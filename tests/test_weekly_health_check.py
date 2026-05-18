import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import weekly_health_check


class WeeklyHealthTelegramTest(unittest.TestCase):
    def test_weekly_summary_is_sent_to_telegram(self):
        summary = weekly_health_check.WeeklyHealthSummary(
            healthy=True,
            repository="owner/repo",
            window_start=datetime(2026, 5, 8, 6, 45, tzinfo=timezone.utc),
            window_end=datetime(2026, 5, 15, 6, 45, tzinfo=timezone.utc),
            expected_runs=7,
            actual_runs=7,
            successful_runs=7,
            failed_runs=0,
            other_runs=0,
            last_success_at=datetime(2026, 5, 15, 1, 0, tzinfo=timezone.utc),
            detail_lines=[],
            actions_url="https://github.com/owner/repo/actions/workflows/monitor.yml",
        )

        class Response:
            status_code = 200
            text = "ok"

        with patch.object(weekly_health_check, "request_with_retry", return_value=Response()) as request:
            weekly_health_check.send_telegram_weekly_summary(summary, "token", "44370045")

        request.assert_called_once()
        _, url = request.call_args.args[:2]
        self.assertIn("api.telegram.org/bottoken/sendMessage", url)
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "44370045")
        self.assertIn("정상 작동 중", payload["text"])
        self.assertIn("예상 실행: 7", payload["text"])


if __name__ == "__main__":
    unittest.main()
