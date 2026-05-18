"""
금감원 징계공시 모니터링

하는 일:
  1. 금감원 징계공시 페이지에 새 글이 올라왔는지 확인
  2. 새 글이 있으면 PDF 다운로드
  3. Telegram으로 알림 전송

사용법:
  python monitor.py                  ← 1회 실행
  python monitor.py --daemon         ← 매일 02:00 자동 확인
  python monitor.py --check-times 02:00 --daemon
  python monitor.py --test
  python monitor.py --reset

기본 동작:
  - 신규 공시가 있으면 Telegram으로 "링크만" 전송
  - PDF 다운로드는 ALERT_LINK_ONLY=0 일 때 수행하고 Telegram으로 저장 정보를 전송
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

# ============================================================
# 설정
# ============================================================

# Telegram Bot 설정은 환경변수/Actions secret으로만 주입한다.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# PDF 저장 폴더
PDF_FOLDER = Path(__file__).parent / "pdfs"

# 기본 확인 시간(로컬 시간)
DEFAULT_CHECK_TIMES = os.getenv("CHECK_TIMES", "02:00")

# 1(기본): 링크만 알림, 0: PDF 다운로드/전송까지 수행
ALERT_LINK_ONLY = os.getenv("ALERT_LINK_ONLY", "1").strip().lower() not in ("0", "false", "no")

# ============================================================
# 내부 상수
# ============================================================

FSS_LIST_URL = "https://www.fss.or.kr/fss/job/openInfo/list.do?menuNo=200476"
FSS_BASE = "https://www.fss.or.kr"
SEEN_FILE = Path(__file__).parent / "seen.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

REQUEST_RETRY = 3
REQUEST_BACKOFF_SEC = 2
DEFAULT_MAX_LIST_PAGES = int(os.getenv("FSS_MAX_LIST_PAGES", "30"))


# ============================================================
# 공통 유틸
# ============================================================

def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """간단 재시도 래퍼."""
    timeout = kwargs.pop("timeout", 30)

    for attempt in range(1, REQUEST_RETRY + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            return resp
        except requests.RequestException:
            if attempt == REQUEST_RETRY:
                raise
            time.sleep(REQUEST_BACKOFF_SEC * attempt)

    raise RuntimeError("요청 재시도 로직 오류")


def normalize_date(date_str: str) -> str:
    """YYYY.MM.DD 형식으로 표준화."""
    if not date_str:
        return ""
    digits = re.sub(r"\D", "", date_str)
    if re.fullmatch(r"20\d{6}", digits):
        return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"
    match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", date_str)
    if not match:
        return date_str.strip()
    y, m, d = match.groups()
    return f"{y}.{int(m):02d}.{int(d):02d}"


def parse_date(date_str: str) -> datetime:
    """정렬용 날짜 파서. 실패 시 아주 과거 날짜 반환."""
    match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", date_str or "")
    if not match:
        return datetime(1900, 1, 1)
    y, m, d = match.groups()
    return datetime(int(y), int(m), int(d))


def date_to_int(date_str: str) -> int:
    """YYYY.MM.DD -> 20260227 형태 정수. 실패 시 0."""
    if not date_str:
        return 0
    normalized = normalize_date(date_str)
    match = re.fullmatch(r"(20\d{2})\.(\d{2})\.(\d{2})", normalized)
    if not match:
        return 0
    y, m, d = match.groups()
    return int(f"{y}{m}{d}")


def max_notice_date(items: list[dict]) -> str:
    """아이템 목록에서 가장 큰 공시일(YYYY.MM.DD)을 반환."""
    dates = []
    for item in items:
        normalized = normalize_date(item.get("date", ""))
        if date_to_int(normalized):
            dates.append(normalized)
    if not dates:
        return ""
    return max(dates, key=date_to_int)


def make_absolute_url(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if not raw or raw == "#" or raw.lower().startswith("javascript:"):
        return ""
    return urljoin(FSS_BASE, raw)


def extract_first_date(text: str) -> str:
    match = re.search(r"20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}", text or "")
    return normalize_date(match.group(0)) if match else ""


def extract_item_id(text: str) -> str:
    """링크/스크립트 문자열에서 공시 ID 후보를 추출."""
    if not text:
        return ""

    patterns = [
        r"openInfoSn\s*[=:]\s*['\"]?(\d{3,})",
        r"openInfoSn=(\d{3,})",
        r"fn_\w+\(['\"]?(\d{3,})['\"]?\)",
        r"\((?:\s*['\"])?(\d{3,})(?:['\"])?\s*(?:,|\))",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def build_item_key(item_id: str, title: str, date_str: str, detail_url: str) -> str:
    if item_id:
        return f"id:{item_id}"
    raw = f"{title}|{normalize_date(date_str)}|{detail_url}".encode("utf-8", errors="ignore")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    return f"hash:{digest}"


def sanitize_filename(filename: str) -> str:
    filename = filename.strip().strip("\"'")
    if not filename:
        return "attachment.pdf"

    filename = filename.replace("\\", "_").replace("/", "_")
    filename = re.sub(r"[<>:\\|?*]", "_", filename)
    filename = re.sub(r"\s+", " ", filename).strip()

    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    return filename


def decode_filename_from_cd(cd: str) -> str:
    if not cd:
        return ""

    # RFC 5987: filename*=UTF-8''...
    match_star = re.search(r"filename\*\s*=\s*([^;]+)", cd, re.IGNORECASE)
    if match_star:
        value = match_star.group(1).strip().strip("\"")
        if "''" in value:
            _, encoded = value.split("''", 1)
            return unquote(encoded)
        return unquote(value)

    match_plain = re.search(r"filename\s*=\s*([^;]+)", cd, re.IGNORECASE)
    if match_plain:
        value = match_plain.group(1).strip().strip("\"")
        return unquote(value)

    return ""


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def is_probably_pdf(content: bytes, content_type: str, filename: str) -> bool:
    content_type = (content_type or "").lower()
    if "pdf" in content_type:
        return True
    if filename.lower().endswith(".pdf"):
        return True
    return content[:4] == b"%PDF"


# ============================================================
# 상태 저장
# ============================================================

def load_state_payload() -> dict:
    """상태 파일 원본 payload를 불러온다."""
    if not SEEN_FILE.exists():
        return {}

    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        print("⚠ seen.json 읽기 실패: 기록을 비우고 계속 진행합니다.")
        return {}

    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"seen_keys": [str(x) for x in data]}
    return {}


def load_state() -> tuple[set[str], str]:
    """상태 파일에서 seen key와 최신 공시일(high-water date)을 불러온다."""
    data = load_state_payload()
    if not data:
        return set(), ""

    seen = data.get("seen_keys", [])
    latest_notice_date = normalize_date(str(data.get("latest_notice_date", "")))
    if isinstance(seen, list):
        return set(str(x) for x in seen), latest_notice_date

    return set(), ""


def notice_record(item: dict, status: str, recorded_at: str) -> dict:
    """seen.json에 사람이 확인할 수 있는 알림 메타데이터를 남긴다."""
    return {
        "id": item.get("id", ""),
        "key": item.get("key", ""),
        "title": item.get("title", ""),
        "date": normalize_date(item.get("date", "")),
        "url": item.get("url", ""),
        "status": status,
        "recorded_at": recorded_at,
    }


def save_state(seen: set[str], latest_notice_date: str, seen_items: dict = None):
    """상태 파일 저장."""
    previous = load_state_payload()
    previous_items = previous.get("seen_items", {})
    if not isinstance(previous_items, dict):
        previous_items = {}

    merged_items = {k: v for k, v in previous_items.items() if k in seen}
    if seen_items:
        for key, record in seen_items.items():
            if key in seen:
                merged_items[key] = record

    payload = {
        "seen_keys": sorted(seen),
        "seen_items": {k: merged_items[k] for k in sorted(merged_items)},
        "latest_notice_date": normalize_date(latest_notice_date),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    SEEN_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_seen() -> set[str]:
    """하위호환: seen key 목록만 반환."""
    seen, _ = load_state()
    return seen


def save_seen(seen: set[str]):
    """하위호환: latest_notice_date를 유지하며 seen만 저장."""
    _, latest_notice_date = load_state()
    save_state(seen, latest_notice_date)


def move_to_trash(path: Path) -> None:
    """저장소 규칙에 따라 파일 삭제 대신 trash로 이동한다."""
    trash_bin = shutil.which("trash")
    if not trash_bin:
        raise RuntimeError("trash 명령을 찾지 못했습니다. seen.json을 직접 확인해 주세요.")
    subprocess.run([trash_bin, str(path)], check=True)


# ============================================================
# 목록/첨부 파싱
# ============================================================

def build_detail_url(href: str, onclick: str, item_id: str) -> str:
    """상세 URL 구성."""
    href = (href or "").strip()
    onclick = (onclick or "").strip()

    # href가 직접 상세 URL
    abs_href = make_absolute_url(href)
    if abs_href and ("openInfoSn=" in abs_href or "view.do" in abs_href):
        return abs_href

    # onclick 내 URL 문자열
    quoted_urls = re.findall(r"['\"]((?:https?://|/)[^'\"]+)['\"]", onclick)
    for u in quoted_urls:
        abs_u = make_absolute_url(u)
        if abs_u:
            return abs_u

    # ID가 있으면 표준 상세 URL 조합
    if item_id:
        return f"{FSS_BASE}/fss/job/openInfo/view.do?menuNo=200476&openInfoSn={item_id}"

    return abs_href


def list_page_url(page_index: int) -> str:
    """목록 페이지 번호를 반영한 URL을 만든다."""
    parsed = urlparse(FSS_LIST_URL)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["pageIndex"] = str(page_index)
    return urlunparse(parsed._replace(query=urlencode(query)))


def parse_list_page(html_text: str) -> list[dict]:
    """금감원 징계공시 목록 HTML 한 페이지에서 공시 항목을 파싱한다."""
    soup = BeautifulSoup(html_text, "html.parser")
    items: dict[str, dict] = {}

    # 1) 표 기반 파싱(현재 금감원 구조)
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        org_name = tds[1].get_text(" ", strip=True)
        raw_date = tds[2].get_text(" ", strip=True)
        date_str = normalize_date(raw_date)
        a = tr.find("a", href=True)

        if not org_name or not a or not date_to_int(date_str):
            continue

        detail_url = make_absolute_url(a.get("href", ""))
        if not detail_url or "openInfo/view.do" not in detail_url:
            continue

        exam_mgmt_no = re.search(r"examMgmtNo=([^&]+)", detail_url)
        em_open_seq = re.search(r"emOpenSeq=([^&]+)", detail_url)
        if exam_mgmt_no and em_open_seq:
            item_id = f"{exam_mgmt_no.group(1)}_{em_open_seq.group(1)}"
        else:
            item_id = extract_item_id(detail_url)

        title = f"{org_name} 제재관련 공시"
        key = build_item_key(item_id, title, date_str, detail_url)
        items[key] = {
            "id": item_id,
            "key": key,
            "title": title,
            "date": date_str,
            "url": detail_url,
        }

    # 2) 예외 구조 대비 fallback 파싱
    if not items:
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a"):
            href = a.get("href", "")
            onclick = a.get("onclick", "")
            title = a.get_text(" ", strip=True)

            if not title or len(title) < 2:
                continue

            combined = f"{href} {onclick}"
            if not re.search(r"openInfoSn|view\.do|fn_", combined):
                continue

            item_id = extract_item_id(combined)
            detail_url = build_detail_url(href, onclick, item_id)
            if not detail_url:
                continue

            parent = a.find_parent(["tr", "li", "div"])
            date_str = extract_first_date(parent.get_text(" ", strip=True) if parent else "")
            if not item_id and not date_to_int(date_str):
                continue
            if "openInfo/view.do" not in detail_url and "openInfoSn=" not in detail_url:
                continue

            key = build_item_key(item_id, title, date_str, detail_url)
            items[key] = {
                "id": item_id,
                "key": key,
                "title": title,
                "date": date_str,
                "url": detail_url,
            }

    return list(items.values())


def fetch_list(max_pages: int = DEFAULT_MAX_LIST_PAGES) -> list[dict]:
    """
    금감원 징계공시 목록 페이지에서 공시 항목을 가져온다.
    대량 게시 때 신규 공시가 1페이지 밖으로 밀릴 수 있으므로 여러 페이지를 훑는다.
    반환: [{"id": "12345", "key": "id:12345", "title": "...", "date": "...", "url": "..."}, ...]
    """
    print("금감원 사이트 접속 중...")

    items: dict[str, dict] = {}

    for page_index in range(1, max(1, max_pages) + 1):
        resp = request_with_retry("GET", list_page_url(page_index), headers=HEADERS, timeout=30)
        resp.raise_for_status()

        page_items = parse_list_page(resp.text)
        if not page_items:
            break

        before_count = len(items)
        for item in page_items:
            items[item["key"]] = item

        if len(items) == before_count:
            break

    result = list(items.values())
    result.sort(key=lambda x: (parse_date(x.get("date", "")), x.get("id", "")), reverse=True)

    print(f"  → 공시 후보 {len(result)}건 확인 ({max(1, max_pages)}페이지 스캔)")
    return result


def extract_download_urls_from_anchor(a) -> list[str]:
    """상세 페이지의 앵커에서 다운로드 URL 후보를 수집."""
    href = a.get("href", "")
    onclick = a.get("onclick", "")
    text = a.get_text(" ", strip=True)
    combined = f"{href} {onclick} {text}".lower()

    if not any(k in combined for k in ["pdf", "첨부", "download", "down", "file", "atch"]):
        return []

    urls = []

    # href 자체
    abs_href = make_absolute_url(href)
    if abs_href:
        urls.append(abs_href)

    # onclick/href 안의 문자열 URL
    raw = f"{href} {onclick}"
    for u in re.findall(r"['\"]((?:https?://|/)[^'\"]+)['\"]", raw):
        abs_u = make_absolute_url(u)
        if abs_u:
            urls.append(abs_u)

    # 일부 사이트는 문자열 결합이 아닌 상대경로가 그대로 존재
    for u in re.findall(r"(/[^\s'\"()]+)", raw):
        if any(k in u.lower() for k in ["download", "down", "file", "atch", ".pdf"]):
            abs_u = make_absolute_url(u)
            if abs_u:
                urls.append(abs_u)

    # 중복 제거(순서 유지)
    deduped = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped


def download_pdfs(item: dict) -> list[Path]:
    """상세 페이지에서 첨부 PDF를 찾아 다운로드한다."""
    print(f"  상세 페이지 접속: {item['title'][:40]}...")

    try:
        resp = request_with_retry("GET", item["url"], headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ⚠ 상세 페이지 접속 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # 후보 URL 수집
    candidates = []
    for a in soup.find_all("a"):
        candidates.extend(extract_download_urls_from_anchor(a))

    # 중복 제거
    deduped_urls = []
    seen_url = set()
    for url in candidates:
        if url not in seen_url:
            seen_url.add(url)
            deduped_urls.append(url)

    if not deduped_urls:
        print("  ⚠ 첨부 PDF 링크를 찾지 못했습니다")
        return []

    PDF_FOLDER.mkdir(exist_ok=True)
    downloaded = []

    for url in deduped_urls:
        try:
            r = request_with_retry("GET", url, headers=HEADERS, timeout=60)
            if r.status_code != 200:
                continue

            cd = r.headers.get("Content-Disposition", "")
            content_type = r.headers.get("Content-Type", "")
            filename = decode_filename_from_cd(cd)

            if not filename:
                guessed = url.split("?")[0].rstrip("/").split("/")[-1]
                filename = guessed or "attachment.pdf"

            filename = sanitize_filename(filename)

            # 실제로 PDF가 아니면 스킵
            if not is_probably_pdf(r.content, content_type, filename):
                continue

            prefix = (item.get("date", "").replace(".", "") or datetime.now().strftime("%Y%m%d"))
            item_id = item.get("id") or item.get("key", "item").replace(":", "_")
            saved_name = sanitize_filename(f"{prefix}_{item_id}_{filename}")

            path = ensure_unique_path(PDF_FOLDER / saved_name)
            path.write_bytes(r.content)

            size_kb = path.stat().st_size / 1024
            print(f"  ✓ PDF 다운로드 완료: {path.name} ({size_kb:.0f}KB)")
            downloaded.append(path)

        except Exception as e:
            print(f"  ⚠ PDF 다운로드 실패: {e}")

    if not downloaded:
        print("  ⚠ PDF 링크는 있었지만 실제 PDF 다운로드에는 실패했습니다")

    return downloaded


# ============================================================
# Telegram 전송
# ============================================================

def build_telegram_notice_text(item: dict, pdf_paths: Optional[list[Path]] = None) -> str:
    pdf_lines = ""
    if pdf_paths:
        pdf_lines = "\nPDF: " + ", ".join(path.name for path in pdf_paths)
    return (
        "금감원 새 징계공시\n"
        f"제목: {item.get('title', '(제목 없음)')}\n"
        f"공시일: {item.get('date', '-')}\n"
        f"원문: {item.get('url', FSS_LIST_URL)}"
        f"{pdf_lines}"
    )


def send_telegram_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  ⚠ TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 설정되지 않았습니다 (알림 건너뜀)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = request_with_retry(
        "POST",
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=10,
    )
    if resp.status_code == 200:
        print("  ✓ Telegram 알림 발송 완료")
        return True
    print(f"  ⚠ Telegram 알림 발송 실패: HTTP {resp.status_code} {resp.text[:200]}")
    return False


def send_telegram_link_alert(item: dict) -> bool:
    """신규 공시 링크를 Telegram으로 전송."""
    return send_telegram_message(build_telegram_notice_text(item))


def send_telegram_notification(item: dict, pdf_paths: list[Path]) -> bool:
    """PDF 다운로드 후에도 Telegram으로 공시 링크와 PDF 저장 정보를 알림."""
    return send_telegram_message(build_telegram_notice_text(item, pdf_paths))


# ============================================================
# 실행 흐름
# ============================================================

def run_once() -> int:
    """1회 실행. 반환값: 신규 처리 건수"""
    print("=" * 58)
    print(f"금감원 징계공시 모니터링  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 58)

    try:
        items = fetch_list()
    except Exception as e:
        print(f"❌ 금감원 사이트 접속 실패: {e}")
        return 0

    if not items:
        print("⚠ 공시 목록을 파싱하지 못했습니다. 사이트 구조를 확인하세요.")
        return 0

    first_run = not SEEN_FILE.exists()
    seen, latest_notice_date = load_state()

    if first_run:
        baseline = {i["key"] for i in items}
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        seen_items = {i["key"]: notice_record(i, "baseline", now_text) for i in items}
        latest_notice_date = max_notice_date(items)
        save_state(baseline, latest_notice_date, seen_items)
        print("\n초기 실행: 현재 공시 목록을 기준선으로 저장했습니다.")
        print("다음 실행부터 신규 공시만 알림합니다.")
        return 0

    # 구버전 상태파일(최신 공시일 없음) 보정
    if not latest_notice_date:
        seen_items = [i for i in items if i["key"] in seen]
        latest_notice_date = max_notice_date(seen_items)

    new_items = [i for i in items if i["key"] not in seen]

    if not new_items:
        print("\n새로운 공시 없음 ✓")
        return 0

    print(f"\n신규 공시 {len(new_items)}건 발견\n")

    processed = 0
    for item in new_items:
        print(f"[{item.get('date', '-')}] {item['title']}")

        delivered = False
        if ALERT_LINK_ONLY:
            delivered = send_telegram_link_alert(item)
        else:
            pdfs = download_pdfs(item)
            time.sleep(1)
            delivered = send_telegram_notification(item, pdfs)

        if delivered:
            item_date = normalize_date(item.get("date", ""))
            item_date_num = date_to_int(item_date)
            latest_date_num = date_to_int(latest_notice_date)
            seen.add(item["key"])
            if item_date_num and item_date_num > latest_date_num:
                latest_notice_date = item_date
            now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_state(seen, latest_notice_date, {item["key"]: notice_record(item, "notified", now_text)})
        else:
            print("  ⚠ 알림 전송 실패: seen에 기록하지 않고 다음 실행에 재시도합니다.")

        processed += 1
        print()

    print(f"완료: 신규 {processed}건 처리")
    return processed


def parse_check_times(raw: str) -> list[str]:
    """HH:MM,HH:MM 문자열을 정렬된 시간 목록으로 변환."""
    values = []
    for part in (raw or "").split(","):
        t = part.strip()
        if not t:
            continue
        if re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", t):
            values.append(t)

    unique = sorted(set(values))
    if not unique:
        raise ValueError("확인 시간 형식이 잘못되었습니다. 예: 02:00")
    return unique


def next_run_at(now: datetime, check_times: list[str]) -> datetime:
    """다음 실행 시각을 계산."""
    today = now.date()

    candidates = []
    for t in check_times:
        hh, mm = t.split(":")
        dt = datetime(today.year, today.month, today.day, int(hh), int(mm), 0)
        if dt >= now:
            candidates.append(dt)

    if candidates:
        return min(candidates)

    hh, mm = check_times[0].split(":")
    tomorrow = now + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, int(hh), int(mm), 0)


def run_daemon(check_times: list[str]):
    """02:00 등 지정 시간마다 자동 실행."""
    print("=" * 58)
    print(f"스케줄 모드 시작: {', '.join(check_times)}")
    print("중지하려면 Ctrl+C")
    print("=" * 58)

    last_slot = ""

    while True:
        now = datetime.now()
        slot = next_run_at(now, check_times)
        slot_key = slot.strftime("%Y-%m-%d %H:%M")

        wait_sec = max(1, int((slot - now).total_seconds()))
        print(f"다음 확인 시각: {slot_key} (약 {wait_sec // 60}분 후)")

        while True:
            remaining = (slot - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(60, max(1, int(remaining))))

        # 같은 슬롯 중복 실행 방지
        if slot_key != last_slot:
            try:
                run_once()
            except Exception as e:
                print(f"⚠ 스케줄 실행 중 오류: {e}")
            last_slot = slot_key

        time.sleep(2)


def run_test(check_times: list[str]):
    """설치 후 테스트용"""
    print("\n[테스트 1] 금감원 사이트 접속...")
    try:
        items = fetch_list()
        if items:
            print(f"  ✓ 성공! 공시 후보 {len(items)}건 확인")
            print(f"  최신 공시: {items[0]['title'][:60]}")
        else:
            print("  ⚠ 접속은 됐는데 목록 파싱 실패")
    except Exception as e:
        print(f"  ❌ 접속 실패: {e}")

    print("\n[테스트 2] Telegram 전송 경로...")
    mode = "Telegram 링크 알림 전용(기본)" if ALERT_LINK_ONLY else "PDF 다운로드 후 Telegram 알림"
    print(f"  현재 모드: {mode}")

    test_item = {
        "id": "test",
        "key": "id:test",
        "title": "[테스트] 금감원 징계공시 알림 테스트입니다",
        "date": datetime.now().strftime("%Y.%m.%d"),
        "url": FSS_LIST_URL,
    }

    try:
        if ALERT_LINK_ONLY:
            send_telegram_link_alert(test_item)
        else:
            send_telegram_notification(test_item, [])
    except Exception as e:
        print(f"  ⚠ Telegram 테스트 중 오류: {e}")

    print("\n[테스트 3] PDF 저장 폴더...")
    PDF_FOLDER.mkdir(exist_ok=True)
    print(f"  ✓ {PDF_FOLDER}")

    print("\n[테스트 4] 스케줄 시간 파싱...")
    print(f"  ✓ {', '.join(check_times)}")

    print("\n" + "=" * 58)
    print("테스트 완료")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="금감원 징계공시 모니터링")
    parser.add_argument("--test", action="store_true", help="연결/설정 테스트")
    parser.add_argument("--reset", action="store_true", help="seen.json 초기화")
    parser.add_argument("--daemon", action="store_true", help="스케줄 모드로 실행")
    parser.add_argument(
        "--check-times",
        default=DEFAULT_CHECK_TIMES,
        help="확인 시각(HH:MM,HH:MM). 기본값: 02:00",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.reset:
        if SEEN_FILE.exists():
            move_to_trash(SEEN_FILE)
        print("기록을 휴지통으로 이동했습니다. 다음 실행 시 기존 글도 신규로 처리됩니다.")
        return

    try:
        check_times = parse_check_times(args.check_times)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    if args.test:
        run_test(check_times)
        return

    if args.daemon:
        try:
            run_daemon(check_times)
        except KeyboardInterrupt:
            print("\n스케줄 모드를 종료합니다.")
        return

    run_once()


if __name__ == "__main__":
    main()
