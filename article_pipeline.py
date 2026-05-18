"""
금감원 제재공시 기사화 로컬 파이프라인.

이 스크립트는 기존 monitor.py의 금감원 목록/첨부 PDF 파서를 재사용해
로컬 작업 폴더를 만든다. 현재 단계의 책임은 다음과 같다.

1. 신규 또는 지정 공시의 PDF 다운로드
2. PDF 텍스트 추출
3. Auto-Writer 입력 파일 생성
4. Auto-Writer 실행 인계서와 상태 파일 생성

기사 작성, 이미지 생성, moneynlaw CMS 미승인 저장은 Auto-Writer로 인계한다.
이 스크립트는 공개 발행/승인 완료를 수행하지 않는다.
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
SAFE_CMS_REVIEW_STATUSES = {"미승인", "draft", "unapproved", "pending", "pending_review"}
AUTO_WRITER_SOURCE_FILE = "auto_writer_source.md"
AUTO_WRITER_TASK_FILE = "auto_writer_task.md"
AUTO_WRITER_STATE_FILE = "auto_writer_state.json"

FSS_CARTOON_IMAGE_PROMPT = """당신은 뉴요커의 전설적 만평가인 Herbert Block 스타일을 매우 충실하게 구현할 수 있는 재치 넘치는 화가야. 주어진 주제, 키워드 또는 기사 내용을 바탕으로 재미있는 일러스트를 그려야 해.

인종적인 혐오로 오해될 수 있는 스타일은 피해줘. 대신 만평가니까 자유로운 사고는 추천해.

오브제가 너무 많아서 이해하기 복잡한 그림은 지양하도록. 글씨도  사용하지 말 것. 풍자처럼 그림 아래에 한 줄 적는 건 가능. 특히 영어 사용 금지.

검은색 펜화지만, 가벼운 파스텔톤 수채화풍 채색을 옅게 하는 것은 허용

뉴요커 만평 스타일 지향."""


@dataclass
class ServiceConfig:
    runs_dir: str = "runs"
    state_file: str = "pipeline_state.json"
    max_auto_writer_input_chars: int = 120000
    cms_login_url: str = "https://www.moneynlaw.co.kr/member/login.html"
    cms_write_url: str = "https://www.moneynlaw.co.kr/news/userArticleWriteForm.html"
    cms_review_status: str = "미승인"
    auto_writer_project_dir: str = "/Users/sanghoon/codes/Auto-Writer"
    auto_writer_mode: str = "live"
    auto_writer_channel: str = "fss-monitor"


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
        "FSS_MAX_AUTO_WRITER_INPUT_CHARS": "max_auto_writer_input_chars",
        "MONEYNLAW_LOGIN_URL": "cms_login_url",
        "MONEYNLAW_WRITE_URL": "cms_write_url",
        "MONEYNLAW_REVIEW_STATUS": "cms_review_status",
        "MONEYNLAW_DEFAULT_STATUS": "cms_review_status",
        "AUTO_WRITER_PROJECT_DIR": "auto_writer_project_dir",
        "AUTO_WRITER_MODE": "auto_writer_mode",
        "AUTO_WRITER_CHANNEL": "auto_writer_channel",
    }
    for env_name, field_name in env_overrides.items():
        value = os.getenv(env_name)
        if value:
            if field_name == "max_auto_writer_input_chars":
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


def write_handoff(
    job_dir: Path,
    item: dict[str, str],
    pdf_paths: list[Path],
    config: ServiceConfig,
    extraction_errors: list[str],
) -> None:
    project_dir = resolve_path(config.auto_writer_project_dir)
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

1. `auto_writer_source.md`를 확인합니다.
2. Auto-Writer 프로젝트로 이동합니다.
   - 경로: `{project_dir}`
3. `auto_writer_task.md`의 명령을 실행하거나 Auto-Writer 작업 큐에 같은 내용을 넘깁니다.
4. moneynlaw CMS 저장 상태는 `{config.cms_review_status}`로 둡니다.
5. 공개 발행, 승인 완료, 예약 발행은 별도 승인 전까지 하지 않습니다.
6. 저장 결과의 기사 URL/ID와 CMS 상태를 `auto_writer_state.json`에 기록합니다.
"""
    (job_dir / "handoff.md").write_text(handoff, encoding="utf-8")


