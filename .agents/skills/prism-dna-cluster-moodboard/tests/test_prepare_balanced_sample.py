"""小规模离线抽样验证；不解析图片、不调用模型、不把失败图换出样本。"""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_balanced_sample.py"
SPEC = importlib.util.spec_from_file_location("balanced_sampling", SCRIPT)
sampling = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sampling)


def image(index, article):
    return {"image_id": f"i{index}", "sha256": f"{index:064x}", "local_path": f"/nonexistent/{index}",
            "sources": [{"article_id": article}], "aliases": [{"image_id": f"i{index}", "article_id": article}]}


class BalancedSampleTests(unittest.TestCase):
    def test_round_robin_uses_up_small_articles_and_redistributes(self):
        rows = [image(0, "a"), *[image(i, "b") for i in range(1, 3)], *[image(i, "c") for i in range(3, 8)]]
        result, audit = sampling.balanced_sample(rows, 6, "test")
        self.assertEqual(len(result), 6)
        self.assertEqual({row["article_id"]: row["sampled_images"] for row in audit["article_allocations"]}, {"a": 1, "b": 2, "c": 3})
        self.assertEqual(audit["round_sizes"], [3, 2, 1])

    def test_order_is_reproducible_independent_of_pool_order(self):
        rows = [image(i, str(i % 3)) for i in range(18)]
        first, _ = sampling.balanced_sample(rows, 10, "fixed")
        second, _ = sampling.balanced_sample(list(reversed(rows)), 10, "fixed")
        changed, _ = sampling.balanced_sample(rows, 10, "other")
        self.assertEqual(first, second)
        self.assertNotEqual([row["sha256"] for row in first], [row["sha256"] for row in changed])

    def test_shared_SHA_gets_one_quota_and_keeps_all_aliases(self):
        shared = image(0, "small")
        shared["sources"].append({"article_id": "large"})
        shared["aliases"].append({"image_id": "alias0", "article_id": "large"})
        rows = [shared, *[image(i, "large") for i in range(1, 6)]]
        result, audit = sampling.balanced_sample(rows, 4, "seed")
        adopted = next(row for row in result if row["sha256"] == shared["sha256"])
        self.assertEqual(adopted["sampling_article_id"], "small")
        self.assertEqual(adopted["aliases"], shared["aliases"])
        self.assertEqual(audit["sample_duplicate_shas"], 0)

    def test_DNA_quality_and_category_do_not_change_selected_identity(self):
        rows = [image(i, str(i % 4)) for i in range(24)]
        altered = copy.deepcopy(rows)
        for row in altered:
            row.update(dna_primary_ref=None, visual_quality_status="failed", category="opposite")
        first, _ = sampling.balanced_sample(rows, 12, "seed")
        second, _ = sampling.balanced_sample(altered, 12, "seed")
        self.assertEqual([row["sha256"] for row in first], [row["sha256"] for row in second])

    def test_duplicate_SHA_and_absent_article_are_not_silently_fixed(self):
        with self.assertRaisesRegex(ValueError, "去重"):
            sampling.balanced_sample([image(0, "a"), image(0, "b")], 1, "x")
        row = image(1, "a")
        row["sources"] = row["aliases"] = []
        with self.assertRaisesRegex(ValueError, "缺少原文"):
            sampling.balanced_sample([row], 1, "x")

    def test_missing_original_remains_sample_and_output_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sampling.write_new(root / "pool.json", {"images": [image(0, "a"), image(1, "b")]})
            result = sampling.freeze(root / "pool.json", root / "run", size=2, seed="x", prior_paths=[])
            self.assertEqual(result["sample_count"], 2)
            self.assertEqual(result["original_check_counts"], {"unreadable": 2})
            sample = sampling.read(root / "run/sample.json")
            self.assertFalse(sample["sampling"]["missing_images_replaced"])
            with self.assertRaises(FileExistsError):
                sampling.freeze(root / "pool.json", root / "run", size=2, seed="x", prior_paths=[])

    def test_latest_valid_prior_is_preserved_with_original_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = [image(0, "a"), image(1, "b")]
            unit = {"unit_id": "u0", "image_id": "i0", "image_sha256": selected[0]["sha256"], "features": {"kept": "old"}}
            old = {"images": [{"image_id": "i0", "sha256": selected[0]["sha256"], "status": "observed", "units": [unit]}]}
            failed = {"images": [{"image_id": "i0", "sha256": selected[0]["sha256"], "status": "failed"}], "units": []}
            sampling.write_new(root / "old.json", old)
            sampling.write_new(root / "failed.json", failed)
            result = sampling.old_context(selected, [root / "old.json", root / "failed.json"])
            self.assertEqual(result["units"], [unit])
            self.assertEqual(result["unit_source_bindings"][0]["pointer"], "/images/0/units/0")
            self.assertEqual(result["images"][1]["status"], "not_previously_observed")
            self.assertFalse(result["new_DNA_created"])


if __name__ == "__main__":
    unittest.main()
