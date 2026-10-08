"""Invented schema/algorithm fixtures, never a model result or real design conclusion."""
from copy import deepcopy

from .adapter import adapt_r5, producer
from .common import BASELINE, VERSION, digest, seal
from .scope import FLOW_SCHEMA, prepare_scope


def fixture_data():
    rows = {
        "fixture:chair": [("形态", "GEO-001", "圆弧"), ("形态", "STR-007", "环绕"),
            ("表面", "COL-006", "金色"), ("表面", "OPT-001", "金属外观"), ("表面", "OPT-002", "哑光"), ("表面", "TEX-002", "颗粒"),
            ("细边", "COL-006", "蓝色"), ("细边", "OPT-002", "高光")],
        "fixture:lamp": [("轮廓", "GEO-001", "圆弧"), ("轮廓", "STR-007", "环绕"),
            ("底座", "COL-006", "金色"), ("底座", "OPT-001", "金属外观"), ("底座", "OPT-002", "哑光"), ("底座", "TEX-002", "线")],
        "fixture:kettle": [("形态", "GEO-001", "折线"), ("形态", "STR-007", "直线"),
            ("壶嘴", "COL-006", "金色"), ("壶嘴", "OPT-001", "金属外观"), ("壶嘴", "OPT-002", "镜面外观"),
            ("把手", "COL-006", "黑色"), ("把手", "OPT-001", "塑料外观"), ("把手", "OPT-002", "哑光")],
    }
    assets, results, quality = [], {}, {}
    engine = producer()
    for iid, facts in rows.items():
        asset = {"image_id": iid, "sha256": digest(["explicitly_synthetic_image", iid]), "source_kind": "trend",
                 "source_id": "fixture:trend", "source_group": "fixture:only", "product_type": iid.split(":")[1]}
        assets.append(asset)
        local = [{"at": at, "p": pid, "v": value, "source": "fixture:P-" + iid, "path": "/fixture/" + str(i)} for i, (at, pid, value) in enumerate(facts)]
        index, excluded = engine.r3.normalize([{"feature": f, "source": f["source"]} for f in local])
        assert not excluded
        results[iid] = {"schema_version": "prism.sol_r5.portable_result.v1", "algorithm_version": BASELINE,
            "image_id": iid, "image_sha256": asset["sha256"] , "local_features": local, "features": index,
            "pending": [], "invalid": [], "decisions": [], "admission_adjustments": [],
            "source_binding": "named_flat_locations_no_boxes_or_object_tree", "model": "gpt-6-sol", "reasoning_effort": "low",
            "service_tier_requested": "default", "fast_mode": False, "status": "accepted_for_pilot",
            "fixture_only": True, "model_calls": 0, "not_a_model_output": True}
        uses = {}
        for name in ("id_reference", "cmf_reference"):
            uses[name] = {"status": "complete", "decision": "PASS", "reason": "SYNTHETIC protocol only",
                "evidence": [{"region": "合成声明区域", "feature": "silhouette" if name == "id_reference" else "color", "observation": "虚构观察，仅供测试"}],
                "limits": ["没有真实图像或视觉评估"], "response_ref": "fixture:quality", "selected_stage": "primary"}
        quality[iid] = {"schema_version": "prism.quality_selected.decision.v2", "algorithm_version": "fixture-only",
            "image_id": iid, "image_sha256": asset["sha256"], "source_kind": "trend", "global_decision": None,
            "status": "complete", "uses": uses, "fixture_only": True}
    prepared = seal({"schema_version": FLOW_SCHEMA, "stage": "H01_semantic", "dataset_mode": "synthetic_fixture",
        "asset_catalog": assets, "lanes": {"trend": [{"evidence_id": "fixture:T"}],
        "research": [{"evidence_id": "fixture:R"}, {"evidence_id": "fixture:N"}]}})
    candidates = seal({"schema_version": FLOW_SCHEMA, "stage": "H01_candidates", "prepared_digest": prepared["digest"],
        "directions": [{"direction_id": "fixture:D1", "title": "合成曲线与表面", "design_question": "仅测试两路协议",
                        "candidate_image_ids": list(rows), "trend_evidence_refs": ["fixture:T"], "research_evidence_refs": ["fixture:R"]}]})
    choices = [{"direction_id": "fixture:D1", "branches": ["ID", "CMF"]}]
    selection = seal({"schema_version": FLOW_SCHEMA, "stage": "designer_selection", "prepared_digest": prepared["digest"],
        "candidate_digest": candidates["digest"], "selection": choices, "confirmation": {
            "status": "confirmed", "actor_kind": "synthetic_fixture", "actor_id": "fixture", "source_ref": "fixture:not_user",
            "selection_digest": digest(choices), "candidate_digest": candidates["digest"]}})
    return {"fixture_only": True, "prepared": prepared, "candidates": candidates, "selection": selection,
            "assets": assets, "results": results, "quality": quality}


