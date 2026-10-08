"""用研 R5 批次的停止条件必须区分 HTTP 状态和随机追踪 ID。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts import run_d02_ppt_enjoy_r5_batch as batch
from scripts.run_d02_ppt_enjoy_r5_batch import _quota_or_auth_error


class D02PptEnjoyR5BatchTestCase(TestCase):
    def test_trace_id_containing_403_is_not_quota_error(self) -> None:
        self.assertFalse(_quota_or_auth_error(
            "运行记录 d9b80a56577d40379a066d2606c12214：JSONDecodeError"
        ))

    def test_real_quota_and_authorization_errors_stop_new_submissions(self) -> None:
        self.assertTrue(_quota_or_auth_error("Error code: 403 - Quota Exceeded"))
        self.assertTrue(_quota_or_auth_error("HTTP status 403"))
        self.assertTrue(_quota_or_auth_error("invalid API key"))

    def test_incomplete_focus_remains_viewable_but_not_fully_completed(self) -> None:
        with TemporaryDirectory() as directory:
            result_id = "a" * 32
            (Path(directory) / f"{result_id}.json").write_text(json.dumps({
                "validation": {"focus_complete": False},
                "execution": {"focus_error": "Connection error."},
            }), encoding="utf-8")
            manifest = {"entries": [{
                "source_path": "ppt_images/example.png", "status": "completed",
                "result_id": result_id, "error": None,
            }]}
            with patch.object(batch, "RESULT_DIR", Path(directory)):
                batch._reconcile_partial_results(manifest)
            self.assertEqual(manifest["entries"][0]["status"], "partial")
            self.assertEqual(manifest["entries"][0]["result_id"], result_id)
            self.assertIn("Connection error", manifest["entries"][0]["error"])
