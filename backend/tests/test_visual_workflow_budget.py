"""视觉累计额度的离线边界测试，不使用供应商或假造视觉判定。"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.services.visual_workflow.budget import BudgetExceeded, budget_snapshot, reserve_visual_call


def image(sha, role="original", cid="H001-one"):
    return {"sha256": sha, "role": role, "candidate_id": cid}


class VisualBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.run = Path(self.temp.name)
        self.policy = {"limits": {"unique_originals": 2, "view_candidates": 2,
                                  "board_reviews": 2, "visual_requests": 20, "image_attachments": 20},
                       "history_run_paths": []}
        self.save_policy()

    def tearDown(self):
        self.temp.cleanup()

    def save_policy(self):
        (self.run / "visual-budget-policy.json").write_text(json.dumps(self.policy))

    def actual(self, root, call_id, images, *, receipt=None):
        folder = root / "calls" / call_id
        folder.mkdir(parents=True)
        request = {"call_id": call_id, "input_fingerprint": "fp", "started_at": "same", "images": images}
        (folder / "request.json").write_text(json.dumps(request))
        if receipt:
            (folder / "receipt.json").write_text(json.dumps(receipt))

    def reserve(self, call_id, images):
        return reserve_visual_call(self.run, call_id, {"direction_id": "H001"}, images, fingerprint="fp")

    def test_history_failures_unknown_and_reused_requests_are_counted_once(self):
        old = self.run / "history"
        old.mkdir()
        self.policy["history_run_paths"] = [str(old)]
        self.save_policy()
        original = [image("a")]
        self.actual(old, "target-H001-old", original, receipt={"status": "failed_no_retry"})
        self.actual(self.run, "target-H001-old", original, receipt={"status": "failed_no_retry"})
        row = budget_snapshot(self.run)["directions"]["H001"]
        self.assertEqual((row["unique_originals"], row["visual_requests"], row["tokens"]["unknown_calls"]), (1, 1, 1))

    def test_simultaneous_reservations_cannot_exceed_unique_limit(self):
        def attempt(n):
            try:
                self.reserve(f"target-H001-{n}", [image(str(n))])
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=5) as pool:
            outcomes = list(pool.map(attempt, range(5)))
        self.assertEqual(sum(outcomes), 2)
        self.assertEqual(budget_snapshot(self.run)["directions"]["H001"]["unique_originals"], 2)

    def test_repeat_originals_charge_requests_and_attachments(self):
        self.policy["limits"]["image_attachments"] = 2
        self.save_policy()
        self.reserve("target-H001-one", [image("a")])
        self.reserve("quality-H001-one", [image("a")])
        with self.assertRaises(BudgetExceeded):
            self.reserve("view-H001-one", [image("a")])
        row = budget_snapshot(self.run)["directions"]["H001"]
        self.assertEqual((row["unique_originals"], row["visual_requests"], row["image_attachments"]), (1, 2, 2))

    def test_actual_request_replaces_reservation_without_double_count(self):
        self.reserve("target-H001-one", [image("a")])
        self.actual(self.run, "target-H001-one", [image("a")], receipt={"status": "completed", "usage": {
            "input_tokens": 5, "output_tokens": 3, "usage_complete": True}})
        row = budget_snapshot(self.run)["directions"]["H001"]
        self.assertEqual((row["visual_requests"], row["reserved_requests"]), (1, 0))
        self.assertEqual(row["tokens"], {"input": 5, "output": 3, "unknown_calls": 0})

    def test_board_cap_includes_prior_actual_reviews(self):
        board = [image("board", "actual_rendered_board", None)]
        self.actual(self.run, "board-H001-old", board)
        self.reserve("board-H001-new", board)
        with self.assertRaises(BudgetExceeded):
            self.reserve("board-H001-third", board)

    def test_views_are_counted_by_bound_candidate_not_crop_hash(self):
        self.policy["limits"]["view_candidates"] = 1
        self.save_policy()
        self.reserve("view-H001-one", [image("v1", "actual_view")])
        self.reserve("view-H001-revised", [image("v2", "actual_view")])
        with self.assertRaises(BudgetExceeded):
            self.reserve("view-H001-two", [image("v3", "actual_view", "H001-two")])

    def test_unknown_direction_or_contact_sheet_cannot_bypass_accounting(self):
        with self.assertRaises(ValueError):
            reserve_visual_call(self.run, "undirected", {}, [image("a", cid=None)])
        with self.assertRaises(ValueError):
            self.reserve("target-H001-sheet", [image("sheet", "contact_sheet")])

    def test_unavailable_history_is_not_zero_usage(self):
        self.policy["history_run_paths"] = [str(self.run / "missing")]
        self.save_policy()
        with self.assertRaises(ValueError):
            budget_snapshot(self.run)

    def test_same_request_reservation_is_idempotent_and_input_change_rejected(self):
        self.reserve("target-H001-one", [image("a")])
        self.reserve("target-H001-one", [image("a")])
        self.assertEqual(budget_snapshot(self.run)["directions"]["H001"]["visual_requests"], 1)
        with self.assertRaises(ValueError):
            self.reserve("target-H001-one", [image("b")])

    def test_prior_overage_only_blocks_additional_consumption_of_that_metric(self):
        board = [image("board", "actual_rendered_board", None)]
        for n in range(3):
            self.actual(self.run, f"board-H001-old{n}", board)
        self.reserve("view-H001-one", [image("v1", "actual_view")])
        with self.assertRaises(BudgetExceeded):
            self.reserve("board-H001-new", board)

    def test_failed_request_without_provider_usage_is_unknown(self):
        self.actual(self.run, "target-H001-old", [image("a")], receipt={"status": "failed_no_retry", "usage": {
            "input_tokens": 0, "output_tokens": 0, "usage_complete": True,
            "llm_request_count": 1, "requests_with_usage": 0}})
        self.assertEqual(budget_snapshot(self.run)["directions"]["H001"]["tokens"]["unknown_calls"], 1)

    def test_history_same_call_name_does_not_hide_new_reservation(self):
        old = self.run / "history"
        old.mkdir()
        self.policy["history_run_paths"] = [str(old)]
        self.save_policy()
        self.actual(old, "target-H001-same", [image("a")])
        reserve_visual_call(self.run, "target-H001-same", {"direction_id": "H001"}, [image("b")], fingerprint="new")
        with self.assertRaises(BudgetExceeded):
            self.reserve("target-H001-third", [image("c")])
        self.assertEqual(budget_snapshot(self.run)["directions"]["H001"]["unique_originals"], 2)

    def test_payload_direction_remains_resolvable_after_request_is_saved(self):
        images = [image("board", "actual_rendered_board", None)]
        saved = self.reserve("board-review", images)
        self.actual(self.run, "board-review", images)
        path = self.run / "calls/board-review/request.json"
        request = json.loads(path.read_text())
        request["visual_budget_reservation"] = saved
        path.write_text(json.dumps(request))
        self.assertEqual(budget_snapshot(self.run)["directions"]["H001"]["visual_requests"], 1)


if __name__ == "__main__":
    unittest.main()
