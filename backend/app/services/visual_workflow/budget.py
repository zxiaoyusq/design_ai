"""视觉工作流的本地累计预算；只读回执和原子预留，不调用模型。"""

from __future__ import annotations

from collections import defaultdict
import fcntl
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone


class BudgetExceeded(RuntimeError):
    """预算不足属于停止条件，不能当作图片视觉不合格。"""


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _policy(run: Path) -> dict | None:
    path = run / "visual-budget-policy.json"
    if not path.exists():
        return None
    policy = _read(path)
    required = {"unique_originals", "view_candidates", "board_reviews", "visual_requests", "image_attachments"}
    limits = policy.get("limits", {})
    if set(limits) != required or any(type(v) is not int or v < 1 for v in limits.values()):
        raise ValueError("视觉预算必须明确给出五项正整数硬上限")
    return policy


def _directions(call_id: str, images: list[dict], payload: dict | None = None) -> list[str]:
    """图片身份优先；整板截图没有候选ID时，从实际请求方向回查。"""
    found = set(re.findall(r"\bH\d{3}\b", call_id))
    for item in images:
        cid = item.get("candidate_id") or ""
        match = re.match(r"^(H\d{3})-", cid)
        if match:
            found.add(match.group(1))
    if payload:
        did = payload.get("direction_id") or payload.get("family", {}).get("direction_id")
        if isinstance(did, str) and re.fullmatch(r"H\d{3}", did):
            found.add(did)
    return sorted(found)


def _charge(call_id: str, images: list[dict], payload: dict | None = None) -> dict:
    directions = _directions(call_id, images, payload)
    if not directions:
        raise ValueError("多模态请求必须能追溯到预算方向")
    originals = defaultdict(set)
    views = defaultdict(set)
    for item in images:
        if item.get("role") not in {"original", "actual_view", "actual_rendered_board", "calibration_reference"}:
            # 联系表等派生输入须先实现逐原图记账，不能用一张合成图绕开原图上限。
            raise ValueError("该图片角色尚未实现预算记账，不允许隐式发送")
        match = re.match(r"^(H\d{3})-", item.get("candidate_id") or "")
        bound = [match.group(1)] if match else directions
        for did in bound:
            if item.get("role") == "original":
                originals[did].add(item["sha256"])
            elif item.get("role") == "actual_view":
                if not item.get("candidate_id"):
                    raise ValueError("实际取景必须绑定候选图片身份")
                views[did].add(item["candidate_id"])
    return {"directions": directions,
            "originals": {did: sorted(v) for did, v in originals.items()},
            "views": {did: sorted(v) for did, v in views.items()},
            "image_attachments": len(images),
            "board_reviews": int(any(i.get("role") == "actual_rendered_board" for i in images))}


