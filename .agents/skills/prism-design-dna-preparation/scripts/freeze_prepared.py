"""离线冻结已完成的逐图观察并建立内容寻址资产；不发模型请求、不补字段。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


VERSION = "prism.design_dna_prepared.v1"
ASSET_VERSION = "prism.design_dna_prepared_image.v1"
# 与已有观察的固定传输顺序一致，只无损解码用于出处核对，不重新做视觉解释。
FEATURE_ORDER = {
    "ID": "form.contour form.proportion form.volume form.symmetry structure.component_count "
          "structure.connection_visibility structure.line_density structure.layering detail.edge "
          "detail.detail_density detail.composition",
    "CMF": "color.hue color.chroma color.lightness color.color_count color.contrast "
           "material.appearance material.gloss material.reflection material.transparency "
           "texture.family texture.scale texture.density texture.regularity texture.direction "
           "texture.edge texture.representation",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def reference(path: Path, data: bytes | None = None) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path.read_bytes() if data is None else data)}


def read_ref(value: dict, checked: dict) -> bytes:
    """按实际字节核验来源；同一进程内重复引用只读一次，不能仅检查路径存在。"""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ValueError("缺少可核验的文件引用")
    path = Path(value["path"])
    if not path.is_absolute() or not isinstance(value.get("sha256"), str):
        raise ValueError("引用必须包含绝对路径与 SHA256")
    key = (str(path), value["sha256"])
    if key not in checked:
        data = path.read_bytes()
        if sha(data) != value["sha256"]:
            raise ValueError(f"来源 SHA256 不一致：{path}")
        checked[key] = data
    return checked[key]


def pointer(document: object, location: str) -> object:
    if not isinstance(location, str) or not location.startswith("/"):
        raise ValueError("缺少原回答 JSON pointer")
    try:
        current = document
        for part in location[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            current = current[int(key)] if isinstance(current, list) else current[key]
        return current
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"原回答指针不存在：{location}") from exc


def check_pointer_image(answer: dict, location: str, image_id: str) -> None:
    """批次回执可包含多图，仍须确认指针属于本图，防止借同批另一张的观察。"""
    parts = location.split("/") if isinstance(location, str) else []
    if len(parts) < 4 or parts[1] not in {"images", "revisions"}:
        raise ValueError("不支持的图像观察指针范围")
    owner = pointer(answer, "/" + "/".join(parts[1:3]))
    if not isinstance(owner, dict) or owner.get("image_id") != image_id:
        raise ValueError("原回答指针指向其他图片")


def check_call(answer_ref: dict, receipt_ref: dict, image: dict, checked: dict) -> tuple[dict, dict, dict]:
    answer = json.loads(read_ref(answer_ref, checked))
    receipt = json.loads(read_ref(receipt_ref, checked))
    if receipt.get("status") != "completed" or receipt.get("answer_ref") != answer_ref:
        raise ValueError("观察必须绑定已完成调用及其实际原回答")
    expected = (image["image_id"], image["sha256"])
    if expected not in {(item.get("candidate_id"), item.get("sha256")) for item in receipt.get("images", [])}:
        raise ValueError("调用回执未包含当前原图身份")
    if not receipt.get("requested_model") or not receipt.get("started_at"):
        raise ValueError("调用缺少真实请求模型或时间")
    datetime.fromisoformat(receipt["started_at"])
    prompt = read_ref(receipt.get("prompt_ref"), checked).decode()
    # 读取实际发送 Prompt 中的 payload，不以可单独改写的旁路版本标签代替。
    marker = "=== ACTUAL PAYLOAD ==="
    if marker not in prompt:
        raise ValueError("当前冻结入口仅接受带实际 payload 的可追溯观察调用")
    payload, _ = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())
    if not payload.get("prompt_version"):
        raise ValueError("实际请求缺少 Prompt 版本")
    return answer, receipt, payload


def decoded_features(raw: dict) -> dict:
    value = raw["features"]
    fields = FEATURE_ORDER[raw["branch"]].split()
    if isinstance(value, dict) and "f0" in value:
        if set(value) != {f"f{i}" for i in range(len(fields))}:
            raise ValueError("原回答短键字段不完整")
        value = [value[f"f{i}"] for i in range(len(fields))]
    if not isinstance(value, list):
        return value
    if len(value) != len(fields):
        raise ValueError("原回答特征数组长度不一致")
    output = {}
    for name, item in zip(fields, value, strict=True):
        block, field = name.split(".")
        if raw["branch"] == "CMF" and name == "color.contrast" and item == "moderate":
            item = "medium"  # 既有、有界的 wire alias，不把其他定性值归并。
        output.setdefault(block, {})[field] = item
    return output


def check_emotion(unit: dict, image: dict, checked: dict) -> dict | None:
    emotion = unit.get("design_emotion")
    if emotion is None:
        return None  # 未观察/待复核如实保留，不由冻结过程补成通过。
    proof = unit.get("design_emotion_provenance")
    if not isinstance(proof, dict):
        raise ValueError("已有情绪值缺少独立出处")
    answer, receipt, payload = check_call(proof.get("observation_ref"), proof.get("receipt_ref"), image, checked)
    check_pointer_image(answer, proof.get("observation_pointer"), image["image_id"])
    if pointer(answer, proof.get("observation_pointer")) != emotion:
        raise ValueError("情绪内容与原回答不一致")
    if (proof.get("image_id"), proof.get("image_sha256")) != (image["image_id"], image["sha256"]):
        raise ValueError("情绪出处借用了其他图片")
    subject = unit.get("primary_subject", {})
    if (proof.get("primary_subject_identity"), proof.get("primary_subject_bbox")) != (subject.get("identity"), subject.get("bbox")):
        raise ValueError("情绪出处借用了其他对象")
    if proof.get("prompt_version") != payload["prompt_version"]:
        raise ValueError("情绪 Prompt 版本与实际请求不一致")
    if proof.get("model_requested") != receipt["requested_model"] or proof.get("assessed_at") != receipt["started_at"]:
        raise ValueError("情绪模型或时间与实际回执不一致")
    return {"prompt_version": payload["prompt_version"], "model_requested": receipt["requested_model"],
            "reasoning_effort_requested": receipt.get("requested_reasoning_effort"),
            "model_reported": receipt.get("actual_model"), "receipt_ref": proof["receipt_ref"]}


def check_unit(unit: dict, image: dict, checked: dict) -> dict:
    if (unit.get("image_id"), unit.get("image_sha256")) != (image["image_id"], image["sha256"]):
        raise ValueError("单元与所属图片身份不一致")
    answer, receipt, payload = check_call(unit.get("observation_ref"), unit.get("receipt_ref"), image, checked)
    check_pointer_image(answer, unit.get("observation_pointer"), image["image_id"])
    raw = pointer(answer, unit.get("observation_pointer"))
    if not isinstance(raw, dict) or "features" not in raw:
        raise ValueError("单元未指向真实观察对象")
    for key, value in raw.items():
        if key in {"design_emotion", "features"}:
            continue
        if unit.get(key) != value:
            raise ValueError(f"单元 {unit['unit_id']} 的 {key} 与原观察不一致")
    if unit.get("features") != decoded_features(raw):
        raise ValueError("单元 DNA 与原回答不一致，须保留有效定点修订出处")
    # 版本从实际原回答的协议字段核对，旧结果不能仅改标签就升级为同级对象/局部协议。
    actual_version = ("v3" if "display_scope" in raw and "crop_reason" in raw else
                      "v2" if "primary_subject" in raw and "display_bbox" in raw else "v1")
    if unit.get("feature_definition_version") != f"prism.dna_cluster_observation.{actual_version}":
        raise ValueError("字段协议标签与原回答范围不一致")
    if unit.get("model_requested") != receipt["requested_model"]:
        raise ValueError("单元请求模型与真实回执不一致")
    emotion_call = check_emotion(unit, image, checked)
    return {"unit_id": unit["unit_id"], "feature_definition_version": unit["feature_definition_version"],
            "prompt_version": payload["prompt_version"], "model_requested": receipt["requested_model"],
            "reasoning_effort_requested": receipt.get("requested_reasoning_effort"),
            "model_reported": receipt.get("actual_model"), "receipt_ref": unit["receipt_ref"],
            "emotion_call": emotion_call,
            "scope": {key: unit.get(key) for key in ("branch", "target_role", "primary_subject", "bbox",
                      "evidence_bbox", "display_bbox", "display_scope", "crop_reason")}}


def indexed(rows: list[dict], key: str) -> dict:
    result = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError(f"{key} 缺失或重复")
        result[identity] = row
    return result


def validate_observations(observations: dict, sample: dict, checked: dict | None = None) -> list[dict]:
    """只验证封装/身份/出处完备，不将终态、缓存或 usable 当成视觉合格。"""
    checked = {} if checked is None else checked
    expected, actual = indexed(sample["images"], "image_id"), indexed(observations["images"], "image_id")
    if not expected or set(expected) != set(actual):
        raise ValueError("观察图片集合与指定样本不一致")
    units = [unit for row in observations["images"] for unit in row.get("units", [])]
    if indexed(units, "unit_id") != indexed(observations["units"], "unit_id"):
        raise ValueError("顶层 units 与逐图 units 不一致")
    assets = []
    for identity, source in expected.items():
        row = actual[identity]
        if row.get("sha256") != source.get("sha256"):
            raise ValueError("观察与样本 SHA256 不一致")
        read_ref({"path": source["local_path"], "sha256": source["sha256"]}, checked)
        if row.get("local_path") != source["local_path"]:
            raise ValueError("观察原图路径与冻结样本不一致")
        if row.get("status") not in {"observed", "failed"}:
            raise ValueError("尚有未终态图片；冻结阶段不自动补解析")
        if row["status"] == "failed":
            if row.get("units") or not row.get("observation_error"):
                raise ValueError("失败图片不得携带可用单元，须保留失败诊断")
            assets.append({"image_id": identity, "image_sha256": source["sha256"], "status": "failed", "asset": None})
            continue
        answer, receipt, payload = check_call(row.get("observation_ref"), row.get("receipt_ref"), row, checked)
        if row.get("observation_prompt_version") != payload["prompt_version"]:
            raise ValueError("图级 Prompt 版本与实际调用不一致")
        raw_images = [item for item in answer.get("images", []) if item.get("image_id") == identity]
        if len(raw_images) != 1:
            raise ValueError("图级原回答没有当前图片")
        if len(row.get("units", [])) != len(raw_images[0].get("units", [])):
            raise ValueError("图级观察遗漏或增添原单元，须显式记录新的观察而非静默删减")
        definitions = [check_unit(unit, row, checked) for unit in row.get("units", [])]
        asset = {"schema_version": ASSET_VERSION, "image_id": identity, "image_sha256": source["sha256"],
                 "observation_prompt_version": payload["prompt_version"],
                 "observation_model_requested": receipt["requested_model"], "unit_contracts": definitions,
                 "observation": row, "visual_approval_granted": False}
        assets.append({"image_id": identity, "image_sha256": source["sha256"], "status": "observed", "asset": asset})
    return assets


def freeze(observations_path: Path, sample_path: Path, out: Path, cache_dir: Path | None = None) -> dict:
    """新建不可覆盖的快照；共享缓存仅复用完全相同内容，不负责自动跳过未来模型调用。"""
    observations_path, sample_path, out = observations_path.resolve(), sample_path.resolve(), out.resolve()
    if out.exists():
        raise FileExistsError(f"输出目录必须不存在，拒绝覆盖：{out}")
    observation_bytes, sample_bytes = observations_path.read_bytes(), sample_path.read_bytes()
    observations, sample = json.loads(observation_bytes), json.loads(sample_bytes)
    checked = {}
    if observations.get("sample_ref"):
        if read_ref(observations["sample_ref"], checked) != sample_bytes:
            raise ValueError("观察声明的原样本与本次指定样本字节不一致")
    assets = validate_observations(observations, sample, checked)
    cache = cache_dir.resolve() if cache_dir else out / "assets"
    planned, index = {}, []
    for item in assets:
        asset = item.pop("asset")
        versions, prompts = [], []
        if asset is not None:
            data = encoded(asset)
            key = sha(data)
            path = cache / f"{key}.json"
            if path.exists() and path.read_bytes() != data:
                raise ValueError(f"内容寻址缓存冲突：{path}")
            planned[path] = data
            versions = sorted({contract["feature_definition_version"] for contract in asset["unit_contracts"]})
            prompts = sorted({asset["observation_prompt_version"],
                              *(contract["prompt_version"] for contract in asset["unit_contracts"])})
        else:
            data, key, path = None, None, None
        index.append({**item, "cache_key": key, "asset_ref": reference(path, data) if path else None,
                      "feature_definition_versions": versions, "prompt_versions": prompts,
                      "scope_status": "legacy_scope_preserved" if any(not value.endswith(".v3") for value in versions)
                                      else "source_scope_preserved"})
    counts = Counter(row["status"] for row in observations["images"])
    manifest = {"schema_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "sample_ref": reference(out / "sample.snapshot.json", sample_bytes),
                "observations_ref": reference(out / "observations.snapshot.json", observation_bytes),
                "source_sample_ref": reference(sample_path, sample_bytes),
                "source_observations_ref": reference(observations_path, observation_bytes),
                "terminal_counts": {"images": len(assets), "observed": counts["observed"], "failed": counts["failed"], "pending": 0},
                "extraction_completeness": "all_images_terminal_not_all_fields_known_or_all_images_successful",
                "asset_index": index, "model_calls": 0, "visual_approval_granted": False,
                "automatic_cross_run_model_skipping_implemented": False}
    # 全部输入与已存在缓存验证完成后才创建新交付；已有任何文件均不覆盖。
    out.mkdir(parents=True, exist_ok=False)
    cache.mkdir(parents=True, exist_ok=True)
    for path, data in planned.items():
        try:
            with path.open("xb") as handle:
                handle.write(data)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f"并发缓存内容冲突：{path}")
    for name, data in (("sample.snapshot.json", sample_bytes), ("observations.snapshot.json", observation_bytes),
                       ("prepared-manifest.json", encoded(manifest))):
        with (out / name).open("xb") as handle:
            handle.write(data)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    manifest = freeze(args.observations, args.sample, args.out, args.cache_dir)
    print(json.dumps({"manifest": str(args.out.resolve() / "prepared-manifest.json"),
                      "terminal_counts": manifest["terminal_counts"], "model_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
