"""Slack 검증 후 적용할 후보 상태를 준비한다. 실제 seen 변경/알림 발송은 없다."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import monitor


def prepare_payload(state: dict, items: list[dict], prepared_at: str):
    seen = set(state["seen_keys"])
    # 원문에 게시 시간이 없어 공시일만 비교한다. 동률은 수집 목록 순서,
    # 그 다음 공시 식별자로 정렬한다. 날짜가 없는 항목은 마지막이다.
    candidates = [(index, item) for index, item in enumerate(items) if item["key"] not in seen]
    candidates.sort(key=lambda pair: (-monitor.date_to_int(pair[1].get("date", "")), pair[0], pair[1]["key"]))
    pending = [item for _, item in candidates[:5]]
    skipped = [item for _, item in candidates[5:]]
    proposed = json.loads(json.dumps(state))
    proposed["seen_keys"] = sorted(seen | {item["key"] for item in skipped})
    records = proposed.setdefault("seen_items", {})
    for item in skipped:
        records[item["key"]] = monitor.notice_record(item, "skipped_by_user", prepared_at)
    audit = {
        "prepared_at": prepared_at, "applied": False, "slack_actions_connection_verified": False,
        "original_seen_sha256": None,
        "reason": "사용자 요청: Slack 연결 검증 후 최신 5건만 미전송으로 남기고 나머지 과거 후보 알림 생략",
        "sort": "공시일 내림차순; 동률은 수집 목록 순서, 공시 키; 게시 시각은 원문에 없음",
        "collected": len(items), "candidate_count": len(candidates),
        "kept_pending_count": len(pending), "skipped_count": len(skipped),
        "kept_pending": pending, "skipped": skipped,
        "delivery_performed": False,
        "slack_target_channel_id": monitor.TARGET_SLACK_CHANNEL_ID,
    }
    return proposed, audit


def main():
    original = monitor.SEEN_FILE.read_bytes()
    state = monitor.load_state_payload()
    items = monitor.fetch_list()
    if not items:
        raise RuntimeError("빈 목록: 상태 변경을 준비하지 않습니다.")
    now = datetime.now(timezone.utc)
    proposed, audit = prepare_payload(state, items, now.isoformat())
    audit["original_seen_sha256"] = hashlib.sha256(original).hexdigest()
    directory = Path(__file__).parent / "recovery-preparation" / now.strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    (directory / "seen.original.json").write_bytes(original)
    for name, data in [("seen.prepared.json", proposed), ("audit.json", audit), ("collected.json", items)]:
        (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(directory), "candidate_count": audit["candidate_count"],
                      "skipped_count": audit["skipped_count"], "kept_pending": audit["kept_pending"],
                      "applied": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