def _snapshot(run: Path, policy: dict) -> dict:
    accum = {}
    actual_reservations = set()
    identities = set()

    def add(charge, *, reserved=False, receipt=None):
        for did in charge["directions"]:
            row = accum.setdefault(did, {"originals": set(), "views": set(), "board_reviews": 0,
                                       "visual_requests": 0, "image_attachments": 0,
                                       "reserved_requests": 0,
                                       "tokens": {"input": 0, "output": 0, "unknown_calls": 0}})
            row["originals"].update(charge["originals"].get(did, []))
            row["views"].update(charge["views"].get(did, []))
            row["board_reviews"] += charge["board_reviews"]
            row["visual_requests"] += 1
            row["image_attachments"] += charge["image_attachments"]
            row["reserved_requests"] += int(reserved)
            if not reserved:
                usage = (receipt or {}).get("usage", {})
                row["tokens"]["input"] += usage.get("input_tokens", 0) or 0
                row["tokens"]["output"] += usage.get("output_tokens", 0) or 0
                if (not usage or not usage.get("usage_complete")
                        or usage.get("llm_request_count", 1) > usage.get("requests_with_usage", 1)):
                    row["tokens"]["unknown_calls"] += 1

    roots = [run, *[Path(p) for p in policy.get("history_run_paths", [])]]
    for root in dict.fromkeys(roots):
        if not root.exists():
            raise ValueError(f"历史预算目录不存在，不能按零消耗处理: {root}")
        for path in sorted((root / "calls").glob("*/request.json")):
            request = _read(path)
            images = request.get("images", [])
            if not images:
                continue
            identity = (request["call_id"], request.get("input_fingerprint"), request.get("started_at"))
            if identity in identities:
                continue
            identities.add(identity)
            if root.resolve() == run.resolve():
                actual_reservations.add((request["call_id"], request.get("input_fingerprint", "")))
            payload = None
            if not _directions(request["call_id"], images):
                # 与预约使用同一实际方向；不依赖所有调用名称恰好包含H编号。
                saved_directions = request.get("visual_budget_reservation", {}).get("charge", {}).get("directions", [])
                if len(saved_directions) == 1:
                    payload = {"direction_id": saved_directions[0]}
                elif (path.parent / "payload.json").exists():
                    payload = _read(path.parent / "payload.json")
            charge = _charge(request["call_id"], images, payload)
            receipt_path = path.parent / "receipt.json"
            add(charge, receipt=_read(receipt_path) if receipt_path.exists() else {})
    for path in sorted((run / "visual-budget/reservations").glob("*.json")):
        reservation = _read(path)
        # 只有当前运行同输入请求落盘才能替换预约；历史同名请求不能遮住新消费。
        if (reservation["call_id"], reservation["fingerprint"]) not in actual_reservations:
            add(reservation["charge"], reserved=True)
    result = {}
    for did, row in accum.items():
        result[did] = {"unique_originals": len(row["originals"]),
                       "original_sha256s": sorted(row["originals"]),
                       "view_candidates": len(row["views"]),
                       "view_candidate_ids": sorted(row["views"]),
                       **{k: v for k, v in row.items() if k not in ("originals", "views")}}
        result[did]["exhausted_limits"] = [k for k, limit in policy["limits"].items()
                                            if result[did][k] >= limit]
    return {"enabled": True, "limits": policy["limits"], "directions": result,
            "original_stages": policy.get("original_stages", [24, 40, 60]),
            "policy_ref": {"path": str(run / "visual-budget-policy.json"),
                           "sha256": hashlib.sha256((run / "visual-budget-policy.json").read_bytes()).hexdigest()}}


def budget_snapshot(run: Path) -> dict:
    """返回真实请求和在途预留的累计值；复用已完成回执不新增消费。"""
    run = Path(run)
    policy = _policy(run)
    if policy is None:
        return {"enabled": False, "limits": {}, "directions": {}}
    folder = run / "visual-budget"
    folder.mkdir(exist_ok=True)
    with (folder / "budget.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _snapshot(run, policy)


def reserve_visual_call(run: Path, call_id: str, payload: dict, images: list[dict], *, fingerprint: str = "") -> dict | None:
    """发送前串行预留全部计数，最多五并发也不能共同越过剩余额度。"""
    run = Path(run)
    policy = _policy(run)
    if policy is None or not images:
        return None
    charge = _charge(call_id, images, payload)
    folder = run / "visual-budget"
    reservations = folder / "reservations"
    reservations.mkdir(parents=True, exist_ok=True)
    reservation_path = reservations / (hashlib.sha256(call_id.encode()).hexdigest() + ".json")
    with (folder / "budget.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if reservation_path.exists():
            saved = _read(reservation_path)
            if saved["charge"] != charge or saved["fingerprint"] != fingerprint:
                raise ValueError("同名预算预留的实际输入改变")
            return saved
        snapshot = _snapshot(run, policy)
        violations = []
        for did in charge["directions"]:
            row = snapshot["directions"].get(did, {})
            projected = {"unique_originals": len(set(row.get("original_sha256s", [])) | set(charge["originals"].get(did, []))),
                         "view_candidates": len(set(row.get("view_candidate_ids", [])) | set(charge["views"].get(did, []))),
                         "board_reviews": row.get("board_reviews", 0) + charge["board_reviews"],
                         "visual_requests": row.get("visual_requests", 0) + 1,
                         "image_attachments": row.get("image_attachments", 0) + charge["image_attachments"]}
            # 历史可能已超新上限；只有新增该项消耗才阻断，仍允许复用已有ROI等结果。
            violations.extend(f"{did}.{k}={v}>{policy['limits'][k]}" for k, v in projected.items()
                              if v > policy["limits"][k] and v > row.get(k, 0))
        if violations:
            raise BudgetExceeded("awaiting_user_budget_decision: " + "; ".join(violations))
        saved = {"call_id": call_id, "fingerprint": fingerprint, "charge": charge,
                 "reserved_at": datetime.now(timezone.utc).isoformat(),
                 "policy_ref": snapshot["policy_ref"],
                 "status": "reserved_not_yet_sent"}
        reservation_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return saved
