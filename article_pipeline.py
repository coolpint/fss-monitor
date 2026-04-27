"""
금감원 제재공시 기사화 로컬 파이프라인.

이 스크립트는 기존 monitor.py의 금감원 목록/첨부 PDF 파서를 재사용해
로컬 작업 폴더를 만든다. 현재 단계의 책임은 다음과 같다.

1. 신규 또는 지정 공시의 PDF 다운로드
2. PDF 텍스트 추출
3. Gemini "금감원 징계 해설" Gem에 넣을 입력 파일 생성
4. Gemini "신문만평 제작" Gem과 moneynlaw CMS 입력을 위한 handoff 생성

Gemini/CMS 웹 UI 조작은 로그인과 화면 확인이 필요하므로, 이 스크립트는
기본적으로 안전한 승인요청 저장 인계 지점까지만 진행한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import monitor


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "service_config.local.json"
STATUS_VERSION = 1
SAFE_CMS_REVIEW_STATUSES = {"승인요청", "미승인", "draft", "unapproved", "pending", "pending_review"}


@dataclass
class ServiceConfig:
    runs_dir: str = "runs"
    state_file: str = "pipeline_state.json"
    max_gemini_input_chars: int = 120000
    gemini_model_mode: str = "Pro"
    chrome_profile_name: str = "가리봉동"
    chrome_profile_directory: str = ""
    chrome_account_hint: str = ""
    article_gem_url: str = ""
    cartoon_gem_url: str = ""
    cms_admin_url: str = ""
    cms_login_url: str = "https://www.moneynlaw.co.kr/member/login.html"
    cms_write_url: str = "https://www.moneynlaw.co.kr/news/userArticleWriteForm.html"
    cms_review_status: str = "승인요청"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def resolve_path(raw: str | Path, base: Path = ROOT) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return base / path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_safe_cms_review_status(status: str) -> bool:
    return status.strip().lower() in SAFE_CMS_REVIEW_STATUSES


def load_config(path: Path) -> ServiceConfig:
    payload = read_json(path, {})
    config = ServiceConfig(**{k: v for k, v in payload.items() if hasattr(ServiceConfig, k)})

    env_overrides = {
        "FSS_PIPELINE_RUNS_DIR": "runs_dir",
        "FSS_PIPELINE_STATE_FILE": "state_file",
        "FSS_MAX_GEMINI_INPUT_CHARS": "max_gemini_input_chars",
        "FSS_GEMINI_MODEL_MODE": "gemini_model_mode",
        "FSS_CHROME_PROFILE_NAME": "chrome_profile_name",
        "FSS_CHROME_PROFILE_DIRECTORY": "chrome_profile_directory",
        "FSS_CHROME_ACCOUNT_HINT": "chrome_account_hint",
        "FSS_ARTICLE_GEM_URL": "article_gem_url",
        "FSS_CARTOON_GEM_URL": "cartoon_gem_url",
        "MONEYNLAW_ADMIN_URL": "cms_admin_url",
        "MONEYNLAW_LOGIN_URL": "cms_login_url",
        "MONEYNLAW_WRITE_URL": "cms_write_url",
        "MONEYNLAW_REVIEW_STATUS": "cms_review_status",
        "MONEYNLAW_DEFAULT_STATUS": "cms_review_status",
    }
    for env_name, field_name in env_overrides.items():
        value = os.getenv(env_name)
        if value:
            if field_name == "max_gemini_input_chars":
                value = int(value)
            setattr(config, field_name, value)

    return config


def load_state(path: Path) -> dict[str, Any]:
    state = read_json(path, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("processed_keys", [])
    state.setdefault("jobs", {})
    state.setdefault("updated_at", "")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_json(path, state)


def safe_slug(value: str, fallback: str = "item") -> str:
    if re.fullmatch(r"20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}", value or ""):
        value = monitor.normalize_date(value).replace(".", "")
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", value or "").strip("-._")
    return value[:80] or fallback


def item_from_url(url: str, title: str, date_text: str, item_id: str) -> dict[str, str]:
    item_id = item_id or monitor.extract_item_id(url)
    if not item_id:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        item_id = f"url_{digest}"

    date_text = monitor.normalize_date(date_text)
    title = title or "금감원 제재관련 공시"
    key = monitor.build_item_key(item_id, title, date_text, url)
    return {
        "id": item_id,
        "key": key,
        "title": title,
        "date": date_text,
        "url": url,
    }


def choose_items(args: argparse.Namespace, state: dict[str, Any]) -> list[dict[str, str]]:
    if args.item_url:
        return [item_from_url(args.item_url, args.title, args.date, args.item_id)]

    items = monitor.fetch_list()
    if args.latest:
        return items[: args.max_items]

    processed = set(state.get("processed_keys", []))
    new_items = [item for item in items if args.force or item["key"] not in processed]
    return new_items[: args.max_items]


def make_job_dir(runs_dir: Path, item: dict[str, str]) -> Path:
    date_part = safe_slug(item.get("date", ""), datetime.now().strftime("%Y%m%d"))
    id_part = safe_slug(item.get("id", "") or item.get("key", ""), "notice")
    title_part = safe_slug(item.get("title", ""), "fss")
    return runs_dir / f"{date_part}_{id_part}_{title_part}"


def download_job_pdfs(item: dict[str, str], job_dir: Path) -> list[Path]:
    pdf_dir = job_dir / "pdf"
    previous_pdf_folder = monitor.PDF_FOLDER
    monitor.PDF_FOLDER = pdf_dir
    try:
        return monitor.download_pdfs(item)
    finally:
        monitor.PDF_FOLDER = previous_pdf_folder


def extract_text_from_pdf(pdf_path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        return "", "pypdf가 설치되어 있지 않습니다. `pip install -r requirements.txt`를 실행하세요."

    try:
        reader = PdfReader(str(pdf_path))
        chunks = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                chunks.append(f"\n\n--- PDF page {index} ---\n{text}")
        return "\n".join(chunks).strip(), ""
    except Exception as exc:  # PDF 암호화/손상/스캔본 등
        return "", f"{pdf_path.name} 텍스트 추출 실패: {exc}"


def extract_all_pdf_text(pdf_paths: list[Path]) -> tuple[str, list[str]]:
    all_chunks = []
    errors = []
    for pdf_path in pdf_paths:
        text, error = extract_text_from_pdf(pdf_path)
        if error:
            errors.append(error)
            continue
        if text:
            all_chunks.append(f"# Source PDF: {pdf_path.name}\n{text}")
    return "\n\n".join(all_chunks).strip(), errors


def limit_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    marker = f"\n\n[입력 길이 제한으로 {len(text) - max_chars}자가 생략되었습니다. 원문은 pdf_text.txt를 확인하세요.]"
    return text[:max_chars] + marker, True


def write_article_gem_input(
    job_dir: Path,
    item: dict[str, str],
    pdf_paths: list[Path],
    extracted_text: str,
    config: ServiceConfig,
) -> dict[str, Any]:
    limited, truncated = limit_text(extracted_text, config.max_gemini_input_chars)
    pdf_names = ", ".join(path.name for path in pdf_paths) or "(PDF 없음)"

    body = f"""# Gemini 입력: 금감원 징계 해설

