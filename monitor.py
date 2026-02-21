"""
금감원 징계공시 모니터링

하는 일:
  1. 금감원 징계공시 페이지에 새 글이 올라왔는지 확인
  2. 새 글이 있으면 PDF 다운로드
  3. Teams 채널에 "새 공시 나왔다" 알림 전송

사용법:
  python monitor.py          ← 평소 실행 (새 글만 감지)
  python monitor.py --test   ← 처음 설치 후 테스트
  python monitor.py --reset  ← 기록 초기화 (모든 글을 새 글로 취급)
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# ★ 여기만 수정하세요 ★
# ============================================================

# Teams 채널의 Incoming Webhook URL (위 설명대로 만든 URL을 붙여넣기)
TEAMS_WEBHOOK_URL = "https://hoamlaw2022.webhook.office.com/webhookb2/75c09bd8-ec98-4dcd-bed5-488a59a95b8f@eacf98ab-6217-42c4-9f62-193901c7f469/IncomingWebhook/883f7dfbc0bd43988fb465da5efd0121/e1240353-937d-4363-860a-62a3f22bafec/V2UmEzLk9XKv5m55vTK8_eaH8DMtnCn30oYx8ukZniqwY1"

# PDF 저장 폴더 (기본값: 이 스크립트와 같은 폴더 안의 pdfs/)
PDF_FOLDER = Path(__file__).parent / "pdfs"

# ============================================================
# 아래는 수정할 필요 없습니다
# ============================================================

FSS_URL = "https://www.fss.or.kr/fss/job/openInfo/list.do?menuNo=200476"
FSS_BASE = "https://www.fss.or.kr"
SEEN_FILE = Path(__file__).parent / "seen.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def load_seen() -> set:
    """이미 확인한 공시 ID 목록을 불러온다."""
    if SEEN_FILE.exists():
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return set(data)
    return set()


def save_seen(seen: set):
    """확인한 공시 ID 목록을 저장한다."""
    SEEN_FILE.write_text(
        json.dumps(list(seen), ensure_ascii=False),
        encoding="utf-8"
    )


def fetch_list() -> list[dict]:
    """
    금감원 징계공시 목록 페이지에서 공시 항목을 가져온다.
    반환: [{"id": "12345", "title": "...", "date": "...", "url": "..."}, ...]
    """
    print("금감원 사이트 접속 중...")
    resp = requests.get(FSS_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []

    # 테이블 형태 목록에서 링크 추출
    for a in soup.find_all("a", href=True):
        href = a["href"]

        # openInfoSn=숫자 패턴이 있는 링크만 (징계공시 상세 링크)
        match = re.search(r"openInfoSn=(\d+)", href)
        if not match:
            # 자바스크립트 호출 패턴도 체크 fn_detail('12345')
            match = re.search(r"fn_\w+\(['\"]?(\d+)['\"]?\)", href)
        if not match:
            continue

        item_id = match.group(1)
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        # 주변에서 날짜 찾기
        parent = a.find_parent("tr") or a.find_parent("li") or a.find_parent("div")
        date_str = ""
        if parent:
            date_match = re.search(r"20\d{2}[.\-/]\d{2}[.\-/]\d{2}", parent.get_text())
            if date_match:
                date_str = date_match.group(0)

        # 상세 URL 구성
        if href.startswith("http"):
            detail_url = href
        elif href.startswith("/"):
            detail_url = FSS_BASE + href
        else:
            detail_url = f"{FSS_BASE}/fss/job/openInfo/view.do?menuNo=200476&openInfoSn={item_id}"

        items.append({
            "id": item_id,
            "title": title,
            "date": date_str,
            "url": detail_url,
        })

    # 중복 제거
    unique = {}
    for item in items:
        unique[item["id"]] = item

    print(f"  → 공시 {len(unique)}건 확인")
    return list(unique.values())


def download_pdfs(item: dict) -> list[Path]:
    """상세 페이지에서 첨부 PDF를 찾아 다운로드한다."""
    print(f"  상세 페이지 접속: {item['title'][:40]}...")

    try:
        resp = requests.get(item["url"], headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ⚠ 상세 페이지 접속 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    downloaded = []

    # PDF 링크 찾기 (파일 다운로드 링크들)
    pdf_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # .pdf 확장자, fileDown, download 등의 패턴
        if any(kw in href.lower() for kw in [".pdf", "filedown", "download", "atch"]):
            url = href if href.startswith("http") else FSS_BASE + href
            pdf_links.append(url)

    # onclick 속성에서도 찾기
    for a in soup.find_all("a", onclick=True):
        onclick = a["onclick"]
        match = re.search(r"fn_\w*[Dd]own\w*\(['\"]([^'\"]+)['\"]", onclick)
        if match:
            path = match.group(1)
            url = path if path.startswith("http") else FSS_BASE + path
            pdf_links.append(url)

    if not pdf_links:
        print("  ⚠ 첨부 PDF를 찾지 못했습니다")
        return []

    PDF_FOLDER.mkdir(exist_ok=True)

    for url in pdf_links:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60, stream=True)
            resp.raise_for_status()

            # 파일명 결정
            cd = resp.headers.get("Content-Disposition", "")
            fname_match = re.search(r'filename[*]?=["\']?([^"\';]+)', cd)
            if fname_match:
                filename = fname_match.group(1).strip()
            else:
                filename = f"제재_{item['id']}_{datetime.now().strftime('%Y%m%d')}.pdf"

            filepath = PDF_FOLDER / filename
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)

            size_kb = filepath.stat().st_size / 1024
            print(f"  ✓ PDF 다운로드 완료: {filename} ({size_kb:.0f}KB)")
            downloaded.append(filepath)

        except Exception as e:
            print(f"  ⚠ PDF 다운로드 실패: {e}")

    return downloaded


def send_teams_alert(item: dict, pdf_paths: list[Path]):
    """Teams 채널에 알림을 보낸다."""
    if not TEAMS_WEBHOOK_URL:
        print("  ⚠ TEAMS_WEBHOOK_URL이 설정되지 않았습니다 (알림 건너뜀)")
        return

    # PDF 파일명 목록
    pdf_names = [p.name for p in pdf_paths] if pdf_paths else ["(첨부파일 없음)"]

    # 메시지 카드 구성 (심플한 형태)
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
                        "text": "🔔 금감원 새 징계공시",
                        "weight": "Bolder",
                        "size": "Large",
                    },
                    {
                        "type": "TextBlock",
                        "text": item["title"],
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
                        "text": f"PDF가 {PDF_FOLDER} 폴더에 저장되었습니다.",
                        "size": "Small",
                        "isSubtle": True,
                        "wrap": True,
                    },
                ],
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "금감원 원문 보기",
                        "url": item["url"],
                    }
                ],
            },
        }],
    }

    try:
        resp = requests.post(
            TEAMS_WEBHOOK_URL,
            json=card,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code in (200, 202):
            print("  ✓ Teams 알림 발송 완료")
        else:
            # 구형 Webhook 포맷으로 재시도
            fallback = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "themeColor": "0076D7",
                "summary": f"금감원 징계공시: {item['title']}",
                "sections": [{
                    "activityTitle": "🔔 금감원 새 징계공시",
                    "facts": [
                        {"name": "제목", "value": item["title"]},
                        {"name": "공시일", "value": item.get("date", "-")},
                        {"name": "PDF", "value": ", ".join(pdf_names)},
                    ],
                    "markdown": True,
                }],
                "potentialAction": [{
                    "@type": "OpenUri",
                    "name": "원문 보기",
                    "targets": [{"os": "default", "uri": item["url"]}],
                }],
            }
            resp2 = requests.post(TEAMS_WEBHOOK_URL, json=fallback, timeout=10)
            if resp2.status_code == 200:
                print("  ✓ Teams 알림 발송 완료 (구형 포맷)")
            else:
                print(f"  ⚠ Teams 발송 실패: HTTP {resp2.status_code}")

    except Exception as e:
        print(f"  ⚠ Teams 발송 오류: {e}")


# ============================================================
# 실행
# ============================================================

def main():
    print("=" * 50)
    print(f"금감원 징계공시 모니터링  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 옵션 처리
    if "--reset" in sys.argv:
        if SEEN_FILE.exists():
            SEEN_FILE.unlink()
        print("기록 초기화 완료. 다음 실행 시 모든 글을 새 글로 취급합니다.\n")
        return

    if "--test" in sys.argv:
        run_test()
        return

    # 1. 목록 가져오기
    try:
        items = fetch_list()
    except Exception as e:
        print(f"❌ 금감원 사이트 접속 실패: {e}")
        return

    if not items:
        print("⚠ 공시 목록을 파싱하지 못했습니다.")
        print("  사이트 구조가 바뀌었을 수 있습니다.")
        return

    # 2. 새 글 확인
    seen = load_seen()
    new_items = [i for i in items if i["id"] not in seen]

    if not new_items:
        print("\n새로운 공시 없음 ✓")
        return

    print(f"\n🆕 신규 공시 {len(new_items)}건 발견!\n")

    # 3. 각 신규 공시 처리
    for item in new_items:
        print(f"[{item['date']}] {item['title']}")

        # PDF 다운로드
        pdfs = download_pdfs(item)
        time.sleep(1)

        # Teams 알림
        send_teams_alert(item, pdfs)

        # 처리 완료 표시
        seen.add(item["id"])
        save_seen(seen)
        print()

    print(f"완료! 신규 {len(new_items)}건 처리됨.")


def run_test():
    """설치 후 테스트용"""
    print("\n[테스트 1] 금감원 사이트 접속...")
    try:
        items = fetch_list()
        if items:
            print(f"  ✓ 성공! 공시 {len(items)}건 확인됨")
            print(f"  최신 공시: {items[0]['title'][:50]}")
        else:
            print("  ⚠ 접속은 됐는데 목록 파싱 실패")
            print("  사이트 구조가 바뀌었을 수 있습니다.")
    except Exception as e:
        print(f"  ❌ 접속 실패: {e}")

    print(f"\n[테스트 2] Teams Webhook...")
    if TEAMS_WEBHOOK_URL:
        test_item = {
            "id": "test",
            "title": "[테스트] 금감원 징계공시 알림 테스트입니다",
            "date": datetime.now().strftime("%Y.%m.%d"),
            "url": "https://www.fss.or.kr/fss/job/openInfo/list.do?menuNo=200476",
        }
        send_teams_alert(test_item, [])
    else:
        print("  ⚠ TEAMS_WEBHOOK_URL이 비어 있습니다")
        print("  monitor.py 파일 맨 위의 TEAMS_WEBHOOK_URL에 URL을 붙여넣으세요")

    print(f"\n[테스트 3] PDF 저장 폴더...")
    PDF_FOLDER.mkdir(exist_ok=True)
    print(f"  ✓ {PDF_FOLDER}")

    print("\n" + "=" * 50)
    print("테스트 완료!")


if __name__ == "__main__":
    main()
