"""合成图片只验证统一结果的渲染、出处与未审状态，不评估审美。"""
import argparse
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from render_delivery import digest, ref, render


class PageContent(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.filters = []
        self.page_json = ""
        self.in_page_data = False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "button" and "data-filter" in attrs:
            self.filters.append(attrs["data-filter"])
        if tag == "script" and attrs.get("id") == "page-data":
            self.in_page_data = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_page_data = False

    def handle_data(self, data):
        if self.in_page_data:
            self.page_json += data


def fixture(root, *, mixed=False, invalid_branch=False):
    """真实创建小图及冻结展示引用，覆盖此前 DESIGN 被入口拒绝的路径。"""
    images, units, members = [], [], []
    for number in range(6):
        image_path = root / f"synthetic-{number}.png"
        Image.new("RGB", (60 + number, 48), (number * 25, 50, 100)).save(image_path)
        identity = f"synthetic-{number}"
        image_sha = digest(image_path)
        image = {"image_id": identity, "sha256": image_sha, "local_path": str(image_path),
                 "sources": [{"article_id": identity, "title": "合成测试来源"}]}
        unit = {"unit_id": f"{identity}:CMF:1", "image_id": identity, "image_sha256": image_sha,
                "branch": "ID" if number % 2 else "CMF", "subject": {"identity": "合成对象"},
                "display_scope": "representative_detail", "crop_reason": "测试冻结取景",
                "display_bbox": [.1, .1, .8, .8], "evidence_bbox": [.2, .2, .3, .3]}
        member = {"unit_id": unit["unit_id"], "image_id": identity, "sha256": image_sha,
                  "branch": unit["branch"], "roi": unit["display_bbox"],
                  "display_bbox": unit["display_bbox"], "evidence_bbox": unit["evidence_bbox"]}
        images.append(image)
        units.append(unit)
        members.append(member)
    board = {"board_id": "synthetic-unified", "cluster_id": "synthetic-cluster", "branch": "DESIGN",
             "title": "合成统一候选：不代表视觉通过", "members": members,
             "validation": {"visual": None, "quantity": True, "source": None, "runway": None}}
    if invalid_branch:
        board["branch"] = "unrecognized"
    boards = [board]
    if mixed:
        historical = deepcopy(board)
        historical.update(board_id="synthetic-historical", branch="CMF")
        boards.append(historical)
    documents = {
        "sample.json": {"images": images},
        "observations.json": {"schema_version": "prism.design_cards_display_compat.v1", "units": units},
        "clusters.json": {"clusters": [], "summary": {"mode": "priority_boards", "comparison_mode": "unified",
            "branch_coverage": {"DESIGN": {"input_cards": 6, "route_compared_cards": 6,
                                            "actually_visually_compared": 6, "not_selected_direction": 0}}}},
    }
    for name, value in documents.items():
        (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    (root / "boards.json").write_text(json.dumps({"boards": boards, "input_refs": {
        "sample": ref(root / "sample.json"), "observations": ref(root / "observations.json")}}, ensure_ascii=False), encoding="utf-8")
    return argparse.Namespace(run_dir=root, out=root / "delivery", sample=None, observations=None,
                              clusters=None, boards=None, reviews=None, history_delivery=[]), boards


class UnifiedDeliveryTests(unittest.TestCase):
    def test_unified_render_keeps_source_branches_pixels_roi_and_pending_state(self):
        with tempfile.TemporaryDirectory(prefix="prism-unified-delivery-") as temporary:
            args, original = fixture(Path(temporary))
            result = render(args)
            self.assertEqual(result["board_count"], 1)
            manifest = json.loads((args.out / "delivery-manifest.json").read_bytes())
            board = manifest["boards"][0]
            self.assertEqual(board["branch"], "DESIGN")
            self.assertEqual([row["branch"] for row in board["members"]], [row["branch"] for row in original[0]["members"]])
            self.assertEqual([row["roi"] for row in board["members"]], [row["roi"] for row in original[0]["members"]])
            for member in board["members"]:
                self.assertEqual(digest(args.out / member["asset_path"]), member["sha256"])
            self.assertEqual(next(row["state"] for row in board["validation_display"] if row["key"] == "visual"), "pending")
            self.assertFalse(manifest["visual_pass_awarded_by_renderer"])
            self.assertFalse(manifest["designer_confirmation_awarded_by_renderer"])
            self.assertEqual(PageContent((args.out / "index.html").read_text()).filters, ["all"])
            detail = json.loads(PageContent((args.out / board["path"]).read_text()).page_json)
            self.assertEqual(detail["board"]["branch"], "DESIGN")
            self.assertFalse(detail["board"]["designer_confirmed"])

    def test_mixed_historical_delivery_keeps_separate_filter_identity(self):
        with tempfile.TemporaryDirectory(prefix="prism-mixed-delivery-") as temporary:
            args, original = fixture(Path(temporary), mixed=True)
            render(args)
            self.assertEqual(PageContent((args.out / "index.html").read_text()).filters, ["all", "DESIGN", "CMF"])
            saved = json.loads((args.out / "data/boards.json").read_bytes())
            self.assertEqual([board["branch"] for board in saved["boards"]], [board["branch"] for board in original])

    def test_unrecognized_branch_still_fails(self):
        with tempfile.TemporaryDirectory(prefix="prism-invalid-delivery-") as temporary:
            args, _ = fixture(Path(temporary), invalid_branch=True)
            with self.assertRaisesRegex(ValueError, "未知分支"):
                render(args)


if __name__ == "__main__":
    unittest.main()
