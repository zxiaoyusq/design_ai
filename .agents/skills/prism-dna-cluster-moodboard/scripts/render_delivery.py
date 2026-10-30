"""把当前DNA聚类板和真实状态整理为离线HTML；只复制原字节，不授予视觉通过。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image
from finalize_boards import (board_emotion_evidence_recorded, member_visual_supported,
                             concrete_relation_review_supported, requires_relation_review,
                             requires_view_review, reviewed_view_matches, view_review_policy_matches)
from design_emotion import validate_display_contract


def read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": digest(path)}


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def script_json(value: Any) -> str:
    # 输入标题和说明不可提前结束script标签。
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_layout_overrides(value: Any, allowed_ids: set[str]) -> dict:
    """只接受明确成员的版面尺寸；不能借展示配置改图、换框或插入任意 CSS。"""
    if not isinstance(value, dict) or not set(value) <= allowed_ids:
        raise ValueError("layout_overrides 必须按当前 unit_id 指定，不能含未知成员")
    for identity, settings in value.items():
        if not isinstance(settings, dict) or not settings or set(settings) - {"columns", "height", "mobile_height"}:
            raise ValueError(f"未知布局字段：{identity}")
        for key, number in settings.items():
            low, high = (1, 4) if key == "columns" else (120, 1000)
            if not isinstance(number, int) or isinstance(number, bool) or not low <= number <= high:
                raise ValueError(f"布局尺寸越界：{identity} / {key}")
    return deepcopy(value)


def layout_binding(board: dict, overrides: dict) -> dict:
    relevant = {m["unit_id"]: overrides[m["unit_id"]] for m in board["members"] if m["unit_id"] in overrides}
    binding = {"version": "prism.board_layout.v1", "renderer_ref": ref(Path(__file__)), "overrides": relevant,
               "members": [{key: m.get(key) for key in ("unit_id", "image_id", "sha256", "roi", "evidence_bbox")} for m in board["members"]]}
    binding["identity"] = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return binding


def review_layout_identity(review: dict | None) -> str | None:
    """无新布局身份的历史审阅返回 None；坏引用仍须失效，不能当历史缺字段放行。"""
    provenance = (review or {}).get("provenance", {})
    capture_ref = provenance.get("capture_record_ref") or provenance.get("capture_sidecar_ref")
    if capture_ref is None:
        return None
    if not isinstance(capture_ref, dict) or not capture_ref.get("path"):
        return "invalid_capture_reference"
    path = Path(capture_ref["path"])
    if not path.is_file() or digest(path) != capture_ref.get("sha256"):
        return "invalid_capture_reference"
    capture = read(path)
    return capture.get("layout_identity")


def review_matches_layout(review: dict | None, binding: dict) -> bool:
    """显示尺度参与审阅身份；仅同 board_id 或同 ROI 的旧 PASS 不能沿用。"""
    return review_layout_identity(review) == binding["identity"]


def review_map(data: Any) -> dict[str, dict]:
    """接受按board_id的对象或reviews数组；缺审阅不能推断为已通过。"""
    if data is None:
        return {}
    if isinstance(data, list):
        return {item["board_id"]: item for item in data}
    if "reviews" in data:
        return review_map(data["reviews"])
    if "boards" in data and isinstance(data["boards"], (dict, list)):
        return review_map(data["boards"])
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def review_state(review: dict | None) -> tuple[str, str]:
    if not review:
        return "pending", "待 AI 审阅"
    verdict = review.get("visual_verdict", review.get("verdict", review.get("visual_status", review.get("status"))))
    if verdict in {"pass", "passed", "coherent", "accepted"}:
        return "passed", "AI 审阅通过"
    if verdict in {"fail", "failed", "incoherent", "rejected", "needs_revision", "blocked"}:
        return "revision", "需要调整"
    return "pending", "审阅有未决项"


def board_validation(board: dict, review: dict | None, document_policy: str | None = None) -> tuple[tuple[str, str], list[dict]]:
    """采用当前逐项验收结果；视觉通过不能掩盖来源、数量或秀场未决。"""
    checks = board.get("mechanical_checks") or {}
    validated = board.get("validation") or {}
    visual = validated.get("visual")
    require_relation_review = requires_relation_review(board, review)
    require_current_view = requires_view_review(board) or require_relation_review
    require_subject_review = require_current_view or any(member.get("display_bbox") is not None for member in board["members"])
    if require_subject_review:
        # 新对象或取景不能沿用旧整物规则的通过；历史板仍按它原来的协议展示。
        checked = review.get("members", []) if review else [member.get("current_target_review", {}) for member in board["members"]]
        current_ids = {(member["unit_id"], member["image_id"]) for member in board["members"]}
        checked_ids = {(member.get("unit_id"), member.get("image_id")) for member in checked}
        if (checked_ids != current_ids or len(checked) != len(current_ids)
                or not all(member_visual_supported(member, True, require_current_view, require_relation_review) for member in checked)
                or not view_review_policy_matches(board, review, document_policy)
                or not reviewed_view_matches(board, review)
                or not board_emotion_evidence_recorded(review or board)):
            visual = False if review or visual is not None else None
    if require_relation_review and (not concrete_relation_review_supported(board, review)
                                    or (review and review.get("visual_verdict") != "coherent")):
        visual = False if review or visual is not None else None
    if board.get("current_layout_review_pending") or (board.get("review_invalidation") and not review):
        visual = None
        review = None
    if visual is None and review:
        verdict = review_state(review)[0]
        members = review.get("members", [])
        member_conflict = any(
            any(member.get(field) is False for field in ("scope_correct", "relation_supported", "second_signal_compatible", "keep", "primary_subject_supported", "whole_subject_compatible", "emotion_combination_supported", "display_expression_supported", "crop_context_faithful"))
            or member.get("image_quality") == "unreadable" for member in members
        )
        visual = False if verdict == "revision" or member_conflict else True if verdict == "passed" else None
    prior_view_pending = visual is not True and any(member.get("prior_view_failures") for member in board["members"])
    visual_row = {"key": "visual", "state": "passed" if visual is True else "revision" if visual is False else "pending",
                  "label": "视觉审阅通过" if visual is True else "视觉需调整" if visual is False else "已有取景问题待复核" if prior_view_pending else "视觉待审阅"}
    quantity = validated.get("quantity", checks.get("quantity_pass"))
    if quantity is None and isinstance(checks.get("quantity"), bool):
        quantity = checks["quantity"]
    quantity_row = {"key": "quantity", "state": "passed" if quantity is True else "revision" if quantity is False else "pending",
                    "label": "图数符合" if quantity is True else "图数需调整" if quantity is False else "图数待核"}
    source = validated.get("source")
    if source is None and checks.get("project_identity_complete") is True:
        source = all(checks.get(key) is True for key in ("source_articles_unique", "known_projects_unique"))
    source_duplicate = any(checks.get(key) is False for key in ("source_articles_unique", "known_source_groups_unique", "known_projects_unique"))
    source_row = {"key": "source", "state": "passed" if source is True else "revision" if source_duplicate else "pending",
                  "label": "来源已核" if source is True else "来源需调整" if source_duplicate else "来源待核"}
    runway = validated.get("runway", checks.get("runway_conservative_pass"))
    known_overflow = checks.get("runway_known_count", 0) > checks.get("runway_maximum", len(board["members"]) * 30 // 100)
    runway_row = {"key": "runway", "state": "passed" if runway is True else "revision" if known_overflow else "pending",
                  "label": "秀场占比符合" if runway is True else "秀场占比超限" if known_overflow else "秀场占比待核"}
    rows = [visual_row, quantity_row, source_row, runway_row]
    if all(row["state"] == "passed" for row in rows):
        overall = ("passed", "AI 检查通过")
    elif any(row["state"] == "revision" for row in rows):
        overall = ("revision", "需要调整")
    else:
        overall = ("pending", "视觉通过 · 仍有待核项" if visual is True else "候选板 · 取景待复核" if prior_view_pending else "候选板 · 待审阅")
    return overall, rows


def profile_text(profile: Any) -> str:
    if isinstance(profile, str):
        return profile
    if isinstance(profile, dict):
        for key in ("summary", "common_relation", "description", "visible_relationship"):
            if isinstance(profile.get(key), str):
                return profile[key]
    return "从图片的可见特征归纳共同关系，保留真实差异与来源。"


def build_image_ledger(sample: dict, observations: dict, clusters: dict, boards: list[dict]) -> dict:
    """把同一冻结样本的处理状态和全部去向联起来，未观察及未成板图片也保留。"""
    observation_by_sha = {image["sha256"]: image for image in observations.get("images", [])}
    image_disposition = {item["image_id"]: item for item in clusters.get("image_dispositions", [])}
    unit_dispositions: dict[str, list] = {}
    for item in clusters.get("unit_dispositions", []):
        unit_dispositions.setdefault(item["image_id"], []).append(item)
    clusters_by_unit: dict[str, list[str]] = {}
    for cluster in clusters.get("clusters", []):
        for unit_id in cluster.get("unit_ids", []):
            clusters_by_unit.setdefault(unit_id, []).append(cluster["cluster_id"])
    boards_by_sha: dict[str, list[dict]] = {}
    for board in boards:
        for member in board["members"]:
            boards_by_sha.setdefault(member["sha256"], []).append({
                "board_id": board["board_id"], "unit_id": member.get("unit_id"),
                "branch": board["branch"], "title": board["title"], "status": board.get("status"),
                "display_status": board["review_display"], "validation": board.get("validation"),
                "roi": member["roi"], "display_bbox": member.get("display_bbox"),
                "evidence_bbox": member.get("evidence_bbox"),
                "display_scope": member.get("display_scope"), "crop_reason": member.get("crop_reason"),
            })
    rows = []
    for image in sample["images"]:
        observation = observation_by_sha.get(image["sha256"], {})
        dispositions = unit_dispositions.get(image["image_id"], [])
        rows.append({
            "image_id": image["image_id"], "sha256": image["sha256"],
            "local_path": image["local_path"], "image_url": image.get("image_url"),
            "aliases": image.get("aliases", []), "sources": image.get("sources", []),
            "observation_status": observation.get("status", "not_recorded"),
            "observation_limitations": observation.get("observation_limitations", []),
            "image_disposition": image_disposition.get(image["image_id"]),
            "unit_dispositions": dispositions,
            "cluster_ids": sorted({cluster_id for item in dispositions for cluster_id in clusters_by_unit.get(item["unit_id"], [])}),
            "current_board_occurrences": boards_by_sha.get(image["sha256"], []),
            "observation_ref": observation.get("observation_ref"),
        })
    return {"schema_version": "prism.dna_cluster_image_ledger.v1", "image_count": len(rows),
            "observation_status_counts": dict(Counter(row["observation_status"] for row in rows)),
            "all_sample_images_retained": len(rows) == len(sample["images"]),
            "note": "这是当前版本全样本去向；当前板包含候选与诊断状态，不代表所有出现图片已通过视觉审阅。",
            "images": rows}


def validate_roi(value: Any) -> list[float]:
    roi = [float(x) for x in (value if value is not None else [0, 0, 1, 1])]
    if len(roi) != 4 or not all(math.isfinite(x) for x in roi):
        raise ValueError(f"ROI必须为四个有限数：[x,y,w,h]，实际为{value}")
    x, y, width, height = roi
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
        raise ValueError(f"ROI越过原图范围：{value}")
    return roi


def image_readability_dimensions(width: int, height: int, roi: list[float]) -> dict:
    """归一化ROI按原图尺寸换算为连续像素范围；不四舍五入裁图，也不判定清晰度。"""
    return {
        "original_dimensions_px": [width, height],
        "roi_native_dimensions_px": [width * roi[2], height * roi[3]],
    }


def validate_display_scope(member: dict, observation: dict) -> None:
    """展示框可为整体或代表性局部，但不能在渲染时改框并沿用原板身份。"""
    if requires_view_review({"members": [member]}) and not member.get("display_scope"):
        raise ValueError(f"新对象协议缺display_scope，不能退回旧规则：{member['unit_id']}")
    if member.get("display_bbox") is None and observation.get("display_bbox") is None:
        return
    if member.get("display_bbox") is None or member.get("evidence_bbox") is None:
        raise ValueError(f"新版成员缺所选对象展示框或事实框：{member['unit_id']}")
    display = validate_roi(member["display_bbox"])
    roi = validate_roi(member.get("roi"))
    if any(abs(left - right) > 1e-9 for left, right in zip(display, roi)):
        raise ValueError(f"实际ROI必须等于已明确选择的display_bbox，不能渲染时换框：{member['unit_id']}")
    member["display_bbox"] = display
    member["evidence_bbox"] = validate_roi(member["evidence_bbox"])
    if member.get("display_scope"):
        # 图板记录不重复保存bbox/usable；补入冻结观察的事实定义，不把展示范围推成新DNA。
        for field in ("primary_subject", "target_role", "evidence_bbox", "display_scope"):
            if field in observation and member.get(field) != observation[field]:
                raise ValueError(f"图板所选对象或事实与冻结观察不一致：{member['unit_id']} / {field}")
        validate_display_contract({**observation, **member,
                                   "bbox": observation.get("bbox", member["evidence_bbox"]), "usable": True})
    elif observation.get("display_scope"):
        raise ValueError(f"成员丢失新观察的展示范围契约：{member['unit_id']}")


STYLE = r"""
:root{--ink:#183c3a;--muted:#6e807a;--accent:#176e60;--paper:#f5f5ee;--line:#dce3d9;--warm:#a6653c;--white:#fffef9}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}button,input,textarea,select{font:inherit}a{color:inherit;text-decoration:none}button,a,select,textarea{outline-offset:4px}button{cursor:pointer}button:focus-visible,a:focus-visible{outline:2px solid var(--accent)}[hidden]{display:none!important}.shell{max-width:1392px;margin:0 auto;padding:36px 42px 48px}.topline{display:flex;justify-content:space-between;align-items:center;gap:20px;font-size:12px;letter-spacing:.12em;color:var(--muted)}.brand{font-weight:800;letter-spacing:.18em;color:var(--accent)}.brand-mark{display:inline-block;width:10px;height:10px;border:1px solid var(--accent);transform:rotate(45deg);margin-right:10px}.hero{padding:44px 0 27px;border-bottom:1px solid var(--line)}.eyebrow{text-transform:uppercase;font-size:12px;letter-spacing:.16em;color:var(--muted);margin:0 0 12px}h1,h2,h3,p{margin:0}h1{font-size:clamp(28px,3.2vw,44px);line-height:1.25;font-weight:550;letter-spacing:.01em;max-width:1000px}.lead{margin-top:16px;max-width:850px;font-size:16px;color:var(--muted)}.counts{display:flex;gap:25px;flex-wrap:wrap;margin-top:25px;font-size:13px;color:var(--muted)}.counts b{font-size:21px;color:var(--ink);margin-right:7px;font-weight:500}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:25px 0;flex-wrap:wrap}.filters{display:flex;gap:6px}.filter{border:1px solid transparent;background:transparent;border-radius:25px;padding:7px 18px;color:var(--muted)}.filter[aria-pressed=true]{background:var(--ink);color:white}.quiet-link{font-size:13px;text-decoration:underline;text-underline-offset:4px;color:var(--muted)}.card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px}.board-card{display:block;border:1px solid var(--line);background:var(--white);border-radius:12px;overflow:hidden;transition:transform .15s,box-shadow .15s}.board-card:hover{transform:translateY(-3px);box-shadow:0 9px 24px #244a3d0a}.mini-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;padding:13px;background:#eaeee6}.mini-grid .viewport{height:115px;background:#f7f8f2}.card-body{padding:19px 22px 24px}.card-top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}.branch{font-size:11px;letter-spacing:.12em;font-weight:700;color:var(--accent)}.status{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)}.status:before{content:"";width:5px;height:5px;border-radius:50%;background:#adb8ad}.status.passed:before{background:#297d56}.status.revision:before{background:#b47a3d}.card-body h2{font-size:22px;line-height:1.45;font-weight:550}.card-body p{font-size:13px;color:var(--muted);margin-top:9px}.card-foot{display:flex;justify-content:space-between;margin-top:18px;font-size:12px;color:var(--muted)}.section-note{font-size:13px;color:var(--muted);line-height:1.7;margin:25px 0}.downloads{border-top:1px solid var(--line);padding-top:25px;margin-top:35px;display:flex;gap:18px;flex-wrap:wrap}.downloads a{font-size:12px;color:var(--muted);text-decoration:underline;text-underline-offset:4px}.board-header{padding-bottom:21px}.board-header .hero{padding-top:32px}.board-meta{display:flex;align-items:center;gap:20px;flex-wrap:wrap;margin-top:18px;color:var(--muted);font-size:13px}.board-meta .status{font-size:13px}.board-grid{display:grid;grid-template-columns:repeat(var(--cols),minmax(0,1fr));gap:14px;background:var(--paper);padding:5px 0}.tile{min-width:0;margin:0;border:1px solid var(--line);background:var(--white);border-radius:9px;overflow:hidden}.tile-open{border:0;padding:0;display:block;width:100%;color:inherit;background:transparent;text-align:left}.viewport{height:228px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#eceee8;position:relative}.image-window{position:relative;overflow:hidden;flex:none}.image-window img{position:absolute;max-width:none;display:block;pointer-events:none}.tile-caption{padding:12px 13px;display:flex;gap:10px;align-items:center;min-height:47px}.tile-number{font-size:12px;font-variant-numeric:tabular-nums;color:var(--muted)}.tile-name{font-size:12px;white-space:nowrap;text-overflow:ellipsis;overflow:hidden}.tile-view{margin-left:auto;color:var(--muted);font-size:13px}.board-grid.cols-5 .viewport{height:198px}.review-note{padding:16px 18px;margin:24px 0;border-left:3px solid var(--line);font-size:13px;color:var(--muted);background:#f0f2e9}.feedback{border-top:1px solid var(--line);padding-top:27px;margin-top:30px;display:grid;grid-template-columns:1fr 2fr;gap:28px}.feedback h2{font-size:19px;font-weight:500;margin-bottom:7px}.feedback p{font-size:13px;color:var(--muted)}.feedback-form{display:grid;gap:12px}.feedback-form select,.feedback-form textarea{border:1px solid var(--line);border-radius:7px;background:var(--white);padding:10px 12px;color:var(--ink);width:100%;min-width:0}.feedback-form textarea{height:84px;resize:vertical}.form-actions{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.primary-btn,.secondary-btn{padding:8px 16px;border-radius:7px;border:1px solid var(--ink);font-size:13px}.primary-btn{background:var(--ink);color:white}.secondary-btn{background:transparent;color:var(--ink)}.feedback-message{font-size:12px;color:var(--muted)}.modal-backdrop{position:fixed;inset:0;background:#152a28cc;z-index:20;display:flex;align-items:center;justify-content:center;padding:24px;backdrop-filter:blur(5px)}.modal{background:var(--white);border-radius:14px;width:min(1190px,100%);max-height:94vh;overflow:auto;box-shadow:0 20px 90px #0004}.modal-toolbar{display:flex;justify-content:space-between;align-items:center;padding:15px 20px;border-bottom:1px solid var(--line);gap:15px}.modal-toolbar h2{font-size:16px;font-weight:500}.icon-button{border:0;background:transparent;font-size:23px;color:var(--ink);padding:0 6px}.modal-main{display:grid;grid-template-columns:minmax(0,1fr) 300px;min-height:300px}.original-wrap{display:flex;align-items:center;justify-content:center;padding:18px;min-height:300px;background:#e9ede6;overflow:hidden}.original-stage{position:relative;max-width:100%}.original-stage img{display:block;width:100%;height:auto}.roi-outline{position:absolute;border:2px solid #faff9c;outline:1px solid #143d30;pointer-events:none;box-shadow:0 0 0 9999px #17302518}.source-panel{padding:23px;font-size:13px;overflow-wrap:anywhere}.source-panel h3{font-size:13px;font-weight:600;margin:20px 0 7px}.source-panel h3:first-child{margin-top:0}.source-panel p{color:var(--muted);margin:7px 0}.source-panel a{display:block;margin:9px 0;text-decoration:underline;text-underline-offset:4px;color:var(--accent)}.source-panel .source-item{border-top:1px solid var(--line);padding-top:9px;margin-top:11px}.modal-hint{font-size:11px;color:var(--muted)}footer{margin-top:33px;font-size:11px;color:var(--muted);display:flex;justify-content:space-between;gap:15px}.empty{padding:30px 0;color:var(--muted)}
@media(max-width:1000px){.shell{padding:25px}.board-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.board-grid .viewport{height:200px}.mini-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.mini-grid .viewport{height:105px}.modal-main{grid-template-columns:minmax(0,1fr) 250px}}
@media(max-width:620px){.shell{padding:23px 16px 35px}.topline{font-size:10px}.hero{padding-top:30px}.lead{font-size:14px}.counts{gap:15px}.counts b{font-size:18px}.toolbar{padding:20px 0}.filter{padding:6px 14px}.card-grid{grid-template-columns:1fr;gap:20px}.mini-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.mini-grid .viewport{height:95px}.card-body{padding:16px 18px}.card-body h2{font-size:20px}.board-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.board-grid .viewport{height:165px}.tile-caption{padding:9px 10px;min-height:41px;gap:6px}.tile-name{font-size:10px}.feedback{grid-template-columns:1fr;gap:17px}.modal-backdrop{padding:10px}.modal-main{grid-template-columns:1fr}.original-wrap{padding:14px;min-height:180px}.source-panel{padding:18px}.modal{max-height:96vh}.modal-toolbar{padding:12px}.modal-hint{display:none}.board-meta{gap:12px}footer{font-size:10px}.downloads{gap:14px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
.result-section{margin:20px 0 38px}.result-section h2.section-title{font-size:22px;font-weight:550;margin:0 0 7px}.section-description{font-size:13px;color:var(--muted);margin:0 0 18px}.result-section[data-result-group=diagnostic]{border-top:1px solid var(--line);padding-top:25px}.result-section[data-result-group=diagnostic] .section-title{color:var(--warm)}
"""


STYLE += r"""
.evidence-outline{position:absolute;border:2px dashed #31e0df;pointer-events:none}.diagnostic-details{margin:30px 0;border:1px solid var(--line);border-radius:10px;padding:18px}.diagnostic-details>summary{cursor:pointer;font-size:17px;color:var(--muted)}.diagnostic-details .section-description{margin-top:12px}.diagnostic-details .card-grid{margin-top:20px}.subject-quality{margin-top:12px}.empty-supported{padding:22px 0;color:var(--muted);border-bottom:1px solid var(--line)}.emotion-review{margin:5px 0 22px;padding:18px 20px;background:#edf1e8;border-radius:9px}.emotion-review h2{font-size:18px;font-weight:550}.emotion-review p,.emotion-review dl{margin-top:8px;font-size:13px;color:var(--muted)}.emotion-review summary{margin-top:10px;cursor:pointer;font-size:12px}.emotion-review dt{font-weight:550;color:var(--ink)}.emotion-review dd{margin:3px 0 10px}.card-emotion{color:var(--accent)!important}
"""


SCRIPT = r"""
const DATA=JSON.parse(document.getElementById('page-data').textContent);
const board=DATA.board||null;
const keyFor=id=>'prism-feedback:'+DATA.feedback_namespace+':'+id;
function fitFrames(){document.querySelectorAll('.viewport').forEach(slot=>{const frame=slot.querySelector('.image-window');if(!frame)return;const aspect=Number(frame.dataset.aspect);const width=Math.min(slot.clientWidth,slot.clientHeight*aspect);frame.style.width=width+'px';frame.style.height=(width/aspect)+'px';});}
fitFrames();new ResizeObserver(fitFrames).observe(document.body);
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{const filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('.board-card').forEach(card=>card.hidden=filter!=='all'&&card.dataset.branch!==filter);document.querySelectorAll('.result-section').forEach(section=>section.hidden=section.querySelectorAll('.board-card:not([hidden])').length===0);document.getElementById('filter-count').textContent=document.querySelectorAll('.board-card:not([hidden])').length+' 张记录（含待审与诊断）';fitFrames();}));
document.querySelectorAll('.diagnostic-details').forEach(section=>section.addEventListener('toggle',fitFrames));
function getFeedback(id){try{return JSON.parse(localStorage.getItem(keyFor(id))||'null');}catch{return null;}}
function downloadFeedback(items){const value={schema_version:'prism.designer_feedback.v1',exported_at:new Date().toISOString(),feedback_namespace:DATA.feedback_namespace,authentication:'browser_entry_not_identity_verified',feedback:items};const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)+'\n'],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='prism-designer-feedback.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
const exportAll=document.getElementById('export-feedback');if(exportAll)exportAll.addEventListener('click',()=>downloadFeedback(DATA.board_ids.map(getFeedback).filter(Boolean)));
// file://页面不能依赖fetch读取JSON；按需载入同目录文本侧文件，再导出原始内容。
document.querySelectorAll('[data-json-download]').forEach(link=>link.addEventListener('click',async event=>{
 event.preventDefault();const name=link.dataset.jsonDownload,loader=document.createElement('script');loader.src=link.href+'.download.js';
 try{await new Promise((resolve,reject)=>{loader.onload=resolve;loader.onerror=reject;document.body.append(loader);});
  const content=window.__prismDownloads?.[name];if(typeof content!=='string')throw Error('下载内容未加载');
  const url=URL.createObjectURL(new Blob([content],{type:'application/json;charset=utf-8'}));const save=document.createElement('a');save.href=url;save.download=name;save.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch{window.open(link.href,'_blank','noopener');}finally{loader.remove();if(window.__prismDownloads)delete window.__prismDownloads[name];}
}));
if(board){
 const modal=document.getElementById('original-modal');let current=0;let returnFocus=null;
 const original=document.getElementById('original-image'),stage=document.getElementById('original-stage'),roi=document.getElementById('roi-outline');
 function fitOriginal(){const member=board.members[current];const wrap=document.querySelector('.original-wrap');const width=Math.min(wrap.clientWidth-36,(window.innerWidth<620?window.innerHeight*.49:window.innerHeight*.67)*member.width/member.height);stage.style.width=Math.max(100,width)+'px';}
 function link(parent,text,url){if(!url||!/^https?:\/\//i.test(url))return;const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=text;parent.append(a);}
 function showOriginal(index){
  current=(index+board.members.length)%board.members.length;const member=board.members[current];
  document.getElementById('modal-title').textContent=String(current+1).padStart(2,'0')+' / '+board.members.length+' · '+member.image_id;
  original.src=member.asset_url;original.alt=member.image_id+' 原图';const [x,y,w,h]=member.roi;
  Object.assign(roi.style,{left:x*100+'%',top:y*100+'%',width:w*100+'%',height:h*100+'%'});
  const evidence=document.getElementById('evidence-outline');evidence.hidden=!member.evidence_bbox||JSON.stringify(member.evidence_bbox)===JSON.stringify(member.roi);
  if(!evidence.hidden){const [ex,ey,ew,eh]=member.evidence_bbox;Object.assign(evidence.style,{left:ex*100+'%',top:ey*100+'%',width:ew*100+'%',height:eh*100+'%'});}
  document.getElementById('member-reason').textContent=member.reason||'已保留所选视窗及完整原图。';
  const viewLabel=member.display_scope==='representative_detail'?'代表性局部':member.display_scope==='whole_object'?'对象整体':'历史取景';
  document.getElementById('selected-view').textContent=[member.primary_subject?.identity,viewLabel,member.crop_reason].filter(Boolean).join(' · ');
  const quality=member.current_target_review||member.design_quality||{};document.getElementById('subject-quality').textContent=quality.design_evidence||quality.evidence||'';
  const emotion=document.getElementById('member-emotion');emotion.textContent=member.current_target_review?.emotion_reason||'';document.getElementById('member-emotion-section').hidden=!emotion.textContent;
  const list=document.getElementById('source-list');list.replaceChildren();
  member.sources.forEach(source=>{const item=document.createElement('div');item.className='source-item';const p=document.createElement('p');p.textContent=source.title||source.article_id;item.append(p);link(item,'阅读原文 ↗',source.article_url);list.append(item);});
  link(list,'查看图片原始链接 ↗',member.image_url);document.getElementById('source-image-id').textContent=member.image_id;
  const native=member.roi_native_dimensions_px;document.getElementById('source-image-dimensions').textContent='原图 '+member.width+' × '+member.height+' 像素；当前取景约 '+native.map(value=>Number(value.toFixed(1))).join(' × ')+' 原生像素。';
  let prior=document.getElementById('prior-view-feedback');
  if(!prior){prior=document.createElement('section');prior.id='prior-view-feedback';document.querySelector('.source-panel').append(prior);}
  prior.replaceChildren();const failures=member.prior_view_failures||[];prior.hidden=failures.length===0;
  if(failures.length){const heading=document.createElement('h3');heading.textContent='历史取景反馈（当时的判断）';prior.append(heading);failures.forEach(failure=>{const p=document.createElement('p');p.textContent=failure.reason;prior.append(p);});}
  modal.hidden=false;document.body.style.overflow='hidden';fitOriginal();document.getElementById('close-modal').focus();
 }
 function closeModal(){modal.hidden=true;document.body.style.overflow='';if(returnFocus)returnFocus.focus();}
 document.querySelectorAll('.tile-open').forEach(button=>button.addEventListener('click',()=>{returnFocus=button;showOriginal(Number(button.dataset.memberIndex));}));
 document.getElementById('close-modal').addEventListener('click',closeModal);modal.addEventListener('click',event=>{if(event.target===modal)closeModal();});document.getElementById('prev-image').addEventListener('click',()=>showOriginal(current-1));document.getElementById('next-image').addEventListener('click',()=>showOriginal(current+1));
 window.addEventListener('resize',()=>{if(!modal.hidden)fitOriginal();});document.addEventListener('keydown',event=>{if(modal.hidden)return;if(event.key==='Escape')closeModal();if(event.key==='ArrowRight')showOriginal(current+1);if(event.key==='ArrowLeft')showOriginal(current-1);if(event.key==='Tab'){const focusable=[...modal.querySelectorAll('button,a[href]')];const first=focusable[0],last=focusable[focusable.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}});
 const decision=document.getElementById('feedback-decision'),comment=document.getElementById('feedback-comment'),message=document.getElementById('feedback-message');const saved=getFeedback(board.board_id);if(saved){decision.value=saved.decision;comment.value=saved.comment;message.textContent='已载入本机保存的反馈';}
 function feedback(){return {board_id:board.board_id,cluster_id:board.cluster_id,branch:board.branch,decision:decision.value,comment:comment.value.trim(),image_sha256:board.members.map(m=>m.sha256),recorded_at:new Date().toISOString(),source:'explicit_browser_form'};}
 document.getElementById('save-feedback').addEventListener('click',()=>{try{localStorage.setItem(keyFor(board.board_id),JSON.stringify(feedback()));message.textContent='已保存到此浏览器';}catch{message.textContent='此浏览器不支持本机保存，可直接导出';}});document.getElementById('export-board-feedback').addEventListener('click',()=>downloadFeedback([feedback()]));
}
window.__prismReady=true;
"""


def frame(member: dict, prefix: str) -> str:
    x, y, width, height = member["roi"]
    aspect = member["width"] * width / (member["height"] * height)
    style = f"width:{100/width:.10f}%;height:{100/height:.10f}%;left:{-100*x/width:.10f}%;top:{-100*y/height:.10f}%"
    return (
        f'<div class="viewport"><div class="image-window" data-aspect="{aspect:.12f}">'
        f'<img src="{esc(prefix + member["asset_path"])}" alt="{esc(member["image_id"])} 的所选视窗" '
        f'style="{style}" data-original-sha="{member["sha256"]}"></div></div>'
    )


def page(title: str, body: str, data: dict) -> str:
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)} · 棱镜</title><style>{STYLE}{LAYOUT_STYLE}</style></head><body>{body}'
            f'<script id="page-data" type="application/json">{script_json(data)}</script>'
            f'<script>{SCRIPT}</script></body></html>')


def common_top(back: bool = False) -> str:
    return ('<div class="topline"><a class="brand" href="' + ('../index.html' if back else 'index.html') + '">'
            '<span class="brand-mark"></span>PRISM / 棱镜</a>'
            + ('<a class="quiet-link" href="../index.html">返回全部情绪板</a>' if back else '<span>DESIGN OBSERVATIONS · 2026</span>') + '</div>')


def branch_label(branch: str) -> str:
    """统一比较使用自己的显示名；不改原卡出处，也不借 CMF 名称兼容旧页面。"""
    return {"DESIGN": "统一设计情绪", "ID": "ID · 形态", "CMF": "CMF · 表面"}.get(branch, branch)


def emotion_html(board: dict) -> str:
    """仅展示独立板审归纳；观察标签不能冒充当前板已经成立的共同情绪。"""
    emotion = board.get("common_design_emotion")
    evidence = board.get("emotion_combination_evidence") or {}
    if not emotion or not evidence:
        return ""
    supported = any(row["key"] == "visual" and row["state"] == "passed" for row in board["validation_display"])
    label = "共同设计情绪" if supported else "设计情绪审阅 · 待核组合"
    details = ''.join(f'<dt>{label}</dt><dd>{esc(evidence.get(key) or "当前图像无法确认")}</dd>' for key, label in (
        ("form", "形态"), ("proportion", "比例"), ("color", "色彩"),
        ("material_texture", "材料质感"), ("detail_language", "细节语言")))
    relation = board.get("shared_design_relation") or {}
    relation_html = ""
    if relation:
        numbered = {member["unit_id"]: f"{index + 1:02}" for index, member in enumerate(board["members"])}
        pairs = ''.join(
            f'<dt>{esc(numbered.get(pair.get("unit_id_a"), "?"))} / {esc(numbered.get(pair.get("unit_id_b"), "?"))} 对照</dt>'
            f'<dd>支持：{esc("；".join(pair.get("shared_visible_support", [])))}<br>'
            f'最强差异：{esc(pair.get("strongest_difference"))}<br>判断：{esc(pair.get("coordination_reason"))}</dd>'
            for pair in board.get("pair_checks") or [])
        relation_html = (f'<p>具体共同关系：{esc(relation.get("statement"))}</p>'
                         f'<details><summary>查看关键反例对照</summary><dl>{pairs}</dl></details>')
    return (f'<section class="emotion-review"><h2>{label} · <span class="emotion-name">{esc(emotion)}</span></h2>'
            f'<p>{esc(evidence.get("overall_relation"))}</p>{relation_html}'
            f'<details><summary>查看组合依据</summary><dl>{details}</dl></details></section>')


def board_html(board: dict, namespace: str) -> str:
    members = board["members"]
    columns = 5 if len(members) == 10 else 3 if len(members) in {6, 9} else 4
    kind, label = board["review_display"]
    tiles = []
    for i, member in enumerate(members):
        caption = member["sources"][0].get("publisher") or member["image_id"] if member["sources"] else member["image_id"]
        if requires_relation_review(board):
            # 新盲审板保持同一真实页面与几何，但卡片不加来源方名来暗示品质。
            caption = member["image_id"]
        layout = member.get("layout_override", {})
        styles = ";".join(f"--{key}:{value}{'px' if key != 'tile-span' else ''}" for key, value in
                          (("tile-span", min(columns, layout.get("columns", 1))),
                           ("tile-height", layout.get("height", 198 if columns == 5 else 228)),
                           ("tile-mobile-height", layout.get("mobile_height", layout.get("height", 228))))) if layout else ""
        tiles.append(f'<figure class="tile{(" layout-override" if layout else "")}" data-unit-id="{esc(member["unit_id"])}" data-image-id="{esc(member["image_id"])}" style="{styles}"><button class="tile-open" type="button" data-member-index="{i}" aria-label="查看第{i+1}张原图及来源">'
                     + frame(member, "../")
                     + f'<span class="tile-caption"><span class="tile-number">{i+1:02}</span><span class="tile-name">{esc(caption)}</span><span class="tile-view" aria-hidden="true">↗</span></span></button></figure>')
    review = board.get("review") or {}
    review_summary = review.get("summary") or review.get("reason") or review.get("review_summary")
    note = f'<div class="review-note">{esc(review_summary)}</div>' if isinstance(review_summary, str) and review_summary else ''
    validation_labels = ''.join(f'<span class="status {row["state"]}" data-validation="{row["key"]}">{esc(row["label"])}</span>' for row in board["validation_display"])
    history_link = '<p class="section-note"><a class="quiet-link" href="../history.html">查看修改前的图板与历史状态 ↗</a></p>' if board.get("has_history") else ''
    body = f'<main class="shell board-page">{common_top(True)}<header class="board-header"><div class="hero"><p class="eyebrow">{esc(branch_label(board["branch"]))} · VISUAL STUDY</p><h1>{esc(board["title"])}</h1><p class="lead">{esc(profile_text(board.get("profile")))}</p><div class="board-meta"><span>{len(members)} 张图片</span><span class="status {kind}">{label}</span><span>待设计师确认</span></div><div class="board-meta validation-statuses">{validation_labels}</div></div></header>{emotion_html(board)}<section id="board-grid" class="board-grid cols-{columns}" style="--cols:{columns}" aria-label="情绪板图片">{"".join(tiles)}</section><p class="section-note">点击图片查看完整原图与来源。当前视窗由原图直接呈现；黄色框标记情绪板使用的范围。</p>{note}{history_link}'
    body += '<section class="feedback"><div><h2>记录你的判断</h2><p>反馈保存于本机浏览器，可导出交给团队。</p></div><div class="feedback-form"><label for="feedback-decision" class="eyebrow">这张情绪板</label><select id="feedback-decision"><option value="unreviewed">尚未确认</option><option value="approved">确认这张板</option><option value="needs_revision">需要调整</option><option value="comment_only">仅补充意见</option></select><textarea id="feedback-comment" aria-label="反馈说明" placeholder="哪些图片契合？哪些地方需要调整？"></textarea><div class="form-actions"><button type="button" class="primary-btn" id="save-feedback">保存反馈</button><button type="button" class="secondary-btn" id="export-board-feedback">导出反馈</button><span class="feedback-message" id="feedback-message" role="status"></span></div></div></section><footer><span>PRISM · 图片 DNA 聚类</span><span>图片版权归原作者所有</span></footer></main>'
    body += '<div id="original-modal" class="modal-backdrop" hidden><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><header class="modal-toolbar"><h2 id="modal-title">完整原图</h2><span class="modal-hint">← → 切换 · Esc 关闭</span><div><button type="button" class="icon-button" id="prev-image" aria-label="上一张">‹</button><button type="button" class="icon-button" id="next-image" aria-label="下一张">›</button><button type="button" class="icon-button" id="close-modal" aria-label="关闭原图">×</button></div></header><div class="modal-main"><div class="original-wrap"><div class="original-stage" id="original-stage"><img id="original-image" alt="完整原图"><div id="roi-outline" class="roi-outline"></div><div id="evidence-outline" class="evidence-outline" hidden></div></div></div><aside class="source-panel"><h3>所选对象与取景</h3><p id="selected-view"></p><p id="member-reason"></p><p>黄色实线框为图板实际展示范围，可为整体或代表性局部；青色虚线框仅标记局部事实位置。完整原图用于回查对象归属、设计情绪和取景是否遗漏冲突。</p><p id="subject-quality" class="subject-quality"></p><section id="member-emotion-section" hidden><h3>设计情绪依据</h3><p id="member-emotion"></p></section><h3>图片与来源</h3><p id="source-image-id"></p><div id="source-list"></div><h3>取景尺寸</h3><p id="source-image-dimensions"></p><p>尺寸用于定位可读性问题，不能代替视觉判断。</p></aside></div></section></div>'
    data_board = {**board, "members": [{**member, "asset_url": "../" + member["asset_path"]} for member in members]}
    return page(board["title"], body, {"board": data_board, "feedback_namespace": namespace})


# 窄屏固定回两列并限制跨度，不让桌面跨度产生隐式列或横向溢出；原比例由既有视窗函数保留。
LAYOUT_STYLE = """
.board-grid .tile.layout-override{grid-column:span var(--tile-span);align-self:start}
.board-grid .tile.layout-override .viewport{height:var(--tile-height)}
@media(min-width:701px) and (max-width:1000px){.board-grid .tile.layout-override{grid-column:span min(var(--tile-span),3)}}
@media(max-width:700px){.board-grid .tile.layout-override{grid-column:span 2}
.board-grid .tile.layout-override .viewport{height:var(--tile-mobile-height)}}
"""


def grouping_scope_html(summary: dict) -> str:
    """执行范围与成板通过分开；按真实分支覆盖解释未选向，不写全库已完成。"""
    mode = summary.get("mode")
    if mode not in {"full_catalogue", "priority_boards"}:
        return ""
    if mode == "priority_boards":
        target = summary.get("priority_goal", {}).get("target_boards")
        label = f"优先达标板模式 · 目标 {esc(target)} 张" if isinstance(target, int) else "优先达标板模式"
        note = "这里只登记候选形成与比较覆盖；目标是否达成须有当前板验收，不代表所有方向已评估。"
    else:
        label, note = "全目录探索模式", "有界路由与视觉窗口存在未评估残余；目录探索不保证全局召回或审美准确率。"
    items = []
    for branch, row in summary.get("branch_coverage", {}).items():
        if branch not in {"ID", "CMF", "DESIGN"}:
            continue
        count = lambda key: esc(str(row.get(key, "unknown")))
        coverage_label = "统一设计情绪" if branch == "DESIGN" else branch
        items.append(f'<li>{esc(coverage_label)}：输入 {count("input_cards")} 卡，DNA 路由比较 {count("route_compared_cards")} 卡，'
                     f'实际看图比较 {count("actually_visually_compared")} 卡，未选方向 {count("not_selected_direction")} 卡。</li>')
    if summary.get("inherited_source_coverage"):
        note += " 以下分支比较覆盖继承修订前运行；本次仅处理指定板，不是再次全库比较。"
    boundary = "原 ID／CMF 仅记录卡片出处；统一比较的实际范围以上述覆盖为准。" if summary.get("comparison_mode") == "unified" or "DESIGN" in summary.get("branch_coverage", {}) else "CMF 结果不替 ID 作证。"
    return f'<section class="section-note grouping-scope"><strong>{label}</strong><p>{note}</p><ul>{"".join(items)}</ul><p>卡数不是唯一图片数；未选向不等于低质量。{boundary}</p></section>'


def index_html(boards: list[dict], sample_count: int, namespace: str, downloads: list[str], observation_counts: dict, has_history: bool, emotion_counts: dict | None = None, grouping_summary: dict | None = None) -> str:
    supported = [board for board in boards if any(row["key"] == "visual" and row["state"] == "passed" for row in board["validation_display"])]
    branches = {board["branch"] for board in boards}
    unified_only = branches == {"DESIGN"} or (not branches and (grouping_summary or {}).get("comparison_mode") == "unified")
    visible_branches = [branch for branch in ("DESIGN", "ID", "CMF") if branch in branches]
    if not visible_branches:
        visible_branches = ["DESIGN"] if unified_only else ["ID", "CMF"]
    support_counts = ''.join(f'<span><b>{sum(board["branch"] == branch for board in supported)}</b>{esc(branch_label(branch))} · 视觉支持</span>' for branch in visible_branches)
    # 纯统一结果只显示一个入口；混合历史结果按真实分支筛选，不能把历史板改标统一。
    filters = '<button class="filter" data-filter="all" aria-pressed="true">统一设计情绪</button>' if unified_only else (
        '<button class="filter" data-filter="all" aria-pressed="true">全部</button>'
        + ''.join(f'<button class="filter" data-filter="{branch}" aria-pressed="false">{esc(branch_label(branch))}</button>' for branch in visible_branches))
    cards = {"usable": [], "candidate": [], "diagnostic": []}
    for board in sorted(boards, key=lambda item: item["review_display"][0] != "passed"):
        kind, label = board["review_display"]
        preview = ''.join(frame(member, "") for member in board["members"][:4])
        source_note = ' · 来源待核' if board["source_identity_pending"] else ''
        visual_passed = any(row["key"] == "visual" and row["state"] == "passed" for row in board["validation_display"])
        emotion_label = "共同设计情绪" if visual_passed else "设计情绪待核"
        emotion = f'<p class="card-emotion">{emotion_label} · {esc(board["common_design_emotion"])}</p>' if board.get("common_design_emotion") else ''
        group = "usable" if visual_passed else "diagnostic" if kind == "revision" else "candidate"
        cards[group].append(f'<a class="board-card" href="boards/{esc(board["board_id"])}.html" data-branch="{esc(board["branch"])}"><div class="mini-grid">{preview}</div><div class="card-body"><div class="card-top"><span class="branch">{esc(branch_label(board["branch"]))}</span><span class="status {kind}">{label}</span></div><h2>{esc(board["title"])}</h2>{emotion}<p>{esc(profile_text(board.get("profile")))}</p><div class="card-foot"><span>{len(board["members"])} 张图片{source_note} · 待设计师确认</span><span>查看情绪板 ↗</span></div></div></a>')
    sections = []
    for group, title, description in [
        ("usable", "本轮视觉支持图板", "当前所选对象与真实取景已获得其对应版本的独立视觉支持；来源及其他待核项在各板中单独标明，仍待设计师确认。"),
        ("candidate", "待审候选", "当前组合仍需独立审阅，已知的取景问题保留待复核提示。"),
        ("diagnostic", "诊断记录 · 未通过的组合", "这些组合没有通过当前视觉审阅，不计入上方结果数量；保留原图、问题依据和修改记录。"),
    ]:
        if cards[group]:
            content = f'<p class="section-description">{description}</p><div class="card-grid">{"".join(cards[group])}</div>'
            if group == "diagnostic":
                sections.append(f'<details class="result-section diagnostic-details" data-result-group="diagnostic"><summary>{title}（{len(cards[group])} 张）</summary>{content}</details>')
            else:
                sections.append(f'<section class="result-section" data-result-group="{group}"><h2 class="section-title">{title}</h2>{content}</section>')
    if not supported:
        sections.insert(0, '<p class="empty-supported">本轮暂未获得视觉审阅支持的图板。下方候选与诊断保留真实状态，尚不能当作已完成的设计结果。</p>')
    results_html = ''.join(sections) or '<p class="empty">当前尚无达到成板条件的簇，完整记录可在下方下载。</p>'
    download_names = {"image-ledger.json": f"全部 {sample_count} 张图片的去向", "sample.json": "原图样本与来源", "observations.json": "图片观察记录", "clusters.json": "完整簇、小簇与离群", "boards.json": "成板记录", "reviews.json": "独立审阅记录"}
    links = ''.join(f'<a href="data/{esc(name)}" data-json-download="{esc(name)}" download>{esc(download_names.get(name, name))} ↓</a>' for name in downloads)
    if has_history:
        links += '<a href="history.html">查看修改前的图板与历史状态 ↗</a>'
    progress = ''
    if isinstance(observation_counts.get("observed"), int):
        progress = f'<p class="section-note observation-progress">已有有效观察 {observation_counts["observed"]} / {sample_count} 张'
        if isinstance(observation_counts.get("pending"), int):
            progress += f' · {observation_counts["pending"]} 张待处理'
        if isinstance(observation_counts.get("failed"), int):
            progress += f' · {observation_counts["failed"]} 张处理失败'
        progress += '。</p>'
    if emotion_counts:
        # 单图技术完成与情绪观察充分是两个状态；这里不把任一计数当作成板通过。
        states = (("supported", "充分"), ("limited", "有限"), ("unresolved", "未决"),
                  ("missing", "缺失"), ("no_usable_subject", "无可用主体"))
        status_text = ' · '.join(f'{label} {emotion_counts.get(key, 0)} 张' for key, label in states)
        progress += f'<p class="section-note emotion-progress">情绪观察：{status_text}。<br>观察完成不等于情绪证据充分或图板通过。</p>'
    progress += grouping_scope_html(grouping_summary or {})
    body = f'<main class="shell">{common_top()}<header class="hero"><p class="eyebrow">IMAGE DNA / MOODBOARD EXPLORATION</p><h1>从可见关系，寻找设计共鸣。</h1><p class="lead">围绕主物品或同级设计对象，以整体或代表性局部呈现设计表达，结合配色、廓形比例、块面、线条、光学、纹理和细节共同传达的情绪。不同品类、不同材质可以同板，优先选择有可见设计依据的图片。</p><div class="counts"><span><b>{sample_count}</b>张样本</span>{support_counts}<span><b>{len(boards)-len(supported)}</b>待审 / 诊断</span></div>{progress}</header><nav class="toolbar" aria-label="情绪板筛选"><div class="filters">{filters}</div><span id="filter-count" class="quiet-link">{len(boards)} 张记录（含待审与诊断）</span></nav>{results_html}<p class="section-note">每张板保留所选视窗、完整原图和原文链接。AI 审阅与设计师判断分别记录；尚未成板的小簇及离群图片可在完整记录中查看。</p><button type="button" class="secondary-btn" id="export-feedback">导出我的全部反馈</button><section class="downloads" aria-label="下载完整数据">{links}</section><footer><span>PRISM · 图片 DNA 聚类</span><span>图片版权归原作者所有</span></footer></main>'
    return page("图片 DNA 情绪板", body, {"board_ids": [board["board_id"] for board in boards], "feedback_namespace": namespace})


def copy_history(source: Path, destination: Path) -> dict:
    """只接收本渲染器的离线交付目录，保留失败及旧版HTML的原字节和相对链接。"""
    manifest_path = source / "delivery-manifest.json"
    manifest = read(manifest_path)
    if manifest.get("schema_version") != "prism.dna_cluster_delivery.v1":
        raise ValueError(f"历史目录不是当前格式的离线交付：{source}")
    allowed_extensions = {".html", ".json", ".js", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"历史交付不接受符号链接：{path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if path.suffix.lower() not in allowed_extensions or relative.parts[0] not in {"index.html", "history.html", "delivery-manifest.json", "assets", "boards", "data", "history"}:
            raise ValueError(f"历史交付出现未约定文件，须明确处理：{relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        original_sha = digest(path)
        if digest(target) != original_sha:
            raise ValueError(f"历史文件复制不一致：{relative}")
        files.append({"path": relative.as_posix(), "sha256": original_sha})
    return {"source_manifest_ref": ref(manifest_path), "board_count": len(manifest["boards"]), "boards": manifest["boards"], "files": files}


def render(args: argparse.Namespace) -> dict:
    sample_path = args.sample or args.run_dir / "sample.json"
    observations_path = args.observations or args.run_dir / "observations.json"
    clusters_path = args.clusters or args.run_dir / "clusters.json"
    boards_path = args.boards or args.run_dir / "boards.json"
    reviews_path = args.reviews or args.run_dir / "reviews.json"
    required = {"sample.json": sample_path, "observations.json": observations_path, "clusters.json": clusters_path, "boards.json": boards_path}
    for path in required.values():
        if not path.is_file():
            raise FileNotFoundError(f"缺少当前输入：{path}")
    if args.reviews and not reviews_path.is_file():
        raise FileNotFoundError(f"指定的审阅文件不存在：{reviews_path}")
    if args.out.exists() and any(args.out.iterdir()):
        raise FileExistsError(f"请使用新的交付目录，避免覆盖已有板审证据：{args.out}")
    (args.out / "assets").mkdir(parents=True, exist_ok=True)
    (args.out / "boards").mkdir()
    (args.out / "data").mkdir()
    sample = read(sample_path)
    observation_data = read(observations_path)
    observation_units = {unit["unit_id"]: unit for unit in observation_data.get("units", [])}
    observation_counts = observation_data.get("counts", {})
    cluster_data = read(clusters_path)
    image_lookup = {image["sha256"]: image for image in sample["images"]}
    board_data = read(boards_path)
    source_boards = board_data if isinstance(board_data, list) else board_data["boards"]
    layout_path = getattr(args, "layout_overrides", None)
    overrides = validate_layout_overrides(read(layout_path) if layout_path else {},
        {m["unit_id"] for board in source_boards for m in board["members"]})
    if layout_path:
        required["layout-overrides.json"] = layout_path
    cards_compat = observation_data.get("schema_version") == "prism.design_cards_display_compat.v1"
    if cards_compat:
        # 新卡只做可追溯展示映射，不要求旧观察协议字段或冒充旧 R5 通过。
        for name, path in (("sample", sample_path), ("observations", observations_path)):
            if board_data.get("input_refs", {}).get(name) != ref(path):
                raise ValueError(f"LLM 板未绑定当前 {name} 字节")
    review_document = read(reviews_path) if reviews_path.is_file() else None
    if isinstance(review_document, dict) and review_document.get("boards_ref"):
        reviewed_sha = review_document["boards_ref"].get("sha256")
        finalization = board_data.get("finalization_inputs", {}) if isinstance(board_data, dict) else {}
        finalized_binding = (
            finalization.get("reviews", {}).get("sha256") == digest(reviews_path)
            and finalization.get("boards", {}).get("sha256") == reviewed_sha
        )
        if reviewed_sha != digest(boards_path) and not finalized_binding:
            raise ValueError("审阅不是针对当前图板或其明确绑定的finalize输入；不能给修改后的ROI沿用旧PASS")
    reviews = review_map(review_document)
    assets: dict[str, dict] = {}
    boards = []
    seen_board_ids = set()
    for source_board in source_boards:
        board = dict(source_board)
        board_id = board["board_id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", board_id) or ".." in board_id or board_id in seen_board_ids:
            raise ValueError(f"非法或重复board_id：{board_id}")
        seen_board_ids.add(board_id)
        if board["branch"] not in {"ID", "CMF", "DESIGN"}:
            raise ValueError(f"未知分支：{board['branch']}")
        members = []
        for source_member in board["members"]:
            member = dict(source_member)
            observation = observation_units.get(member.get("unit_id"), {})
            if cards_compat:
                if (member["sha256"] != observation.get("image_sha256")
                        or member["image_id"] != observation.get("image_id")
                        or member["roi"] != observation.get("display_bbox")
                        or member["display_bbox"] != observation.get("display_bbox")
                        or member["evidence_bbox"] != observation.get("evidence_bbox")):
                    raise ValueError("LLM 板对象/视窗与冻结卡不一致")
                member.update(primary_subject=observation["subject"], display_scope=observation["display_scope"],
                              crop_reason=observation["crop_reason"], design_quality=observation.get("design_quality"),
                              design_emotion=observation.get("design_emotion"))
            else:
                validate_display_scope(member, observation)
            image_sha = member["sha256"]
            if image_sha not in image_lookup:
                raise ValueError(f"成板图片不在冻结样本内：{image_sha}")
            original = image_lookup[image_sha]
            valid_ids = {original["image_id"]} | {a["image_id"] for a in original.get("aliases", [])}
            if member["image_id"] not in valid_ids:
                raise ValueError(f"image_id与SHA不一致：{member['image_id']}")
            path = Path(member.get("local_path") or original["local_path"])
            if image_sha not in assets:
                if digest(path) != image_sha:
                    raise ValueError(f"原图SHA不符：{path}")
                with Image.open(path) as image:
                    width, height = image.size
                    extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "AVIF": "avif"}.get(image.format, path.suffix.lstrip(".").lower())
                if not re.fullmatch(r"[a-z0-9]+", extension):
                    raise ValueError(f"无法安全表示图片格式：{path}")
                relative = f"assets/{image_sha}.{extension}"
                shutil.copyfile(path, args.out / relative)
                if digest(args.out / relative) != image_sha:
                    raise ValueError(f"复制后SHA不符：{relative}")
                assets[image_sha] = {"path": relative, "sha256": image_sha, "original_path": str(path.resolve()), "width": width, "height": height}
            asset = assets[image_sha]
            member.update({
                "asset_path": asset["path"], "width": asset["width"], "height": asset["height"],
                "roi": validate_roi(member.get("roi")), "sources": original["sources"],
                "image_url": original.get("image_url") or next((a.get("image_url") for a in original.get("aliases", []) if a.get("image_url")), None),
            })
            member.update(image_readability_dimensions(member["width"], member["height"], member["roi"]))
            if member["unit_id"] in overrides:
                member["layout_override"] = overrides[member["unit_id"]]
            members.append(member)
        board["members"] = members
        board["review"] = reviews.get(board_id)
        board["layout_binding"] = layout_binding(board, overrides)
        board["layout_identity"] = board["layout_binding"]["identity"]
        review_for_layout = board["review"] or {"provenance": board.get("review_provenance", {})}
        previous_layout_identity = review_layout_identity(review_for_layout)
        if ((board["layout_binding"]["overrides"] or previous_layout_identity is not None)
                and not review_matches_layout(review_for_layout, board["layout_binding"])):
            board["review"] = None
            board["current_layout_review_pending"] = True
            board["independent_review"] = False
            board["designer_approved"] = False
        if board["review"]:
            for field in ("common_design_emotion", "emotion_combination_evidence", "shared_design_relation",
                          "pair_checks", "least_consistent_unit_id"):
                board[field] = board["review"].get(field)
            checked_members = {(item["unit_id"], item["image_id"]): item for item in board["review"].get("members", [])}
            for member in members:
                checked = checked_members.get((member["unit_id"], member["image_id"]))
                if checked:
                    member["current_target_review"] = checked
        document_policy = review_document.get("review_policy_version") if isinstance(review_document, dict) else None
        board["review_display"], board["validation_display"] = board_validation(board, board["review"], document_policy)
        board["source_identity_pending"] = any(row["key"] == "source" and row["state"] != "passed" for row in board["validation_display"])
        board["has_history"] = bool(args.history_delivery)
        if board["review"]:
            current_review = board["review"]
            if isinstance(current_review.get("title"), str) and current_review["title"].strip():
                board["cluster_title"] = board.get("title")
                board["title"] = current_review["title"]
            if isinstance(current_review.get("common_relation"), str) and current_review["common_relation"].strip():
                board["cluster_profile"] = board.get("profile")
                board["profile"] = {"summary": current_review["common_relation"]}
        board["designer_confirmed"] = False
        boards.append(board)
    if reviews_path.is_file():
        required["reviews.json"] = reviews_path
    copied = []
    for name, source in required.items():
        shutil.copyfile(source, args.out / "data" / name)
        if digest(source) != digest(args.out / "data" / name):
            raise ValueError(f"交接JSON复制后不一致：{name}")
        copied.append(name)
    ledger = build_image_ledger(sample, observation_data, cluster_data, boards)
    write_json(args.out / "data/image-ledger.json", ledger)
    copied.insert(0, "image-ledger.json")
    for name in copied:
        content = (args.out / "data" / name).read_bytes().decode("utf-8")
        download_script = 'window.__prismDownloads=window.__prismDownloads||{};window.__prismDownloads[' + script_json(name) + ']=' + script_json(content) + ';\n'
        (args.out / "data" / f"{name}.download.js").write_text(download_script, encoding="utf-8")
    # 命名或审阅改变会形成新反馈命名空间，避免旧成员的人审结果被悄悄沿用。
    namespace = hashlib.sha256((digest(boards_path) + json.dumps(overrides, sort_keys=True)).encode()).hexdigest() if overrides else digest(boards_path)
    history = []
    for number, source in enumerate(args.history_delivery or [], 1):
        relative = f"history/version-{number:02}"
        entry = copy_history(source, args.out / relative)
        history.append({"path": relative, **entry})
    if history:
        entries = ''.join(f'<div class="review-note"><a class="quiet-link" href="{item["path"]}/index.html">历史版本 {number} · {item["board_count"]} 张图板 ↗</a><p>保留该版本的原始成员、取景和审阅状态。</p></div>' for number, item in enumerate(history, 1))
        history_body = f'<main class="shell">{common_top()}<header class="hero"><p class="eyebrow">VERSION HISTORY</p><h1>图板的修改记录</h1><p class="lead">旧版本保留当时的判断。请回到当前情绪板查看本轮最新结果。</p></header>{entries}<a class="quiet-link" href="index.html">返回当前情绪板</a></main>'
        (args.out / "history.html").write_text(page("图板修改记录", history_body, {"board_ids": [], "feedback_namespace": namespace}), encoding="utf-8")
    for board in boards:
        (args.out / "boards" / f'{board["board_id"]}.html').write_text(board_html(board, namespace), encoding="utf-8")
    emotion_summary = cluster_data.get("design_emotion_summary", {})
    grouping_summary = {**cluster_data.get("source_summary", {}), **cluster_data.get("summary", {})}
    (args.out / "index.html").write_text(index_html(boards, len(sample["images"]), namespace, copied, observation_counts, bool(history), emotion_summary.get("emotion_image_status_counts"), grouping_summary), encoding="utf-8")
    manifest = {
        "schema_version": "prism.dna_cluster_delivery.v1",
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "inputs": {name: ref(path) for name, path in required.items()},
        "renderer_ref": ref(Path(__file__)), "feedback_namespace": namespace,
        "index": {"path": "index.html", "sha256": digest(args.out / "index.html")},
        "image_ledger": {"path": "data/image-ledger.json", "sha256": digest(args.out / "data/image-ledger.json"), "image_count": ledger["image_count"]},
        "sample_count": len(sample["images"]), "observation_counts": observation_counts,
        "design_emotion_summary": emotion_summary,
        "board_count": len(boards), "assets": list(assets.values()),
        "history": history,
        "boards": [{
            "board_id": board["board_id"], "cluster_id": board["cluster_id"], "branch": board["branch"],
            "title": board["title"], "path": f'boards/{board["board_id"]}.html',
            "layout_identity": board["layout_identity"], "layout_binding": board["layout_binding"],
            "html_sha256": digest(args.out / "boards" / f'{board["board_id"]}.html'),
            "status": board.get("status"), "review_display": board["review_display"],
            "validation_display": board["validation_display"], "validation": board.get("validation"),
            "common_design_emotion": board.get("common_design_emotion"),
            "requires_concrete_relation_review": requires_relation_review(board, board.get("review")),
            "shared_design_relation": board.get("shared_design_relation"),
            "pair_checks": board.get("pair_checks"),
            "least_consistent_unit_id": board.get("least_consistent_unit_id"),
            "emotion_combination_evidence": board.get("emotion_combination_evidence"),
            "mechanical_checks": board.get("mechanical_checks"),
            "members": [{k: member.get(k) for k in ("unit_id", "image_id", "branch", "sha256", "asset_path", "width", "height", "roi", "display_bbox", "evidence_bbox", "primary_subject", "target_role", "display_scope", "crop_reason", "design_quality", "whole_appearance", "design_emotion", "design_emotion_provenance", "current_target_review", "original_dimensions_px", "roi_native_dimensions_px", "project_key", "project_state", "runway_state", "layout_override")} for member in board["members"]],
        } for board in boards],
        "original_bytes_preserved": True, "image_transformations": "CSS view-window only; source bytes unchanged",
        "readability_diagnostic_note": "原图与ROI尺寸为几何记录，未设置硬阈值，不代表图片清晰度或视觉审阅通过。",
        "offline_viewing": True, "model_calls": 0, "visual_pass_awarded_by_renderer": False,
        "designer_confirmation_awarded_by_renderer": False,
    }
    write_json(args.out / "delivery-manifest.json", manifest)
    return {"out": str(args.out.resolve()), "board_count": len(boards), "unique_original_images": len(assets), "sample_count": len(sample["images"]), "model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, epilog="示例：python render_delivery.py --run-dir data/result/dna_cluster_moodboard/sample500_20261009 --out /tmp/prism-delivery-v1。重新命名/审阅后请选择新输出目录，保留旧截图证据。")
    parser.add_argument("--run-dir", type=Path, required=True, help="包含sample/observations/clusters/boards JSON的运行目录")
    parser.add_argument("--out", type=Path, required=True, help="新的离线交付目录；拒绝覆盖非空目录")
    parser.add_argument("--sample", type=Path, help="覆盖样本JSON路径")
    parser.add_argument("--observations", type=Path, help="覆盖完整观察JSON路径")
    parser.add_argument("--clusters", type=Path, help="覆盖完整聚类JSON路径")
    parser.add_argument("--boards", type=Path, help="覆盖成板JSON路径")
    parser.add_argument("--reviews", type=Path, help="可选独立审阅JSON；默认读取运行目录reviews.json（若存在）")
    parser.add_argument("--layout-overrides", type=Path, help="JSON：unit_id → columns/height/mobile_height；仅改版面，新尺度不沿用旧板审")
    parser.add_argument("--history-delivery", type=Path, action="append", help="保留的旧版离线交付目录；可重复指定，复制原字节并提供修改前后入口")
    args = parser.parse_args()
    print(json.dumps(render(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