아래 금감원 제재 공시 PDF 내용을 근거로 moneynlaw.co.kr에 게재할 기사 초안을 작성해 주세요.

## 공시 메타데이터

- 제목: {item.get("title", "")}
- 공시일: {item.get("date", "")}
- 원문 URL: {item.get("url", "")}
- PDF 파일: {pdf_names}

## 작성 원칙

- Gemini UI에서 모델은 `{config.gemini_model_mode}`로 선택합니다.
- PDF에 있는 사실만 근거로 씁니다.
- 확인되지 않은 배경이나 의도를 단정하지 않습니다.
- 독자가 제재 대상, 위반 내용, 제재 수준, 실무상 의미를 빠르게 이해하게 씁니다.
- 제목 3개 후보, 리드문, 본문, 핵심 포인트, 확인 필요 사항을 포함합니다.
- 기사 말미에 원문 출처로 금융감독원 제재 관련 공시 URL을 남깁니다.

## PDF 추출 내용

{limited}
"""

    path = job_dir / "gemini_article_input.md"
    path.write_text(body, encoding="utf-8")
    return {
        "path": str(path),
        "truncated": truncated,
        "max_chars": config.max_gemini_input_chars,
    }


def write_handoff(
    job_dir: Path,
    item: dict[str, str],
    pdf_paths: list[Path],
    config: ServiceConfig,
    extraction_errors: list[str],
) -> None:
    article_gem = config.article_gem_url or "[설정 필요: FSS_ARTICLE_GEM_URL 또는 service_config.local.json article_gem_url]"
    cartoon_gem = config.cartoon_gem_url or "[설정 필요: FSS_CARTOON_GEM_URL 또는 service_config.local.json cartoon_gem_url]"
    cms_login = config.cms_login_url or config.cms_admin_url or "[설정 필요: MONEYNLAW_LOGIN_URL 또는 service_config.local.json cms_login_url]"
    cms_write = config.cms_write_url or "[설정 필요: MONEYNLAW_WRITE_URL 또는 service_config.local.json cms_write_url]"
    pdf_list = "\n".join(f"- `{path}`" for path in pdf_paths) or "- PDF 다운로드 실패 또는 없음"
    errors = "\n".join(f"- {error}" for error in extraction_errors) or "- 없음"

    handoff = f"""# 작업 인계서

