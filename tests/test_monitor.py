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
                patch.object(monitor, "send_telegram_link_alert", return_value=True) as send_alert,
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
                patch.object(monitor, "send_telegram_link_alert", return_value=False),
            ):
                processed = monitor.run_once()

            self.assertEqual(processed, 1)
            saved = json.loads(seen_file.read_text(encoding="utf-8"))
            self.assertNotIn("id:new_item", saved["seen_keys"])
            self.assertEqual(saved["latest_notice_date"], "2026.04.20")


if __name__ == "__main__":
    unittest.main()
