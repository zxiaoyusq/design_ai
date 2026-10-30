"""0.4对象/代表性局部下游契约；合成断言只验程序，绝不授予真实视觉通过。"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from finalize_boards import VIEW_REVIEW_POLICY_VERSION, finalize, member_visual_supported, reviewed_view_snapshot
from render_delivery import board_validation, render, validate_display_scope
from review_boards import schema, verify_capture


def member(index=0):
    return {"unit_id": f"synthetic:{index}", "image_id": f"synthetic-{index}", "branch": "CMF",
            "sha256": f"synthetic-sha-{index}", "target_role": "peer_object_surface",
            "primary_subject": {"identity": f"同级设计对象{index}", "bbox": [.1, .1, .8, .8],
                                "whole_visible": True, "evidence": "合成定位，不是图像审阅"},
            "evidence_bbox": [.3, .3, .15, .15], "bbox": [.3, .3, .15, .15],
            "display_bbox": [.25, .25, .3, .3], "roi": [.25, .25, .3, .3],
            "display_scope": "representative_detail", "crop_reason": "合成局部框，用于验证比对象框更小的取景",
            "whole_object_visible": True, "usable": True, "limitations": [], "source_refs": []}


def member_review(item):
    return {"unit_id": item["unit_id"], "image_id": item["image_id"], "scope_correct": True,
            "primary_subject_supported": True, "whole_subject_compatible": True,
            "display_expression_supported": True, "crop_context_faithful": True,
            "emotion_combination_supported": True, "emotion_reason": "合成组合依据，不是视觉判断",
            "design_merit": "considered", "design_evidence": "合成设计依据，不是视觉判断",
            "image_quality": "usable", "relation_supported": True, "second_signal_compatible": True,
            "keep": True, "reason": "合成裁片表达与上下文检查", "suggested_roi": None}


def board_fixture():
    members = [member(index) for index in range(6)]
    board = {"board_id": "synthetic-local", "cluster_id": "synthetic-cluster", "branch": "CMF",
             "title": "合成局部板｜不是真实视觉结论", "members": members,
             "common_design_emotion": "合成感受",
             "emotion_combination_evidence": {"form": "合成形态", "proportion": "合成比例", "color": "合成色彩",
                                               "material_texture": None, "detail_language": "合成细节",
                                               "overall_relation": "功能夹具，不是对真实素材的视觉结论"}}
    review = {"board_id": board["board_id"], "title": board["title"], "common_relation": "合成共同关系",
              "common_design_emotion": board["common_design_emotion"],
              "emotion_combination_evidence": board["emotion_combination_evidence"],
              "visual_verdict": "coherent", "members": [member_review(item) for item in members],
              "provenance": {"review_policy_version": VIEW_REVIEW_POLICY_VERSION, "synthetic_test_only": True,
                             "reviewed_view": reviewed_view_snapshot(board)},
              "source_identity_checks": [{"unit_id": item["unit_id"], "image_id": item["image_id"],
                  "project_name": f"合成{index}", "project_key": f"synthetic-{index}", "project_state": "source_supported",
                  "reason": "合成来源", "runway_state": "no", "runway_reason": "合成状态"}
                  for index, item in enumerate(members)]}
    return board, {"review_policy_version": VIEW_REVIEW_POLICY_VERSION, "reviews": [review]}


class SelectedViewDeliveryTests(unittest.TestCase):
    def test_peer_representative_detail_can_be_smaller_than_object(self):
        item = member()
        validate_display_scope(item, deepcopy(item))
        self.assertLess(item["roi"][2], item["primary_subject"]["bbox"][2])
        item["display_bbox"] = item["roi"] = item["evidence_bbox"]
        validate_display_scope(item, deepcopy(item))

    def test_scope_changes_cannot_hide_frozen_object_or_facts(self):
        item = member()
        original = deepcopy(item)
        item["primary_subject"]["identity"] = "另一件物品"
        with self.assertRaisesRegex(ValueError, "冻结观察"):
            validate_display_scope(item, original)
        item = member()
        item["roi"] = [0, 0, 1, 1]
        with self.assertRaisesRegex(ValueError, "实际ROI"):
            validate_display_scope(item, {})

    def test_whole_object_scope_still_requires_whole_object_frame(self):
        item = member()
        item["display_scope"] = "whole_object"
        with self.assertRaisesRegex(ValueError, "whole_object"):
            validate_display_scope(item, {})

    def test_peer_role_cannot_downgrade_by_omitting_scope(self):
        item = member()
        item.pop("display_scope")
        with self.assertRaisesRegex(ValueError, "不能退回旧规则"):
            validate_display_scope(item, {})

    def test_new_policy_needs_both_crop_expression_and_faithful_context(self):
        checked = member_review(member())
        self.assertTrue(member_visual_supported(checked, True, True))
        for field in ("display_expression_supported", "crop_context_faithful"):
            bad = {**checked, field: False}
            self.assertFalse(member_visual_supported(bad, True, True))
            self.assertTrue(member_visual_supported(bad, True))
            self.assertIn(field, schema()["properties"]["members"]["items"]["required"])

    def test_old_review_cannot_grant_new_view_pass(self):
        board, reviews = board_fixture()
        checked = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertTrue(checked["validation"]["visual"])
        self.assertEqual(board_validation(checked, None)[1][0]["state"], "passed")
        self.assertEqual(board_validation(board, reviews["reviews"][0], "primary-subject-design-emotion.v3")[1][0]["state"], "revision")
        reviews["review_policy_version"] = "primary-subject-design-emotion.v3"
        reviews["reviews"][0]["provenance"]["review_policy_version"] = "primary-subject-design-emotion.v3"
        rejected = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertFalse(rejected["validation"]["visual"])
        self.assertEqual(board_validation(board, reviews["reviews"][0])[1][0]["state"], "revision")
        self.assertFalse(rejected["designer_approved"])

    def test_legacy_board_can_still_show_its_original_review(self):
        board, reviews = board_fixture()
        for item in board["members"]:
            del item["display_scope"]
            del item["crop_reason"]
            item["target_role"] = "primary_object_surface"
        reviews["review_policy_version"] = "primary-subject-design-emotion.v3"
        reviews["reviews"][0]["provenance"]["review_policy_version"] = "primary-subject-design-emotion.v3"
        for checked in reviews["reviews"][0]["members"]:
            del checked["display_expression_supported"]
            del checked["crop_context_faithful"]
        finalized = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertTrue(finalized["validation"]["visual"])
        self.assertEqual(board_validation(finalized, None)[1][0]["state"], "passed")

    def test_current_crop_failure_overrules_top_level_coherent(self):
        board, reviews = board_fixture()
        reviews["reviews"][0]["members"][0]["crop_context_faithful"] = False
        finalized = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertFalse(finalized["validation"]["visual"])
        self.assertEqual(finalized["members"][0]["target_quality_status"], "reviewed_needs_revision")

    def test_legal_crop_change_cannot_reuse_embedded_pass_without_reviews_file(self):
        board, reviews = board_fixture()
        frozen_original = deepcopy(board["members"][0])
        finalized = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertEqual(board_validation(finalized, None)[1][0]["state"], "passed")
        item = finalized["members"][0]
        item["roi"] = item["display_bbox"] = [.28, .28, .2, .2]
        # 合法新框仍包含事实且属于同一对象，但必须重新审实际板图。
        validate_display_scope(item, frozen_original)
        self.assertEqual(board_validation(finalized, None)[1][0]["state"], "revision")
        self.assertEqual(finalized["review_provenance"]["reviewed_view"]["members"][0]["roi"], frozen_original["roi"])

    def test_embedded_review_snapshot_binds_source_object_order_and_scope_reason(self):
        board, reviews = board_fixture()
        original = finalize({"boards": [board]}, reviews)["boards"][0]
        changes = {"sha256": "another-original", "target_role": "primary_object_surface",
                   "evidence_bbox": [.31, .31, .1, .1], "crop_reason": "另一种取景解释",
                   "primary_subject": {**original["members"][0]["primary_subject"], "identity": "另一对象"}}
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = deepcopy(original)
                changed["members"][0][field] = value
                self.assertEqual(board_validation(changed, None)[1][0]["state"], "revision")
        original["members"].reverse()
        self.assertEqual(board_validation(original, None)[1][0]["state"], "revision")

    def test_missing_snapshot_cannot_grant_new_view_pass(self):
        board, reviews = board_fixture()
        reviews["reviews"][0]["provenance"].pop("reviewed_view")
        finalized = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertFalse(finalized["validation"]["visual"])
        self.assertEqual(board_validation(finalized, None)[1][0]["state"], "revision")

    @unittest.skipUnless(os.environ.get("PRISM_BROWSER_TEST") == "1", "显式启用两板离线浏览验证")
    def test_two_synthetic_boards_in_real_browser(self):
        from PIL import Image
        # 留下临时截图供人工核查；不写业务数据，也不发模型请求。
        folder = Path(tempfile.mkdtemp(prefix="prism-selected-view-delivery-"))
        board, reviews = board_fixture()
        images = []
        for index, item in enumerate(board["members"]):
            path = folder / f"synthetic-{index}.png"
            Image.new("RGB", (360 + index * 10, 260), (45 + index * 25, 100, 120)).save(path)
            item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            images.append({"image_id": item["image_id"], "sha256": item["sha256"], "local_path": str(path),
                           "sources": [{"article_id": f"synthetic-{index}", "title": "合成来源",
                                        "article_url": f"https://example.invalid/synthetic/{index}"}]})
        reviews["reviews"][0]["provenance"]["reviewed_view"] = reviewed_view_snapshot(board)
        supported = finalize({"boards": [board]}, reviews)["boards"][0]
        diagnostic = deepcopy(supported)
        diagnostic.update(board_id="synthetic-diagnostic", branch="ID")
        diagnostic["validation"]["visual"] = False
        diagnostic["members"][0]["current_target_review"]["display_expression_supported"] = False
        documents = {"sample.json": {"images": images},
                     "observations.json": {"units": board["members"], "images": [], "counts": {"observed": 6}},
                     "clusters.json": {"clusters": []}, "boards.json": {"boards": [supported, diagnostic]}}
        for name, content in documents.items():
            (folder / name).write_text(json.dumps(content, ensure_ascii=False))
        args = argparse.Namespace(run_dir=folder, out=folder / "delivery", sample=None, observations=None,
                                  clusters=None, boards=None, reviews=None, history_delivery=[])
        render(args)
        subprocess.run(["node", str(SCRIPTS / "capture_boards.cjs"), "--delivery", str(args.out),
                        "--out", str(folder / "captures")], check=True)
        verify_capture(supported, folder / "captures/synthetic-local.png")
        changed = deepcopy(supported)
        changed["members"][0]["primary_subject"]["identity"] = "同位置上的另一个对象"
        with self.assertRaisesRegex(ValueError, "不是当前版本"):
            verify_capture(changed, folder / "captures/synthetic-local.png")
        print(json.dumps({"fixture": str(folder), "boards": 2, "model_calls": 0,
                          "visual_pass_awarded": False, "synthetic_functional_check_only": True}))


if __name__ == "__main__":
    unittest.main()
