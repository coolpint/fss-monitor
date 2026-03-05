"""
금감원 징계공시 모니터링

하는 일:
  1. 금감원 징계공시 페이지에 새 글이 올라왔는지 확인
  2. 새 글이 있으면 PDF 다운로드
  3. Teams 채널로 알림 전송
     - Graph API 설정 시: PDF를 채널 파일 폴더에 업로드 + 메시지 전송
     - 미설정 시: Incoming Webhook 카드 알림(파일 업로드 불가)

사용법:
  python monitor.py                  ← 1회 실행
  python monitor.py --daemon         ← 매일 09:00, 16:00 자동 확인
  python monitor.py --check-times 09:00,16:00 --daemon
  python monitor.py --test
  python monitor.py --reset

기본 동작:
  - 신규 공시가 있으면 Teams로 "링크만" 전송
  - PDF 다운로드/업로드는 ALERT_LINK_ONLY=0 일 때만 수행
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# 설정
# ============================================================

# 기존 하드코드 URL 유지 + 환경변수 우선
DEFAULT_WEBHOOK_URL = (
    "https://hoamlaw2022.webhook.office.com/webhookb2/75c09bd8-ec98-4dcd-bed5-"
    "488a59a95b8f@eacf98ab-6217-42c4-9f62-193901c7f469/IncomingWebhook/"
    "883f7dfbc0bd43988fb465da5efd0121/e1240353-937d-4363-860a-62a3f22bafec/"
    "V2UmEzLk9XKv5m55vTK8_eaH8DMtnCn30oYx8ukZniqwY1"
)
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", DEFAULT_WEBHOOK_URL)

# Graph API 설정(파일 업로드용)
TEAMS_TENANT_ID = os.getenv("TEAMS_TENANT_ID", "")
TEAMS_CLIENT_ID = os.getenv("TEAMS_CLIENT_ID", "")
TEAMS_CLIENT_SECRET = os.getenv("TEAMS_CLIENT_SECRET", "")
TEAMS_TEAM_ID = os.getenv("TEAMS_TEAM_ID", "")
TEAMS_CHANNEL_ID = os.getenv("TEAMS_CHANNEL_ID", "")

# PDF 저장 폴더
PDF_FOLDER = Path(__file__).parent / "pdfs"

# 기본 확인 시간(로컬 시간)
DEFAULT_CHECK_TIMES = os.getenv("CHECK_TIMES", "09:00,16:00")

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

def load_seen() -> set[str]:
    """이미 확인한 공시 key 목록을 불러온다."""
    if not SEEN_FILE.exists():
        return set()

    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        print("⚠ seen.json 읽기 실패: 기록을 비우고 계속 진행합니다.")
        return set()

    if isinstance(data, list):
        # 구버전 호환
        return set(str(x) for x in data)

    if isinstance(data, dict):
        seen = data.get("seen_keys", [])
        if isinstance(seen, list):
            return set(str(x) for x in seen)

    return set()


def save_seen(seen: set[str]):
    """확인한 공시 key 목록을 저장한다."""
    payload = {
        "seen_keys": sorted(seen),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    SEEN_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def fetch_list() -> list[dict]:
    """
    금감원 징계공시 목록 페이지에서 공시 항목을 가져온다.
    반환: [{"id": "12345", "key": "id:12345", "title": "...", "date": "...", "url": "..."}, ...]
    """
    print("금감원 사이트 접속 중...")

    resp = request_with_retry("GET", FSS_LIST_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
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

        if not org_name or not a:
            continue

        detail_url = make_absolute_url(a.get("href", ""))
        if not detail_url:
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

            key = build_item_key(item_id, title, date_str, detail_url)
            items[key] = {
                "id": item_id,
                "key": key,
                "title": title,
                "date": date_str,
                "url": detail_url,
            }

    result = list(items.values())
    result.sort(key=lambda x: (parse_date(x.get("date", "")), x.get("id", "")), reverse=True)

    print(f"  → 공시 후보 {len(result)}건 확인")
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
# Teams 전송
# ============================================================

def is_graph_enabled() -> bool:
    return all([
        TEAMS_TENANT_ID,
        TEAMS_CLIENT_ID,
        TEAMS_CLIENT_SECRET,
        TEAMS_TEAM_ID,
        TEAMS_CHANNEL_ID,
    ])


def graph_token() -> str:
    token_url = f"https://login.microsoftonline.com/{TEAMS_TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": TEAMS_CLIENT_ID,
        "client_secret": TEAMS_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }

    resp = request_with_retry("POST", token_url, data=data, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Graph 토큰 발급 실패: HTTP {resp.status_code} {resp.text[:300]}")

    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Graph access_token 누락")
    return token


def graph_request(method: str, path: str, token: str, **kwargs) -> requests.Response:
    url = f"https://graph.microsoft.com/v1.0{path}"
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    return request_with_retry(method, url, headers=headers, **kwargs)


def graph_upload_pdf_to_channel(pdf_path: Path, token: str) -> str:
    # 채널 파일 폴더 조회
    folder_resp = graph_request(
        "GET",
        f"/teams/{TEAMS_TEAM_ID}/channels/{TEAMS_CHANNEL_ID}/filesFolder",
        token,
        timeout=30,
    )
    if folder_resp.status_code != 200:
        raise RuntimeError(f"filesFolder 조회 실패: HTTP {folder_resp.status_code} {folder_resp.text[:200]}")

    folder = folder_resp.json()
    drive_id = folder.get("parentReference", {}).get("driveId")
    folder_id = folder.get("id")

    if not drive_id or not folder_id:
        raise RuntimeError("filesFolder 응답에서 driveId/id를 찾지 못했습니다")

    upload_name = quote(pdf_path.name, safe="")
    upload_path = f"/drives/{drive_id}/items/{folder_id}:/{upload_name}:/content"

    data = pdf_path.read_bytes()
    up_resp = graph_request(
        "PUT",
        upload_path,
        token,
        headers={"Content-Type": "application/pdf"},
        data=data,
        timeout=120,
    )

    if up_resp.status_code not in (200, 201):
        raise RuntimeError(f"파일 업로드 실패: HTTP {up_resp.status_code} {up_resp.text[:300]}")

    uploaded = up_resp.json()
    web_url = uploaded.get("webUrl")
    if not web_url:
        raise RuntimeError("업로드 성공했으나 webUrl이 없습니다")

    return web_url


def graph_post_channel_message(item: dict, file_links: list[tuple[str, str]], token: str):
    title = html.escape(item.get("title", "(제목 없음)"))
    date_text = html.escape(item.get("date", "-"))
    source_url = html.escape(item.get("url", FSS_LIST_URL))

    if file_links:
        links_html = "".join(
            [f"<li><a href='{html.escape(url)}'>{html.escape(name)}</a></li>" for name, url in file_links]
        )
    else:
        links_html = "<li>(PDF 없음)</li>"

    content = (
        "<p><b>금감원 새 징계공시</b></p>"
        f"<p><b>제목</b>: {title}<br/>"
        f"<b>공시일</b>: {date_text}<br/>"
        f"<a href='{source_url}'>원문 보기</a></p>"
        f"<p><b>첨부 PDF</b></p><ul>{links_html}</ul>"
    )

    body = {
        "body": {
            "contentType": "html",
            "content": content,
        }
    }

    msg_resp = graph_request(
        "POST",
        f"/teams/{TEAMS_TEAM_ID}/channels/{TEAMS_CHANNEL_ID}/messages",
        token,
        headers={"Content-Type": "application/json"},
        json=body,
        timeout=30,
    )

    if msg_resp.status_code not in (200, 201):
        raise RuntimeError(f"채널 메시지 전송 실패: HTTP {msg_resp.status_code} {msg_resp.text[:300]}")


def send_teams_alert_webhook(item: dict, pdf_paths: list[Path]) -> bool:
    """Incoming Webhook 카드 알림(파일 자체 업로드 불가)."""
    if not TEAMS_WEBHOOK_URL:
        print("  ⚠ TEAMS_WEBHOOK_URL이 설정되지 않았습니다 (알림 건너뜀)")
        return False

    pdf_names = [p.name for p in pdf_paths] if pdf_paths else ["(첨부파일 없음)"]

    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "금감원 새 징계공시",
                        "weight": "Bolder",
                        "size": "Large",
                    },
                    {
                        "type": "TextBlock",
                        "text": item.get("title", "(제목 없음)"),
                        "wrap": True,
                        "weight": "Bolder",
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {"title": "공시일", "value": item.get("date", "-")},
                            {"title": "PDF", "value": ", ".join(pdf_names)},
                        ],
                    },
                    {
                        "type": "TextBlock",
                        "text": f"PDF 저장 위치: {PDF_FOLDER}",
                        "size": "Small",
                        "isSubtle": True,
                        "wrap": True,
                    },
                ],
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "금감원 원문 보기",
                        "url": item.get("url", FSS_LIST_URL),
                    }
                ],
            },
        }],
    }

    resp = request_with_retry(
        "POST",
        TEAMS_WEBHOOK_URL,
        json=card,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    if resp.status_code in (200, 202):
        print("  ✓ Teams Webhook 알림 발송 완료")
        return True

    fallback = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": f"금감원 징계공시: {item.get('title', '(제목 없음)')}",
        "sections": [{
            "activityTitle": "금감원 새 징계공시",
            "facts": [
                {"name": "제목", "value": item.get("title", "(제목 없음)")},
                {"name": "공시일", "value": item.get("date", "-")},
                {"name": "PDF", "value": ", ".join(pdf_names)},
            ],
            "markdown": True,
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "원문 보기",
            "targets": [{"os": "default", "uri": item.get("url", FSS_LIST_URL)}],
        }],
    }

    resp2 = request_with_retry("POST", TEAMS_WEBHOOK_URL, json=fallback, timeout=10)
    if resp2.status_code in (200, 202):
        print("  ✓ Teams Webhook 알림 발송 완료 (구형 포맷)")
        return True
    else:
        print(f"  ⚠ Teams Webhook 발송 실패: HTTP {resp2.status_code}")
        return False


def send_teams_link_alert(item: dict) -> bool:
    """신규 공시 링크만 Teams Webhook으로 전송."""
    if not TEAMS_WEBHOOK_URL:
        print("  ⚠ TEAMS_WEBHOOK_URL이 설정되지 않았습니다 (알림 건너뜀)")
        return False

    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": "금감원 새 징계공시",
                        "weight": "Bolder",
                        "size": "Large",
                    },
                    {
                        "type": "TextBlock",
                        "text": item.get("title", "(제목 없음)"),
                        "wrap": True,
                        "weight": "Bolder",
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {"title": "공시일", "value": item.get("date", "-")},
                        ],
                    },
                ],
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "금감원 원문 보기",
                        "url": item.get("url", FSS_LIST_URL),
                    }
                ],
            },
        }],
    }

    resp = request_with_retry(
        "POST",
        TEAMS_WEBHOOK_URL,
        json=card,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if resp.status_code in (200, 202):
        print("  ✓ Teams 링크 알림 발송 완료")
        return True

    fallback = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": f"금감원 징계공시: {item.get('title', '(제목 없음)')}",
        "sections": [{
            "activityTitle": "금감원 새 징계공시",
            "facts": [
                {"name": "제목", "value": item.get("title", "(제목 없음)")},
                {"name": "공시일", "value": item.get("date", "-")},
            ],
            "markdown": True,
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "원문 보기",
            "targets": [{"os": "default", "uri": item.get("url", FSS_LIST_URL)}],
        }],
    }
    resp2 = request_with_retry("POST", TEAMS_WEBHOOK_URL, json=fallback, timeout=10)
    if resp2.status_code in (200, 202):
        print("  ✓ Teams 링크 알림 발송 완료 (구형 포맷)")
        return True
    else:
        print(f"  ⚠ Teams 링크 알림 발송 실패: HTTP {resp2.status_code}")
        return False


def send_teams_notification(item: dict, pdf_paths: list[Path]) -> bool:
    """Graph 우선(파일 업로드), 실패/미설정 시 Webhook fallback."""
    if is_graph_enabled():
        try:
            token = graph_token()
            links = []
            for pdf in pdf_paths:
                web_url = graph_upload_pdf_to_channel(pdf, token)
                links.append((pdf.name, web_url))
            graph_post_channel_message(item, links, token)
            print("  ✓ Teams 채널 전송 완료 (Graph: 파일 업로드 + 메시지)")
            return True
        except Exception as e:
            print(f"  ⚠ Graph 전송 실패, Webhook으로 대체: {e}")
    elif pdf_paths:
        print("  ⚠ Graph 미설정: Webhook 알림만 전송됩니다(Teams 파일 업로드 불가).")

    return send_teams_alert_webhook(item, pdf_paths)


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
    seen = load_seen()

    if first_run:
        baseline = {i["key"] for i in items}
        save_seen(baseline)
        print("\n초기 실행: 현재 공시 목록을 기준선으로 저장했습니다.")
        print("다음 실행부터 신규 공시만 알림합니다.")
        return 0

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
            delivered = send_teams_link_alert(item)
        else:
            pdfs = download_pdfs(item)
            time.sleep(1)
            delivered = send_teams_notification(item, pdfs)

        if delivered:
            seen.add(item["key"])
            save_seen(seen)
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
        raise ValueError("확인 시간 형식이 잘못되었습니다. 예: 09:00,16:00")
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
    """09:00/16:00 등 지정 시간마다 자동 실행."""
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

    print("\n[테스트 2] Teams 전송 경로...")
    if ALERT_LINK_ONLY:
        mode = "Webhook 링크 알림 전용(기본)"
    else:
        mode = "Graph(API, 파일 업로드 가능)" if is_graph_enabled() else "Webhook(파일 업로드 불가)"
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
            send_teams_link_alert(test_item)
        else:
            send_teams_notification(test_item, [])
    except Exception as e:
        print(f"  ⚠ Teams 테스트 중 오류: {e}")

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
        help="확인 시각(HH:MM,HH:MM). 기본값: 09:00,16:00",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.reset:
        if SEEN_FILE.exists():
            SEEN_FILE.unlink()
        print("기록 초기화 완료. 다음 실행 시 기존 글도 신규로 처리됩니다.")
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
