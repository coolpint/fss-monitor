import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor


def item(item_id, date, title):
    return {
        "id": item_id,
        "key": f"id:{item_id}",
        "title": title,
        "date": date,
        "url": f"https://example.test/{item_id}",
    }


class MonitorRunOnceTest(unittest.TestCase):
    def test_alert_only_sends_one_message_without_backlog_or_state(self):
        with (patch("sys.argv", ["monitor.py", "--test-alert-only"]),
              patch.object(monitor, "send_notification_message", return_value=True) as send,
              patch.object(monitor, "fetch_list") as fetch,
              patch.object(monitor, "save_state") as save,
              patch.object(monitor, "write_health") as health):
            monitor.main()
        send.assert_called_once()
        fetch.assert_not_called()
        save.assert_not_called()
        health.assert_not_called()

    def test_fetch_list_scans_multiple_pages(self):
        page_1 = """
        <table><tbody>
          <tr>
            <td>1</td><td>첫번째회사</td><td>2026.05.07</td>
            <td><a href="/fss/job/openInfo/view.do?menuNo=200476&pageIndex=1&examMgmtNo=202600001&emOpenSeq=1">보기</a></td>
          </tr>
        </tbody></table>
        """
        page_2 = """
        <table><tbody>
          <tr>
            <td>2</td><td>두번째회사</td><td>2026.05.06</td>
            <td><a href="/fss/job/openInfo/view.do?menuNo=200476&pageIndex=2&examMgmtNo=202600002&emOpenSeq=1">보기</a></td>
          </tr>
        </tbody></table>
        """

        class Response:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        with patch.object(
            monitor,
            "request_with_retry",
            side_effect=[Response(page_1), Response(page_2)],
        ) as request:
            items = monitor.fetch_list(max_pages=2)

        self.assertEqual([item["key"] for item in items], ["id:202600001_1", "id:202600002_1"])
        self.assertEqual(request.call_count, 2)

    def test_parse_list_page_ignores_non_notice_links(self):
        html = """
        <div>
          <a href="javascript:fn_goApi('bank')">은행 경영통계 API</a>
          <a href="/fss/job/openInfo/view.do?menuNo=200476&examMgmtNo=202600003&emOpenSeq=1">날짜 없는 링크</a>
        </div>
        """

        self.assertEqual(monitor.parse_list_page(html), [])

    def test_notification_uses_only_slack(self):
        with patch.object(monitor, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret"), patch.object(monitor, "SLACK_CHANNEL_ID", "C0C9LQN7A64"), patch.object(monitor, "send_slack_message", return_value=True) as send:
            self.assertTrue(monitor.send_notification_message("공시"))
        send.assert_called_once_with("공시", "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "C0C9LQN7A64")

    def test_unseen_older_date_is_alerted(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen_file = Path(tmp) / "seen.json"
            seen_file.write_text(
                json.dumps(
                    {
                        "seen_keys": ["id:already_seen"],
                        "latest_notice_date": "2026.04.27",
                        "saved_at": "2026-04-30 18:09:59",
                    }
                ),
                encoding="utf-8",
            )
            older_unseen = item("older_unseen", "2026.04.24", "과거 일자 신규 공시")

            with (
                patch.object(monitor, "SEEN_FILE", seen_file),
                patch.object(monitor, "fetch_list", return_value=[older_unseen]),
                patch.object(monitor, "send_slack_link_alert", return_value=True) as send_alert,
            ):
                processed = monitor.run_once()

            self.assertEqual(processed, 1)
            send_alert.assert_called_once_with(older_unseen)
            saved = json.loads(seen_file.read_text(encoding="utf-8"))
            self.assertIn("id:older_unseen", saved["seen_keys"])
            self.assertEqual(saved["seen_items"]["id:older_unseen"]["title"], "과거 일자 신규 공시")
            self.assertEqual(saved["seen_items"]["id:older_unseen"]["status"], "notified")
            self.assertEqual(saved["latest_notice_date"], "2026.04.27")

    def test_failed_delivery_is_not_marked_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen_file = Path(tmp) / "seen.json"
            seen_file.write_text(
                json.dumps(
                    {
                        "seen_keys": [],
                        "latest_notice_date": "2026.04.20",
                        "saved_at": "2026-04-21 02:05:31",
                    }
                ),
                encoding="utf-8",
            )
            new_item = item("new_item", "2026.04.27", "발송 실패 신규 공시")

            with (
                patch.object(monitor, "SEEN_FILE", seen_file),
                patch.object(monitor, "fetch_list", return_value=[new_item]),
                patch.object(monitor, "send_slack_link_alert", return_value=False),
            ):
                with self.assertRaises(monitor.MonitorRunError):
                    monitor.run_once()

            health = json.loads(seen_file.with_name("monitor_health.json").read_text())
            self.assertEqual((health["attempted"], health["succeeded"], health["failed"]), (1, 0, 1))
            self.assertNotIn("last_notification_success_at", health)
            saved = json.loads(seen_file.read_text(encoding="utf-8"))
            self.assertNotIn("id:new_item", saved["seen_keys"])
            self.assertEqual(saved["latest_notice_date"], "2026.04.20")

    def test_partial_success_preserves_successful_state_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "seen.json"
            state.write_text('{"seen_keys": [], "latest_notice_date": ""}')
            with (patch.object(monitor, "SEEN_FILE", state),
                  patch.object(monitor, "fetch_list", return_value=[item("a", "2026.08.21", "a"), item("b", "2026.08.21", "b")]),
                  patch.object(monitor, "send_slack_link_alert", side_effect=[True, RuntimeError("secret-url")])):
                with self.assertRaises(monitor.MonitorRunError):
                    monitor.run_once()
            self.assertEqual(json.loads(state.read_text())["seen_keys"], ["id:a"])
            health = json.loads(state.with_name("monitor_health.json").read_text())
            self.assertEqual((health["succeeded"], health["failed"]), (1, 1))
            self.assertIn("last_notification_success_at", health)
            self.assertNotIn("secret-url", json.dumps(health))

    def test_collection_and_empty_parse_fail_without_touching_seen(self):
        for result in (RuntimeError("secret-url"), []):
            with tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / "seen.json"
                original = '{"seen_keys": ["id:old"]}'
                state.write_text(original)
                fetch = patch.object(monitor, "fetch_list", side_effect=result) if isinstance(result, Exception) else patch.object(monitor, "fetch_list", return_value=result)
                with patch.object(monitor, "SEEN_FILE", state), fetch:
                    with self.assertRaises(monitor.MonitorRunError):
                        monitor.run_once()
                self.assertEqual(state.read_text(), original)

    def test_dry_run_does_not_send_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "seen.json"
            state.write_text('{"seen_keys": []}')
            original = state.read_bytes()
            with (patch.object(monitor, "SEEN_FILE", state),
                  patch.object(monitor, "fetch_list", return_value=[item("a", "2026.08.21", "a")]),
                  patch.object(monitor, "send_slack_link_alert") as send):
                monitor.run_once(dry_run=True)
            send.assert_not_called()
            self.assertEqual(state.read_bytes(), original)
            self.assertFalse(state.with_name("monitor_health.json").exists())

    def test_corrupt_state_blocks_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "seen.json"
            state.write_text('broken')
            with (patch.object(monitor, "SEEN_FILE", state),
                  patch.object(monitor, "fetch_list", return_value=[item("a", "2026.08.21", "a")]),
                  patch.object(monitor, "send_slack_link_alert") as send):
                with self.assertRaises(RuntimeError):
                    monitor.run_once()
            send.assert_not_called()
            self.assertEqual(state.read_text(), 'broken')

    def test_quiet_run_preserves_last_real_notification_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "seen.json"
            state.write_text('{"seen_keys": ["id:a"]}')
            health_path = state.with_name("monitor_health.json")
            health_path.write_text('{"last_notification_success_at": "2026-08-21T11:26:00+00:00"}')
            with (patch.object(monitor, "SEEN_FILE", state),
                  patch.object(monitor, "fetch_list", return_value=[item("a", "2026.08.21", "a")]),
                  patch.object(monitor, "send_slack_link_alert") as send):
                self.assertEqual(monitor.run_once(), 0)
            send.assert_not_called()
            health = json.loads(health_path.read_text())
            self.assertEqual(health["last_notification_success_at"], "2026-08-21T11:26:00+00:00")
            self.assertEqual(health["outcome"], "success")

    def test_cli_exits_nonzero_on_monitor_failure(self):
        with patch("sys.argv", ["monitor.py"]), patch.object(monitor, "run_once", side_effect=monitor.MonitorRunError("failed")):
            with self.assertRaises(SystemExit) as error:
                monitor.main()
            self.assertEqual(error.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