def write_auto_writer_source(
    job_dir: Path,
    item: dict[str, str],
    pdf_paths: list[Path],
    extracted_text: str,
    config: ServiceConfig,
) -> dict[str, Any]:
    limited, truncated = limit_text(extracted_text, config.max_auto_writer_input_chars)
    pdf_list = "\n".join(f"- {path}" for path in pdf_paths) or "- PDF 없음"
    body = f"""# Auto-Writer 입력: 금감원 징계해설 기사

아래 금감원 제재 관련 공시 PDF 내용을 바탕으로 moneynlaw.co.kr에 저장할 금감원 징계해설 기사를 작성해 주세요.

## 공시 메타데이터

- 제목: {item.get("title", "")}
- 공시일: {item.get("date", "")}
- 원문 URL: {item.get("url", "")}
- PDF 파일:
{pdf_list}

## 기사 작성 원칙

- PDF에 있는 사실만 근거로 씁니다.
- 확인되지 않은 배경, 의도, 책임을 단정하지 않습니다.
- 독자가 제재 대상, 위반 내용, 제재 수준, 실무상 의미를 빠르게 이해하게 씁니다.
- 제목 3개 후보, 리드문, 본문, 핵심 포인트, 확인 필요 사항을 포함합니다.
- 기사 말미에 원문 출처로 금융감독원 제재 관련 공시 URL을 남깁니다.
- 기사검토 상태: {config.cms_review_status}
- moneynlaw CMS에서는 기사검토 상태를 `{config.cms_review_status}`로 둡니다. 공개 발행은 하지 않습니다.

## 이미지 생성 프롬프트 — 이 금감원 징계해설 기사에만 적용

{FSS_CARTOON_IMAGE_PROMPT}

## PDF 추출 내용

{limited}
"""
    path = job_dir / AUTO_WRITER_SOURCE_FILE
    path.write_text(body, encoding="utf-8")
    return {
        "path": str(path),
        "mode": config.auto_writer_mode,
        "channel": config.auto_writer_channel,
        "truncated": truncated,
        "max_chars": config.max_auto_writer_input_chars,
    }


def auto_writer_blockers(config: ServiceConfig) -> list[str]:
    blockers = []
    project_dir = resolve_path(config.auto_writer_project_dir)
    if not project_dir.exists():
        blockers.append(f"Auto-Writer 프로젝트 폴더가 없습니다: {project_dir}")
    if not is_safe_cms_review_status(config.cms_review_status):
        blockers.append(f"CMS 검토 상태 `{config.cms_review_status}`는 자동 저장 가능한 안전 상태가 아닙니다.")
    return blockers


