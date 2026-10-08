"""失败重跑只选择原失败项，并保持五路、medium、无自动重试。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts import run_d02_ppt_enjoy_r5_failed_rerun as batch


class D02PptEnjoyR5FailedRerunTestCase(TestCase):
    def test_selection_is_exactly_the_95_failed_paths(self) -> None:
        source = json.loads(batch.SOURCE_MANIFEST.read_text(encoding="utf-8"))
        entries, source_fingerprint = batch._source_entries()
        expected = [row["source_path"] for row in source["entries"] if row["status"] == "failed"]
        self.assertEqual([row["source_path"] for row in entries], expected)
        self.assertEqual(len(entries), 95)
        self.assertEqual(len({row["sha256"] for row in entries}), 93)
        self.assertEqual(source_fingerprint, source["input_fingerprint"])

    def test_worker_uses_medium_and_records_separate_rerun_source(self) -> None:
        group = batch._source_entries()[0][:1]
        with TemporaryDirectory() as directory:
            result_id = "a" * 32
            (Path(directory) / f"{result_id}.json").write_text(json.dumps({
                "validation": {"focus_complete": True}, "execution": {},
            }), encoding="utf-8")
            with patch.object(batch, "RESULT_DIR", Path(directory)), patch.object(
                batch, "run_prism_r5_extraction", return_value=SimpleNamespace(result_id=result_id)
            ) as run:
                outcome = batch._run_group(group)
            self.assertEqual(outcome["status"], "completed")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["model_id"], "gpt-6-sol")
            self.assertEqual(run.call_args.kwargs["reasoning_effort"], "medium")
            self.assertEqual(run.call_args.kwargs["source_record"]["rerun_of_batch_id"], batch.SOURCE_BATCH_ID)
            self.assertEqual(batch.MAX_WORKERS, 5)
