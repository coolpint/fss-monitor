import unittest
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import weekly_health_check


class WeeklyHealthTelegramTest(unittest.TestCase):
    def test_current_hourly_cron_expects_168_runs(self):
        slots = weekly_health_check.parse_slots_utc(weekly_health_check.configured_schedule_slots("monitor.yml"))
        start = datetime(2026, 8, 21, 6, 45, tzinfo=timezone.utc)
        self.assertEqual(weekly_health_check.count_expected_runs(start, start + timedelta(days=7), slots), 168)
        boundary = start.replace(minute=0)
        self.assertEqual(weekly_health_check.count_expected_runs(boundary, boundary + timedelta(days=7), slots), 168)

    def test_disabled_workflow_and_unproven_success_are_unhealthy(self):
        with (patch.object(weekly_health_check, "fetch_workflow_runs", return_value=[]),
              patch.object(weekly_health_check, "fetch_workflow_state", return_value="disabled_inactivity"),
              patch.object(Path, "exists", return_value=False)):
            summary = weekly_health_check.build_summary("owner/repo", "monitor.yml", "main", 7, weekly_health_check.DEFAULT_MONITOR_UTC_SLOTS, "", "")
        self.assertFalse(summary.healthy)
        self.assertEqual(summary.expected_runs, 168)
        self.assertEqual(summary.workflow_state, "disabled_inactivity")
        self.assertIsNone(summary.last_collection_success_at)

    def test_recent_collection_with_failed_delivery_is_unhealthy(self):
        now = datetime.now(timezone.utc)
        health = {"outcome": "notification_failed", "failed": 80,
                  "last_collection_success_at": now.isoformat()}
        with (patch.object(weekly_health_check, "fetch_workflow_runs", return_value=[]),
              patch.object(weekly_health_check, "fetch_workflow_state", return_value="active"),
              patch.object(Path, "exists", return_value=True),
              patch.object(Path, "read_text", return_value=json.dumps(health))):
            summary = weekly_health_check.build_summary("owner/repo", "monitor.yml", "main", 7, weekly_health_check.DEFAULT_MONITOR_UTC_SLOTS, "", "")
        self.assertFalse(summary.healthy)
        self.assertTrue(any("80" in line for line in summary.detail_lines))

    def test_healthy_hourly_runs_with_current_collection(self):
        now = datetime.now(timezone.utc)
        runs = [{"event": "schedule", "created_at": (now - timedelta(hours=i)).isoformat(),
                 "status": "completed", "conclusion": "success"} for i in range(168)]
        health = {"outcome": "success", "failed": 0, "last_collection_success_at": now.isoformat()}
        with (patch.object(weekly_health_check, "fetch_workflow_runs", return_value=runs),
              patch.object(weekly_health_check, "fetch_workflow_state", return_value="active"),
              patch.object(Path, "exists", return_value=True),
              patch.object(Path, "read_text", return_value=json.dumps(health))):
            summary = weekly_health_check.build_summary("owner/repo", "monitor.yml", "main", 7, weekly_health_check.DEFAULT_MONITOR_UTC_SLOTS, "", "")
        self.assertTrue(summary.healthy)
        self.assertEqual(summary.actual_runs, 168)
        self.assertIsNone(summary.last_notification_success_at)

    def test_weekly_summary_is_sent_only_to_slack(self):
        from unittest.mock import Mock
        summary = Mock(healthy=False)
        with patch.object(weekly_health_check, "format_weekly_summary_text", return_value="summary"), patch.object(weekly_health_check, "send_slack_message", return_value=True) as send:
            weekly_health_check.send_weekly_summary(summary, "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "C0C9LQN7A64")
        send.assert_called_once_with("summary", "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "C0C9LQN7A64")

    def test_weekly_send_failure_is_not_silenced(self):
        from unittest.mock import Mock
        with patch.object(weekly_health_check, "format_weekly_summary_text", return_value="summary"), patch.object(weekly_health_check, "send_slack_message", return_value=False):
            with self.assertRaises(RuntimeError):
                weekly_health_check.send_weekly_summary(Mock(), "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "C0C9LQN7A64")


if __name__ == "__main__":
    unittest.main()