## 공시

- 제목: {item.get("title", "")}
- 공시일: {item.get("date", "")}
- 원문 URL: {item.get("url", "")}

## PDF

{pdf_list}

## 추출 오류

{errors}

## 다음 작업

1. Gemini 기사 Gem을 엽니다.
   - URL: {article_gem}
2. 모델을 `{config.gemini_model_mode}`로 선택합니다.
3. `gemini_article_input.md` 내용을 붙여넣고 기사 초안을 생성합니다.
4. 생성된 기사 초안을 이 폴더의 `article.md`로 저장합니다.
5. Gemini 만평 Gem을 엽니다.
   - URL: {cartoon_gem}
6. 모델을 `{config.gemini_model_mode}`로 선택합니다.
7. `article.md` 내용을 붙여넣고 만평을 생성한 뒤 `cartoon/` 폴더에 다운로드합니다.
8. Chrome 프로필 `{config.chrome_profile_name}`을 사용합니다.
   - 프로필 디렉터리: {config.chrome_profile_directory or "[로컬 Chrome 설정에서 확인]"}
   - 계정 확인 힌트: {config.chrome_account_hint}
9. moneynlaw.co.kr 회원 로그인 화면을 엽니다.
   - URL: {cms_login}
10. 저장된 로그인 정보로 로그인한 뒤 기사 작성 화면을 엽니다.
   - URL: {cms_write}
11. `cms_draft_template.md`를 기준으로 기사와 이미지를 입력합니다.
12. `기사검토`는 `{config.cms_review_status}`로 선택합니다.
13. 기사 입력과 이미지 입력이 끝나면 `저장하기`를 누릅니다. 공개 발행은 별도 승인 단계에서 처리합니다.
"""
    (job_dir / "handoff.md").write_text(handoff, encoding="utf-8")


def write_cartoon_template(job_dir: Path, config: ServiceConfig) -> None:
    body = f"""# Gemini 입력: 신문만평 제작

아래 기사 초안을 바탕으로 신문만평을 제작해 주세요.

## 요구사항

- Gemini UI에서 모델은 `{config.gemini_model_mode}`로 선택합니다.
- 금융감독원 제재 공시의 핵심 쟁점이 한눈에 드러나게 구성합니다.
- 특정 개인의 외모 조롱이나 근거 없는 범죄 단정은 피합니다.
- 기사 초안에 없는 사실을 새로 추가하지 않습니다.
- 신문 지면에 실을 수 있는 풍자적이되 과도하게 선정적이지 않은 이미지로 만듭니다.

## 기사 초안

[여기에 article.md 내용을 붙여넣으세요.]
"""
    (job_dir / "gemini_cartoon_input_template.md").write_text(body, encoding="utf-8")


def write_cms_template(job_dir: Path, item: dict[str, str], config: ServiceConfig) -> None:
    body = f"""# moneynlaw CMS 입력 템플릿