def write_auto_writer_task(
    job_dir: Path,
    item: dict[str, str],
    config: ServiceConfig,
    extraction_errors: list[str],
) -> dict[str, Any]:
    blockers = auto_writer_blockers(config)
    ready = not blockers and not extraction_errors
    blocker_text = "\n".join(f"- {blocker}" for blocker in blockers) or "- 없음"
    error_text = "\n".join(f"- {error}" for error in extraction_errors) or "- 없음"
    project_dir = resolve_path(config.auto_writer_project_dir)
    source_path = job_dir / AUTO_WRITER_SOURCE_FILE
    command = f"node src/index.js run --mode {config.auto_writer_mode} --channel {config.auto_writer_channel} --source {source_path}"

    task = f"""# Auto-Writer 기사화 작업

PDF 다운로드와 텍스트 추출 이후 단계는 Auto-Writer가 맡습니다.

## 작업 폴더

- 경로: `{job_dir}`
- 공시명: {item.get("title", "")}
- 공시일: {item.get("date", "")}
- 원문 URL: {item.get("url", "")}

## 실행 가능 여부

- 실행 가능: {"예" if ready else "아니오"}
- 차단 사유:
{blocker_text}
- PDF/텍스트 추출 오류:
{error_text}

## Auto-Writer 실행

- Auto-Writer 프로젝트: `{project_dir}`
- 입력 파일: `{source_path}`
- 모드: `{config.auto_writer_mode}`
- 채널: `{config.auto_writer_channel}`
- CMS 기사검토 상태: `{config.cms_review_status}`

```bash
cd {project_dir}
{command}
```

## 안전 기준

- moneynlaw 저장 상태는 `{config.cms_review_status}`로 둡니다.
- 공개 발행, 승인 완료, 예약 발행, 기존 공개 기사 수정, 삭제는 하지 않습니다.
- 금감원 징계해설 기사 이미지에는 `auto_writer_source.md`의 전용 이미지 프롬프트를 사용합니다.
- 저장 결과의 작업 폴더, CMS 상태, 기사 URL/ID가 확인되면 `{AUTO_WRITER_STATE_FILE}`에 기록합니다.
"""
    task_path = job_dir / AUTO_WRITER_TASK_FILE
    task_path.write_text(task, encoding="utf-8")

    state = {
        "version": STATUS_VERSION,
        "stage": "ready_for_auto_writer" if ready else "blocked",
        "updated_at": now_iso(),
        "job_dir": str(job_dir),
        "item_key": item.get("key", ""),
        "item": item,
        "safe_to_save_for_review": ready,
        "cms_review_status": config.cms_review_status,
        "auto_writer": {
            "project_dir": str(project_dir),
            "mode": config.auto_writer_mode,
            "channel": config.auto_writer_channel,
            "source_path": str(source_path),
            "command": command,
        },
        "image_prompt": FSS_CARTOON_IMAGE_PROMPT,
        "blockers": blockers,
        "extraction_errors": extraction_errors,
        "outputs": {
            "auto_writer_job_dir": "",
            "cms_article_url": "",
            "cms_article_id": "",
            "cms_status": "",
        },
        "history": [
            {
                "at": now_iso(),
                "event": "auto_writer_task_created",
                "ready": ready,
            }
        ],
    }
    state_path = job_dir / AUTO_WRITER_STATE_FILE
    write_json(state_path, state)
    return {
        "ready": ready,
        "task_path": str(task_path),
        "state_path": str(state_path),
        "source_path": str(source_path),
        "command": command,
        "blockers": blockers,
    }


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
            "cms_login_url": config.cms_login_url,
            "cms_write_url": config.cms_write_url,
            "cms_review_status": config.cms_review_status,
            "max_auto_writer_input_chars": config.max_auto_writer_input_chars,
            "auto_writer_project_dir": config.auto_writer_project_dir,
            "auto_writer_mode": config.auto_writer_mode,
            "auto_writer_channel": config.auto_writer_channel,
        },
    }
    write_json(job_dir / "metadata.json", metadata)

    pdf_paths = download_job_pdfs(item, job_dir)
    extracted_text, extraction_errors = extract_all_pdf_text(pdf_paths)
    if extracted_text:
        (job_dir / "pdf_text.txt").write_text(extracted_text, encoding="utf-8")
    else:
        extraction_errors.append("추출된 PDF 텍스트가 없습니다. PDF 업로드 방식 또는 수동 확인이 필요합니다.")

    auto_writer_source = write_auto_writer_source(job_dir, item, pdf_paths, extracted_text, config)
    auto_writer = write_auto_writer_task(job_dir, item, config, extraction_errors)
    write_handoff(job_dir, item, pdf_paths, config, extraction_errors)

    status = {
        "version": STATUS_VERSION,
        "status": "auto_writer_ready" if pdf_paths and extracted_text and auto_writer["ready"] else "manual_required",
        "updated_at": now_iso(),
        "item_key": item["key"],
        "job_dir": str(job_dir),
        "pdfs": [str(path) for path in pdf_paths],
        "auto_writer_source": auto_writer_source,
        "auto_writer": auto_writer,
        "requires": {
            "auto_writer_project_dir": not resolve_path(config.auto_writer_project_dir).exists(),
            "human_publish_approval": not is_safe_cms_review_status(config.cms_review_status),
            "auto_writer": True,
        },
        "cms_review_status": config.cms_review_status,
        "errors": extraction_errors,
        "next_files": [
            "handoff.md",
            AUTO_WRITER_SOURCE_FILE,
            AUTO_WRITER_TASK_FILE,
            AUTO_WRITER_STATE_FILE,
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
    parser.add_argument("--item-url", default="", help="Telegram 알림 등에서 복사한 금감원 공시 상세 URL")
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
