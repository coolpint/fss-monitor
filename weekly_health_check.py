"""
금감원 징계공시 모니터 주간 상태 점검

하는 일:
  1. 최근 7일간 GitHub Actions monitor.yml 실행 이력을 확인
  2. 스케줄 실행 누락/실패 여부를 점검
  3. 결과를 Teams Webhook으로 전송
     - 정상이어도 "정상 작동 중" 메시지를 보냄
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import requests


KST = timezone(timedelta(hours=9))
GITHUB_API_BASE = "https://api.github.com"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MONITOR_WORKFLOW = "monitor.yml"
DEFAULT_MONITOR_UTC_SLOTS = "17:00"
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

    raise RuntimeError(f"HTTP 요청 실패: {last_error}")


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
            if window_start <= slot <= window_end:
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
                f"GitHub Actions 조회 실패: HTTP {resp.status_code} {resp.text[:300]}"
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
    slots_utc = parse_slots_utc(slots_utc_raw)
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

    detail_lines = []

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

    if other_runs:
        detail_lines.append(f"완료되지 않은 scheduled 실행이 {len(other_runs)}회 있습니다.")

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
        other_runs=len(other_runs),
        last_success_at=last_success_at,
        detail_lines=detail_lines,
        actions_url=actions_url,
    )


def send_teams_weekly_summary(summary: WeeklyHealthSummary, webhook_url: str) -> None:
    if not webhook_url:
        raise RuntimeError("TEAMS_WEBHOOK_URL이 설정되지 않았습니다.")

    title = "금감원 징계공시 모니터 주간 점검"
    status_text = "정상 작동 중" if summary.healthy else "점검 필요"
    theme_color = "2E8B57" if summary.healthy else "C0392B"

    facts = [
        {"name": "점검 기간", "value": f"{format_kst(summary.window_start)} ~ {format_kst(summary.window_end)}"},
        {"name": "예상 실행", "value": str(summary.expected_runs)},
        {"name": "확인된 실행", "value": str(summary.actual_runs)},
        {"name": "성공", "value": str(summary.successful_runs)},
        {"name": "실패", "value": str(summary.failed_runs)},
        {"name": "기타", "value": str(summary.other_runs)},
        {
            "name": "마지막 성공 실행",
            "value": format_kst(summary.last_success_at) if summary.last_success_at else "-",
        },
    ]

    body_lines = [f"상태: **{status_text}**"]
    if summary.detail_lines:
        body_lines.append("")
        body_lines.extend(summary.detail_lines)
    else:
        body_lines.append("")
        body_lines.append("최근 1주 scheduled 실행 점검 결과, 실패나 누락 없이 정상적으로 작동했습니다.")

    message = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": theme_color,
        "summary": f"금감원 징계공시 모니터 주간 점검: {status_text}",
        "sections": [{
            "activityTitle": title,
            "text": "\n".join(body_lines),
            "facts": facts,
            "markdown": True,
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "GitHub Actions 보기",
            "targets": [{"os": "default", "uri": summary.actions_url}],
        }],
    }

    resp = request_with_retry(
        "POST",
        webhook_url,
        json=message,
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Teams 전송 실패: HTTP {resp.status_code} {resp.text[:300]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="금감원 징계공시 모니터 주간 상태 점검")
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--workflow-file", default=DEFAULT_MONITOR_WORKFLOW)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--schedule-slots-utc", default=DEFAULT_MONITOR_UTC_SLOTS)
    parser.add_argument(
        "--window-anchor-utc",
        default=DEFAULT_WINDOW_ANCHOR_UTC,
        help="주간 점검 기준 시각(예: FRI@06:45). 비우면 현재 시각 기준",
    )
    parser.add_argument("--print-only", action="store_true", help="Teams 전송 없이 결과만 출력")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    github_token = os.getenv("GITHUB_TOKEN", "")
    teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")

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
    }, ensure_ascii=False, indent=2))

    if not args.print_only:
        send_teams_weekly_summary(summary, teams_webhook_url)


if __name__ == "__main__":
    main()