## 브라우저와 로그인

- Chrome 프로필: {config.chrome_profile_name}
- Chrome 프로필 디렉터리: {config.chrome_profile_directory or "[로컬 Chrome 설정에서 확인]"}
- 계정 확인 힌트: {config.chrome_account_hint}
- 로그인 URL: {config.cms_login_url or config.cms_admin_url}
- 기사 작성 URL: {config.cms_write_url}

## 기사 검토

- `기사검토`: {config.cms_review_status}
- 기사 입력과 이미지 입력이 완료되면 `저장하기`를 누름
- 공개 발행은 최종 승인 단계에서 별도 처리

## 원문

- 금감원 공시명: {item.get("title", "")}
- 공시일: {item.get("date", "")}
- 원문 URL: {item.get("url", "")}

## 기사 입력

- 제목: [article.md에서 선택]
- 본문: [article.md 전체 또는 편집본]
- 출처: 금융감독원 제재 관련 공시
- 대표이미지/본문이미지: `cartoon/` 폴더에 다운로드한 만평 이미지
- 태그: 금융감독원, 제재공시, 징계, 금융규제
- 확인 필요: 공개 발행 여부
"""
    (job_dir / "cms_draft_template.md").write_text(body, encoding="utf-8")


def process_item(item: dict[str, str], config: ServiceConfig) -> dict[str, Any]:
    runs_dir = resolve_path(config.runs_dir)
    job_dir = make_job_dir(runs_dir, item)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "cartoon").mkdir(exist_ok=True)

    metadata = {
        "version": STATUS_VERSION,
        "created_at": now_iso(),
        "item": item,
        "config": {
            "chrome_profile_name": config.chrome_profile_name,
            "chrome_profile_directory": config.chrome_profile_directory,
            "chrome_account_hint": config.chrome_account_hint,
            "cms_login_url": config.cms_login_url,
            "cms_write_url": config.cms_write_url,
            "cms_review_status": config.cms_review_status,
            "gemini_model_mode": config.gemini_model_mode,
            "max_gemini_input_chars": config.max_gemini_input_chars,
            "article_gem_configured": bool(config.article_gem_url),
            "cartoon_gem_configured": bool(config.cartoon_gem_url),
            "cms_login_configured": bool(config.cms_login_url or config.cms_admin_url),
            "cms_write_configured": bool(config.cms_write_url),
        },
    }
    write_json(job_dir / "metadata.json", metadata)

    pdf_paths = download_job_pdfs(item, job_dir)
    extracted_text, extraction_errors = extract_all_pdf_text(pdf_paths)
    if extracted_text:
        (job_dir / "pdf_text.txt").write_text(extracted_text, encoding="utf-8")
    else:
        extraction_errors.append("추출된 PDF 텍스트가 없습니다. PDF 업로드 방식 또는 수동 확인이 필요합니다.")

    article_input = write_article_gem_input(job_dir, item, pdf_paths, extracted_text, config)
    write_cartoon_template(job_dir, config)
    write_cms_template(job_dir, item, config)
    write_handoff(job_dir, item, pdf_paths, config, extraction_errors)

    status = {
        "version": STATUS_VERSION,
        "status": "gemini_ready" if pdf_paths and extracted_text else "manual_required",
        "updated_at": now_iso(),
        "item_key": item["key"],
        "job_dir": str(job_dir),
        "pdfs": [str(path) for path in pdf_paths],
        "article_input": article_input,
        "requires": {
            "article_gem_url": not bool(config.article_gem_url),
            "cartoon_gem_url": not bool(config.cartoon_gem_url),
            "cms_login_url": not bool(config.cms_login_url or config.cms_admin_url),
            "cms_write_url": not bool(config.cms_write_url),
            "human_publish_approval": not is_safe_cms_review_status(config.cms_review_status),
        },
        "gemini_model_mode": config.gemini_model_mode,
        "cms_review_status": config.cms_review_status,
        "errors": extraction_errors,
        "next_files": [
            "handoff.md",
            "gemini_article_input.md",
            "gemini_cartoon_input_template.md",
            "cms_draft_template.md",
        ],
    }
    write_json(job_dir / "status.json", status)
    return status


def run_once(args: argparse.Namespace, config: ServiceConfig) -> int:
    state_path = resolve_path(config.state_file)
    state = load_state(state_path)
    items = choose_items(args, state)
    if not items:
        print("처리할 신규 공시가 없습니다.")
        return 0

    processed_keys = set(state.get("processed_keys", []))
    count = 0
    for item in items:
        if not args.force and item["key"] in processed_keys:
            print(f"이미 작업한 공시입니다: {item['title']}")
            continue

        print(f"\n[{item.get('date', '-')}] {item['title']}")
        status = process_item(item, config)
        print(f"  작업 폴더: {status['job_dir']}")
        print(f"  상태: {status['status']}")
        if status["errors"]:
            for error in status["errors"]:
                print(f"  확인 필요: {error}")

        if not args.no_state:
            processed_keys.add(item["key"])
            state["processed_keys"] = sorted(processed_keys)
            state["jobs"][item["key"]] = {
                "status": status["status"],
                "job_dir": status["job_dir"],
                "updated_at": status["updated_at"],
                "title": item.get("title", ""),
                "date": item.get("date", ""),
                "url": item.get("url", ""),
            }
            save_state(state_path, state)

        count += 1

    print(f"\n완료: {count}건 작업 패키지 생성")
    return count


def run_daemon(args: argparse.Namespace, config: ServiceConfig) -> None:
    check_times = monitor.parse_check_times(args.check_times)
    print("=" * 58)
    print(f"로컬 기사 파이프라인 스케줄 시작: {', '.join(check_times)}")
    print("중지하려면 Ctrl+C")
    print("=" * 58)

    args.latest = False
    args.process_new = True
    last_slot = ""

    while True:
        now = datetime.now()
        slot = monitor.next_run_at(now, check_times)
        slot_key = slot.strftime("%Y-%m-%d %H:%M")
        wait_sec = max(1, int((slot - now).total_seconds()))
        print(f"다음 확인 시각: {slot_key} (약 {wait_sec // 60}분 후)")

        while True:
            remaining = (slot - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(60, max(1, int(remaining))))

        if slot_key != last_slot:
            try:
                run_once(args, config)
            except Exception as exc:
                print(f"스케줄 실행 중 오류: {exc}")
            last_slot = slot_key
        time.sleep(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="금감원 제재공시 기사화 로컬 파이프라인")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="로컬 설정 JSON 경로")
    parser.add_argument("--latest", action="store_true", help="최신 공시부터 처리")
    parser.add_argument("--process-new", action="store_true", help="pipeline_state.json 기준 신규 공시 처리")
    parser.add_argument("--item-url", default="", help="Teams 알림 등에서 복사한 금감원 공시 상세 URL")
    parser.add_argument("--title", default="", help="--item-url 사용 시 제목")
    parser.add_argument("--date", default="", help="--item-url 사용 시 공시일")
    parser.add_argument("--item-id", default="", help="--item-url 사용 시 공시 ID")
    parser.add_argument("--max-items", type=int, default=1, help="한 번에 처리할 최대 공시 수")
    parser.add_argument("--force", action="store_true", help="이미 처리한 공시도 다시 작업")
    parser.add_argument("--no-state", action="store_true", help="pipeline_state.json 업데이트 안 함")
    parser.add_argument("--daemon", action="store_true", help="로컬 스케줄러로 반복 실행")
    parser.add_argument("--check-times", default="09:10,16:10", help="--daemon 실행 시 확인 시각")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(resolve_path(args.config))

    if not args.latest and not args.process_new and not args.item_url:
        args.latest = True

    if args.daemon:
        try:
            run_daemon(args, config)
        except KeyboardInterrupt:
            print("\n로컬 기사 파이프라인을 종료합니다.")
        return

    try:
        run_once(args, config)
    except KeyboardInterrupt:
        print("\n사용자 중단")
        sys.exit(130)


if __name__ == "__main__":
    main()
