"""
금감원 징계공시 모니터 주간 상태 점검

하는 일:
  1. 최근 7일간 GitHub Actions monitor.yml 실행 이력을 확인
  2. 스케줄 실행 누락/실패 여부를 점검
  3. 결과를 Slack으로 전송
     - 정상이어도 "정상 작동 중" 메시지를 보냄
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from slack_notifications import TARGET_SLACK_CHANNEL_ID, send_slack_message


UTC = timezone.utc
KST = timezone(timedelta(hours=9))
GITHUB_API_BASE = "https://api.github.com"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MONITOR_WORKFLOW = "monitor.yml"
DEFAULT_MONITOR_UTC_SLOTS = ",".join(f"{hour:02d}:00" for hour in range(24))
DEFAULT_WINDOW_ANCHOR_UTC = "FRI@06:45"
WEEKDAY_NAMES = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 30)
    last_error = None

    for attempt in range(3):
        try:
            return requests.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                continue

    raise RuntimeError("HTTP 요청 실패 (연결 오류)") from None


def configured_schedule_slots(workflow_file):
    """현재 저장소의 매시간/매일 cron에서 점검 슬롯을 얻는다."""
    source = (Path(__file__).parent / ".github" / "workflows" / workflow_file).read_text(encoding="utf-8")
    crons = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", source)
    slots = set()
    for cron in crons:
        minute, hour, day, month, weekday = cron.split()
        if (day, month, weekday) != ("*", "*", "*") or not minute.isdigit():
            raise ValueError("지원하지 않는 cron: --schedule-slots-utc로 점검 슬롯을 명시하세요.")
        hours = range(24) if hour == "*" else [int(value) for value in hour.split(",")]
        for value in hours:
            if not 0 <= value < 24 or not 0 <= int(minute) < 60:
                raise ValueError("잘못된 cron 시간")
            slots.add(f"{value:02d}:{int(minute):02d}")
    if not slots:
        raise ValueError("점검할 workflow schedule이 없습니다.")
    return ",".join(sorted(slots))


def fetch_workflow_state(repository, workflow_file, github_token):
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    response = request_with_retry("GET", f"{GITHUB_API_BASE}/repos/{repository}/actions/workflows/{workflow_file}", headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"workflow 상태 조회 실패: HTTP {response.status_code}")
    return response.json().get("state", "unknown")


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def format_kst(value: datetime) -> str:
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def parse_slots_utc(raw: str) -> list[tuple[int, int]]:
    slots = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hour_str, minute_str = part.split(":")
        slots.append((int(hour_str), int(minute_str)))
    return sorted(set(slots))


def parse_window_anchor_utc(raw: str) -> tuple[int, int, int] | None:
    raw = raw.strip()
    if not raw:
        return None

    weekday_raw, time_raw = raw.split("@", 1)
    weekday_key = weekday_raw.strip().upper()
    if weekday_key.isdigit():
        weekday = int(weekday_key)
    else:
        weekday = WEEKDAY_NAMES[weekday_key]

    if weekday < 0 or weekday > 6:
        raise ValueError(f"잘못된 weekday 값입니다: {weekday}")

    hour_str, minute_str = time_raw.split(":")
    return weekday, int(hour_str), int(minute_str)


def resolve_window_end(now_utc: datetime, anchor_raw: str) -> datetime:
    anchor = parse_window_anchor_utc(anchor_raw)
    if anchor is None:
        return now_utc

    weekday, hour, minute = anchor
    days_back = (now_utc.weekday() - weekday) % 7
    anchor_date = now_utc.date() - timedelta(days=days_back)
    window_end = datetime(
        anchor_date.year,
        anchor_date.month,
        anchor_date.day,
        hour,
        minute,
        tzinfo=UTC,
    )
    if window_end > now_utc:
        window_end -= timedelta(days=7)

    return window_end


def count_expected_runs(window_start: datetime, window_end: datetime, slots_utc: list[tuple[int, int]]) -> int:
    count = 0
    current_day = window_start.date()
    end_day = window_end.date()

    while current_day <= end_day:
        for hour, minute in slots_utc:
            slot = datetime(
                current_day.year,
                current_day.month,
                current_day.day,
                hour,
                minute,
                tzinfo=UTC,
            )
            if window_start < slot <= window_end:
                count += 1
        current_day += timedelta(days=1)

    return count


@dataclass
class WeeklyHealthSummary:
    healthy: bool
    repository: str
    window_start: datetime
    window_end: datetime
    expected_runs: int
    actual_runs: int
    successful_runs: int
    failed_runs: int
    other_runs: int
    last_success_at: datetime | None
    detail_lines: list[str]
    actions_url: str
    workflow_state: str = "unknown"
    last_collection_success_at: str | None = None
    last_notification_success_at: str | None = None


def fetch_workflow_runs(
    repository: str,
    workflow_file: str,
    branch: str,
    github_token: str,
) -> list[dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    all_runs: list[dict] = []
    page = 1

    while True:
        url = (
            f"{GITHUB_API_BASE}/repos/{repository}/actions/workflows/{workflow_file}/runs"
            f"?per_page=100&page={page}&branch={branch}"
        )
        resp = request_with_retry("GET", url, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"GitHub Actions 조회 실패: HTTP {resp.status_code}"
            )

        payload = resp.json()
        workflow_runs = payload.get("workflow_runs", [])
        all_runs.extend(workflow_runs)

        if len(workflow_runs) < 100:
            break
        page += 1

    return all_runs


def build_summary(
    repository: str,
    workflow_file: str,
    branch: str,
    lookback_days: int,
    slots_utc_raw: str,
    window_anchor_utc_raw: str,
    github_token: str,
) -> WeeklyHealthSummary:
    now_utc = datetime.now(UTC)
    window_end = resolve_window_end(now_utc, window_anchor_utc_raw)
    window_start = window_end - timedelta(days=lookback_days)
    slots_utc = parse_slots_utc(slots_utc_raw or configured_schedule_slots(workflow_file))
    expected_runs = count_expected_runs(window_start, window_end, slots_utc)

    workflow_runs = fetch_workflow_runs(repository, workflow_file, branch, github_token)
    scheduled_runs = []

    for run in workflow_runs:
        if run.get("event") != "schedule":
            continue
        created_at = parse_iso_datetime(run["created_at"])
        if created_at < window_start or created_at > window_end:
            continue
        scheduled_runs.append(run)

    successful_runs = []
    failed_runs = []
    other_runs = []

    for run in scheduled_runs:
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status == "completed" and conclusion == "success":
            successful_runs.append(run)
        elif status == "completed":
            failed_runs.append(run)
        else:
            other_runs.append(run)

    last_success_at = None
    if successful_runs:
        last_success_at = max(parse_iso_datetime(run["created_at"]) for run in successful_runs)

    blocking_other_runs = []
    for run in other_runs:
        created_at = parse_iso_datetime(run["created_at"])
        if last_success_at and created_at < last_success_at:
            continue
        blocking_other_runs.append(run)

    detail_lines = []
    workflow_state = fetch_workflow_state(repository, workflow_file, github_token)
    if workflow_state != "active":
        detail_lines.append(f"워크플로 상태: {workflow_state}")

    health_path = Path(__file__).parent / "monitor_health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    last_collection = health.get("last_collection_success_at")
    last_notification = health.get("last_notification_success_at")
    if not last_collection:
        detail_lines.append("실제 수집 성공 기록이 없습니다 (이전 실행의 성공 배지는 수집/전송 성공 증거가 아닙니다).")
    elif now_utc - parse_iso_datetime(last_collection) > timedelta(hours=3):
        detail_lines.append("실제 수집 성공 시각이 3시간 이상 지났습니다.")
    if health.get("outcome") not in ("success", "baseline"):
        detail_lines.append(f"최근 모니터 결과: {health.get('outcome', 'unknown')}")
    if health.get("failed", 0):
        detail_lines.append(f"최근 알림 실패: {health['failed']}건")

    if not scheduled_runs:
        detail_lines.append("최근 1주간 scheduled 실행 이력이 없습니다.")

    missing_runs = max(0, expected_runs - len(scheduled_runs))
    if missing_runs:
        detail_lines.append(
            f"예상 scheduled 실행 {expected_runs}회 중 {len(scheduled_runs)}회만 확인되었습니다."
        )

    if failed_runs:
        detail_lines.append(f"실패/중단된 scheduled 실행이 {len(failed_runs)}회 있습니다.")
        for run in failed_runs[:3]:
            run_time = format_kst(parse_iso_datetime(run["created_at"]))
            detail_lines.append(
                f"- {run_time} / conclusion={run.get('conclusion', '-')}"
            )

    if blocking_other_runs:
        detail_lines.append(f"완료되지 않은 scheduled 실행이 {len(blocking_other_runs)}회 있습니다.")

    healthy = not detail_lines
    actions_url = f"https://github.com/{repository}/actions/workflows/{workflow_file}"

    return WeeklyHealthSummary(
        healthy=healthy,
        repository=repository,
        window_start=window_start,
        window_end=window_end,
        expected_runs=expected_runs,
        actual_runs=len(scheduled_runs),
        successful_runs=len(successful_runs),
        failed_runs=len(failed_runs),
        other_runs=len(blocking_other_runs),
        last_success_at=last_success_at,
        detail_lines=detail_lines,
        actions_url=actions_url,
        workflow_state=workflow_state,
        last_collection_success_at=last_collection,
        last_notification_success_at=last_notification,
    )


def format_weekly_summary_text(summary: WeeklyHealthSummary) -> str:
    status_text = "정상 작동 중" if summary.healthy else "점검 필요"
    if summary.healthy and not summary.last_notification_success_at:
        status_text += " (수집 기준; 실제 알림 성공 이력 확인 불가)"
    lines = [
        "금감원 징계공시 모니터 주간 점검",
        f"상태: {status_text}",
        f"점검 기간: {format_kst(summary.window_start)} ~ {format_kst(summary.window_end)}",
        f"예상 실행: {summary.expected_runs}",
        f"확인된 실행: {summary.actual_runs}",
        f"성공: {summary.successful_runs}",
        f"실패: {summary.failed_runs}",
        f"기타: {summary.other_runs}",
        f"마지막 성공 실행: {format_kst(summary.last_success_at) if summary.last_success_at else '-'}",
        f"워크플로 상태: {summary.workflow_state}",
        f"실제 마지막 수집 성공(UTC): {summary.last_collection_success_at or '확인 불가'}",
        f"실제 마지막 알림 성공(UTC): {summary.last_notification_success_at or '확인 불가'}",
    ]
    if summary.detail_lines:
        lines.append("")
        lines.extend(summary.detail_lines)
    else:
        lines.append("")
        lines.append("최근 1주 scheduled 실행 점검 결과, 실패나 누락 없이 정상적으로 작동했습니다.")
    lines.append("")
    lines.append(f"GitHub Actions: {summary.actions_url}")
    return "\n".join(lines)


def send_weekly_summary(summary: WeeklyHealthSummary, webhook_url: str, channel_id: str) -> None:
    if not send_slack_message(format_weekly_summary_text(summary), webhook_url, channel_id):
        raise RuntimeError("Slack 주간 점검 알림 발송 실패")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="금감원 징계공시 모니터 주간 상태 점검")
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--workflow-file", default=DEFAULT_MONITOR_WORKFLOW)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--schedule-slots-utc", default="", help="기본값: 현재 workflow cron에서 추출")
    parser.add_argument(
        "--window-anchor-utc",
        default=DEFAULT_WINDOW_ANCHOR_UTC,
        help="주간 점검 기준 시각(예: FRI@06:45). 비우면 현재 시각 기준",
    )
    parser.add_argument("--print-only", action="store_true", help="Slack 전송 없이 결과만 출력")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    github_token = os.getenv("GITHUB_TOKEN", "")
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    slack_channel_id = os.getenv("SLACK_CHANNEL_ID", TARGET_SLACK_CHANNEL_ID)

    if not args.repository:
        raise RuntimeError("GITHUB_REPOSITORY 또는 --repository가 필요합니다.")

    summary = build_summary(
        repository=args.repository,
        workflow_file=args.workflow_file,
        branch=args.branch,
        lookback_days=args.lookback_days,
        slots_utc_raw=args.schedule_slots_utc,
        window_anchor_utc_raw=args.window_anchor_utc,
        github_token=github_token,
    )

    print(json.dumps({
        "healthy": summary.healthy,
        "repository": summary.repository,
        "window_start": summary.window_start.isoformat(),
        "window_end": summary.window_end.isoformat(),
        "expected_runs": summary.expected_runs,
        "actual_runs": summary.actual_runs,
        "successful_runs": summary.successful_runs,
        "failed_runs": summary.failed_runs,
        "other_runs": summary.other_runs,
        "last_success_at": summary.last_success_at.isoformat() if summary.last_success_at else None,
        "detail_lines": summary.detail_lines,
        "actions_url": summary.actions_url,
        "workflow_state": summary.workflow_state,
        "last_collection_success_at": summary.last_collection_success_at,
        "last_notification_success_at": summary.last_notification_success_at,
    }, ensure_ascii=False, indent=2))

    if not args.print_only:
        send_weekly_summary(summary, slack_webhook_url, slack_channel_id)
    if not summary.healthy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