def build_case(branch="CMF", *, fixture=None, negative_audit=None):
    data = deepcopy(fixture) if fixture is not None else fixture_data()
    scope = prepare_scope(data["prepared"], data["candidates"], data["selection"], negative_audit=negative_audit or [])
    records = [adapt_r5(data["results"][a["image_id"]], a, data["quality"].get(a["image_id"])) for a in data["assets"]]
    first = records[0]
    def feature(pid, value):
        return {"parameter_id": pid, "allowed_values": [value], "observation_refs": [o["observation_id"] for o in first["observations"] if o["parameter_id"] == pid and o["value"] == value]}
    core = ([feature("GEO-001", "圆弧"), feature("STR-007", "环绕")] if branch == "ID"
            else [feature("COL-006", "金色"), feature("OPT-002", "哑光")])
    bindings = [{"image_id": r["image_id"], "quality_digest": digest(r["quality"]), "evidence_index": 0,
                 "locations": r["locations"], "reason": "Explicitly synthetic location-binding test, not a visual approval",
                 "acknowledged_limits": r["quality"]["uses"]["id_reference" if branch == "ID" else "cmf_reference"]["limits"]}
                for r in records if r["quality"] is not None and r["asset"]["source_kind"] == "trend"]
    request = {"schema_version": "prism.h02.id_style.v2" if branch == "ID" else "prism.h02.cmf_local.v2",
        "rule_version": VERSION, "request_id": "fixture:" + branch, "direction_id": "fixture:D1", "branch": branch,
        "selection_digest": scope["selection_digest"], "candidate_image_ids": [a["image_id"] for a in data["assets"]],
        "semantic_context": {"title": "合成曲线与表面", "design_question": "仅测试两路协议",
            "trend_evidence_refs": ["fixture:T"], "research_evidence_refs": ["fixture:R"], "unresolved": []},
        "negative_audit": deepcopy(negative_audit or []), "patterns": [{"pattern_id": "fixture:P1",
            "label": "合成ID形态" if branch == "ID" else "合成金色哑光位置", "rationale": "Protocol fixture only",
            "semantic_refs": ["fixture:T", "fixture:R"], "binding_scope": "image_index" if branch == "ID" else "declared_location",
            "core": core, "support": [], "negative_rules": [{"negative_id": n["negative_id"], "status": "pending",
                "reason": "Synthetic unresolved negative", "evidence_refs": n["evidence_refs"]} for n in negative_audit or []]}],
        "quality_bindings": bindings, "deferred_obligations": [{"status": "unfulfilled", "text": "Original-image design review"}]}
    return data, scope, request, records


def confirmation(request, scope):
    return {"status": "confirmed", "actor_kind": "synthetic_fixture", "actor_id": "fixture-only",
            "source_ref": "fixture:not_a_real_approval", "request_digest": digest(request), "selection_digest": scope["selection_digest"]}
