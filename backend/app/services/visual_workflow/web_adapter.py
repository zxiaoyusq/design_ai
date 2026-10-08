"""同事 v2 原生板的网页格式投影；不做选图、裁图或模型审阅。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.services.dna.storage import PROJECT_ROOT

VISUAL_RESULT_ROOT = PROJECT_ROOT / "data/result/visual_workflow"


def _validate_ref(reference: Any) -> None:
    """结构校验与内容校验分开，坏交接文件给出参数错误而非内部异常。"""
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str):
        raise ValueError("原生文件引用须包含 path 与 SHA256")
    if not Path(reference["path"]).is_absolute():
        raise ValueError("原生文件引用须为已保存的本机绝对路径")
    if not re.fullmatch(r"[a-f0-9]{64}", reference["sha256"]):
        raise ValueError("原生文件引用 SHA256 格式无效")


def _validate_display_inputs(board: Any, review: Any = None, *, require_refs: bool = False) -> None:
    """仅验证投影需要的结构，不替代原生数量、来源或视觉验收。"""
    if not isinstance(board, dict) or not isinstance(board.get("tiles"), list):
        raise ValueError("原生 board.tiles 必须是列表")
    ids = []
    for tile in board["tiles"]:
        if not isinstance(tile, dict) or not isinstance(tile.get("image_id"), str) or not tile["image_id"].strip():
            raise ValueError("原生 board.tiles 成员须包含非空 image_id")
        ids.append(tile["image_id"])
        if require_refs:
            for key in ("original_ref", "view_ref"):
                _validate_ref(tile.get(key))
    if len(ids) != len(set(ids)):
        raise ValueError("原生 board.tiles 的 image_id 不能重复")
    if require_refs:
        for key in ("brief_ref", "rendered_board_ref"):
            _validate_ref(board.get(key))
    if review is not None or require_refs:
        if not isinstance(review, dict) or not isinstance(review.get("slots"), list):
            raise ValueError("原生 review.slots 必须是列表")
        slot_ids = []
        for slot in review["slots"]:
            if not isinstance(slot, dict) or not isinstance(slot.get("image_id"), str) or not slot["image_id"].strip():
                raise ValueError("原生 review.slots 成员须包含非空 image_id")
            slot_ids.append(slot["image_id"])
        if len(slot_ids) != len(set(slot_ids)) or set(slot_ids) != set(ids):
            raise ValueError("原生 review.slots 须不重不漏覆盖当前板成员")


def _read_ref(reference: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """读取真实已保存文件并校验内容哈希，缺少原生来源不能补造。"""
    _validate_ref(reference)
    path = Path(reference["path"])
    path = path.resolve(strict=True)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError("原生交接引用 SHA256 不一致")
    return path, json.loads(data)


def load_handoff(run_path: str, *, root: Path | None = None) -> tuple[Path, dict[str, Any], Path, dict[str, Any], Path]:
    """浏览器只指定既有运行目录，固定读取 web-handoff.json，禁止任意文件路径。"""
    root = root or VISUAL_RESULT_ROOT
    folder = (root / run_path).resolve(strict=True)
    if not folder.is_relative_to(root.resolve()) or folder == root.resolve():
        raise ValueError("运行目录必须位于 visual_workflow 内")
    manifest = json.loads((folder / "web-handoff.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not all(key in manifest for key in ("board_ref", "review_ref")):
        raise ValueError("web-handoff.json 缺少 board_ref 或 review_ref")
    if "budget_exhausted" in manifest and type(manifest["budget_exhausted"]) is not bool:
        raise ValueError("budget_exhausted 必须是布尔值")
    board_path, board = _read_ref(manifest["board_ref"])
    review_path, review = _read_ref(manifest["review_ref"])
    _validate_display_inputs(board, review, require_refs=True)
    return folder, manifest, board_path, board, review_path


def project_board(board: dict[str, Any], gate: dict[str, Any], *, run_path: str, review: dict[str, Any] | None = None) -> dict[str, Any]:
    """纯展示：只有原生 gate 已真实完成且允许报告的板进入正式主题。"""
    _validate_display_inputs(board, review)
    tiles = board.get("tiles", [])
    title = board.get("title", "未命名方向")
    direction_id = board.get("direction_id") or board.get("board_id") or run_path
    eligible = gate.get("status") == "ready_for_user_feedback" and gate.get("eligible_to_report_visual_result") is True
    ids = [tile["image_id"] for tile in tiles]
    images = [{"id": tile["image_id"], "image_name": tile.get("label") or tile["image_id"],
               "preview_url": "/api/v1/moodboards/native-assets?" + urlencode({"run_path": run_path, "image_id": tile["image_id"]}),
               "created_at": board.get("created_at", ""), "category": board.get("branch"),
               "style_candidates": [], "summary": tile.get("scope"),
               "source_url": tile.get("source_url"), "source_project_id": tile.get("source_project_id"),
               "original_ref": tile.get("original_ref"), "view_ref": tile.get("view_ref")}
              for tile in tiles]
    clusters = [{"id": str(direction_id) + "-native", "name": title,
                 "description": "同事 v2 原生整板审阅结果；尚待用户反馈。", "result_ids": ids}] if eligible else []
    # 证据引用属于原生整板审阅，不把它伪装为新 DNA 提取或文本筛选结果。
    assignments = [{"result_id": slot["image_id"], "direction_id": direction_id if eligible else None,
                    "status": "matched" if eligible else "insufficient",
                    "reason": slot.get("reason") or "原生逐成员审阅，完整声明见证据引用。",
                    "evidence_paths": [f"/slots/{index}"], "evidence": [{"path": f"/slots/{index}", "value": slot}]}
                   for index, slot in enumerate((review or {}).get("slots", []))]
    return {"directions": [{"id": direction_id, "title": title, "description": board.get("description", ""),
                             "clusters": clusters,
                             "excluded": [] if eligible else [{"result_id": value, "reason": "原生验收尚未闭合，保留待处理"} for value in ids]}],
            "assignments": assignments, "images": images, "unmatched_result_ids": [] if eligible else ids,
            "trace": {"workflow": "colleague_v2_native", "native_gate": gate,
                      "web_projection_only": True, "new_model_calls": 0, "user_acceptance_confirmed": False}}


def preview_handoff(run_path: str) -> dict[str, Any]:
    """复放原生确定性验收，再转换现网页字段；不会发送模型请求。"""
    from app.services.visual_workflow.colleague_v2 import evaluate_board

    _, manifest, board_path, board, review_path = load_handoff(run_path)
    gate = evaluate_board(board_path, review_path, native_module=manifest.get("native_module"),
                          native_arguments=manifest.get("native_arguments"),
                          budget_exhausted=manifest.get("budget_exhausted", False))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    result = project_board(board, gate, run_path=run_path, review=review)
    result["trace"]["source_refs"] = {"board": manifest["board_ref"], "review": manifest["review_ref"]}
    return result


def native_asset(run_path: str, image_id: str) -> Path:
    """只显示当前原生板实际成员的真实裁图；绝不生成或增强证据。"""
    _, _, _, board, _ = load_handoff(run_path)
    tile = next((tile for tile in board.get("tiles", []) if tile.get("image_id") == image_id), None)
    if tile is None:
        raise FileNotFoundError("原生板中不存在该图片")
    reference = tile["view_ref"]
    path = Path(reference["path"]).resolve(strict=True)
    if not path.is_relative_to((PROJECT_ROOT / "data").resolve()):
        raise ValueError("网页素材仅支持工程 data 下的文件")
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError("实际裁图内容已改变")
    return path
