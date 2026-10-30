"""全量来源适配仅做范围检查，不需要模型或项目完整数据。"""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("pool_scope", Path(__file__).parents[1] / "scripts/prepare_pool.py")
pool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pool)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.result = {"directions": [
            {"direction_id": "A", "decision": "high_potential"},
            {"direction_id": "B", "decision": "high_potential"},
            {"direction_id": "C", "decision": "insufficient"}]}
        self.selection = {"selected_direction_ids": ["A", "B"], "result_sha256": "actual"}
        self.articles = {"result_sha256": "actual"}

    def test_all_and_only_high_potential(self):
        self.assertEqual(pool.resolve_direction_scope(self.selection, self.articles, self.result, "actual"), {"A", "B"})

    def test_partial_and_extra_selection_rejected(self):
        for ids in (["A"], ["A", "B", "C"]):
            with self.assertRaises(ValueError):
                pool.resolve_direction_scope({**self.selection, "selected_direction_ids": ids}, self.articles, self.result, "actual")

    def test_wrong_result_and_missing_mapping_rejected(self):
        with self.assertRaises(ValueError):
            pool.resolve_direction_scope(self.selection, self.articles, self.result, "changed")
        with self.assertRaises(ValueError):
            pool.resolve_direction_scope(self.selection, self.articles, {"directions": [{"direction_id": "A", "relation_basis": "direct"}]}, "actual")

    def test_legacy_explicit_scope_preserved(self):
        self.assertEqual(pool.resolve_direction_scope({"selection": [{"direction_id": "X"}]}, {}, None, None), {"X"})


if __name__ == "__main__":
    unittest.main()
