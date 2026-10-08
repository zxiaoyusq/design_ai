"""D02 V2 的离线追溯、候选隔离和复核边界。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services.dna import prism_v2


class PrismDnaV2TestCase(TestCase):
    def test_core_cmf_decodes_from_frozen_dictionary_and_review_rejects_gaps(self) -> None:
        candidate = {"o": [{"t": 10, "g": [0] * 8, "c": "123111", "v": ["#efefef"], "d": []}]}
        observations = prism_v2._observations(candidate)
        fields = {item["field_id"]: item["value"] for item in observations}
        self.assertEqual(fields["OPT-001"], "玻璃外观")
        self.assertEqual(fields["OPT-002"], "高光")
        self.assertEqual(fields["OPT-007"], "不透明")
        self.assertIn("COL-006", fields)

        rows, issues = prism_v2._review_rows(
            {"reviews": [{"object_index": 0, "field_id": "OPT-001", "verdict": "supported", "reason": "可见"}]},
            observations,
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("缺少" in issue for issue in issues))

    def test_open_core_literal_and_parent_cycle_are_not_silently_accepted(self) -> None:
        candidate = {"o": [
            {"t": 1, "g": [0, 0, 0, 1000, 1000, -1, -1, 0], "c": "10", "v": [-1], "d": []},
            {"t": 10, "g": [2, 10, 10, 100, 100, 30, 30, 1], "c": "1x2100", "v": [-1, "半透明涂层"], "d": []},
        ]}
        observations = prism_v2._observations(candidate)
        self.assertEqual(
            next(item["value"] for item in observations if item["field_id"] == "OPT-001"),
            "半透明涂层",
        )
        self.assertTrue(any("父对象" in issue for issue in prism_v2._protocol_issues(candidate)))

    def test_invalid_candidate_keeps_raw_reply_and_never_claims_projection(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / ("a" * 32) / "sample.png"
            image.parent.mkdir()
            image.write_bytes(b"fake-image-for-offline-test")
            with (
                patch.object(prism_v2, "RESULT_DIR", root / "results"),
                patch.object(prism_v2, "save_result_image"),
                patch.object(prism_v2, "create_primary_agent"),
                patch.object(prism_v2, "create_review_agent") as reviewer,
                patch.object(prism_v2, "_invoke", return_value='{"o":[],"f":[],"q":{},"issues":[]}'),
            ):
                output = prism_v2.run_prism_v2_extraction(
                    image_path=image, content_type="image/png", model_id="gemini-3.8-flash",
                    user_prompt="关注材质",
                )
                payload = json.loads((root / "results" / f"{output.result_id}.json").read_text())

            self.assertEqual(payload["skill"], "prism-image-dna")
            self.assertEqual(payload["source"]["image_id"], "a" * 32)
            self.assertEqual(payload["execution"]["model_id"], "gemini-3.8-flash")
            self.assertFalse(payload["validation"]["r41_schema_valid"])
            self.assertFalse(payload["validation"]["official_projection_verified"])
            self.assertEqual(payload["raw_responses"]["primary"], '{"o":[],"f":[],"q":{},"issues":[]}')
            reviewer.assert_not_called()
