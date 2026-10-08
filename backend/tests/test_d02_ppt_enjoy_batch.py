"""PPT ENJOY 批次的冻结范围与同原图复用规则。"""

import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_d02_ppt_enjoy_batch.py"
spec = importlib.util.spec_from_file_location("run_d02_ppt_enjoy_batch", SCRIPT)
assert spec is not None and spec.loader is not None
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class D02PptEnjoyBatchTestCase(TestCase):
    def test_scope_is_exactly_551_existing_enjoy_images_with_two_hash_reuses(self) -> None:
        entries = batch._research_entries()
        self.assertEqual(len(entries), 551)
        self.assertEqual(len({item["sha256"] for item in entries}), 549)
        self.assertEqual(batch.MAX_WORKERS, 5)
        self.assertTrue(all(item["preferences"] for item in entries))
        self.assertTrue(all(
            pref["emotion_tag"] == "ENJOY"
            for item in entries for pref in item["preferences"]
        ))
        self.assertTrue(all(
            item["source_path"].startswith("ppt_images/")
            and (batch.RESEARCH_ROOT / item["source_path"]).is_file()
            for item in entries
        ))

    def test_batch_result_cannot_be_deleted_outside_frozen_manifest(self) -> None:
        with patch("app.api.dna_v2.read_result", return_value={
            "source": {"research": {"batch_id": batch.BATCH_ID}}
        }):
            response = TestClient(app).delete("/api/v1/dna-v2/results/" + "a" * 32)
        self.assertEqual(response.status_code, 409)
