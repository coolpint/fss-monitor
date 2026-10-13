import copy
import unittest

from prepare_backlog import prepare_payload


class PrepareBacklogTest(unittest.TestCase):
    def test_only_latest_five_remain_pending_and_skips_are_distinct(self):
        state = {"seen_keys": ["old"], "seen_items": {"old": {"status": "notified"}}, "latest_notice_date": "2026.01.01"}
        original = copy.deepcopy(state)
        items = [{"key": str(i), "date": f"2026.10.{i:02d}", "title": str(i)} for i in range(1, 8)]
        prepared, audit = prepare_payload(state, items, "2026-10-13T00:00:00Z")
        self.assertEqual([item["key"] for item in audit["kept_pending"]], ["7", "6", "5", "4", "3"])
        self.assertEqual(prepared["seen_keys"], ["1", "2", "old"])
        self.assertEqual(prepared["seen_items"]["1"]["status"], "skipped_by_user")
        self.assertEqual(state, original)
        self.assertFalse(audit["applied"])
        self.assertFalse(audit["slack_actions_connection_verified"])
        self.assertEqual(prepared["latest_notice_date"], original["latest_notice_date"])

    def test_tied_dates_keep_original_collected_order(self):
        items = [{"key": key, "date": "2026.10.01"} for key in ("b", "a", "d", "c", "f", "e")]
        _, audit = prepare_payload({"seen_keys": []}, items, "now")
        self.assertEqual([item["key"] for item in audit["kept_pending"]], ["b", "a", "d", "c", "f"])
