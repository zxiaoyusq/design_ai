"""全目录图片盘点及来源补录：元数据失败不阻断原图进入人工待选库。"""

from hashlib import sha256
import json
from pathlib import Path


def scan_inventory(root, suffixes):
    candidates, metadata_files, warnings = {}, [], []
    root = Path(root).resolve()
    for kind, relative in (("trend", "data/trend_data"), ("user", "data/userreseach_data")):
        directory = root / relative
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in suffixes or not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(directory.resolve()):
                continue
            candidates.setdefault(str(resolved), []).append({
                "source_kind": kind, "image_id": None, "source_record_id": None,
                "source_aliases": [], "source_title": None, "user_id": None, "code": None,
                "emotion_tag": None, "original_path": str(path.relative_to(root)),
                "original_absolute_path": str(resolved), "source_file": None, "json_pointer": None,
                "urls": [], "direction_id": None, "direction_title": None,
                "association_level": "directory_inventory",
            })

        def walk(value, pointer, context, document_path, base):
            if isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{pointer}/{index}", context, document_path, base)
                return
            if not isinstance(value, dict):
                return
            current = dict(context)
            if "title_zh" in value:
                current.update(source_title=value.get("title_zh"), source_record_id=f"trend:{value.get('id')}")
            if "profile" in value and "id" in value:
                current.update(user_id=str(value["id"]))
            if "user_id" in value:
                current["user_id"] = str(value["user_id"])
            if "question" in value or "scenario" in value:
                current.update(source_title=value.get("question") or value.get("scenario"),
                               source_record_id=f"user:{current.get('user_id', '')}:record:{value.get('id', '')}")
            local_values = []
            if isinstance(value.get("local_path"), str):
                local_values.append((value["local_path"], value.get("image_id") or value.get("id"), pointer + "/local_path"))
            if isinstance(value.get("local_paths"), list):
                ids = value.get("image_ids", [])
                local_values.extend((local, ids[i] if i < len(ids) else value.get("image_id"), f"{pointer}/local_paths/{i}")
                                    for i, local in enumerate(value["local_paths"]) if isinstance(local, str))
            for local, image_id, location in local_values:
                if not local.strip():
                    continue
                path = Path(local)
                resolved = (path if path.is_absolute() else base / path).resolve()
                key = str(resolved)
                if key not in candidates:
                    continue
                tags = value.get("emotion_tag") or value.get("emotion_tags")
                if isinstance(tags, list):
                    tags = " / ".join(str(tag) for tag in tags)
                codes = value.get("reference_codes", [])
                code = value.get("ref_pic_code") or value.get("code") or (", ".join(codes) if codes else None)
                origin = {**candidates[key][0], **current,
                          "image_id": str(image_id) if image_id is not None else None,
                          "code": code, "emotion_tag": tags, "original_path": local,
                          "source_file": str(document_path), "json_pointer": location,
                          "urls": sorted({value[k] for k in ("url", "download_url", "resolved_url", "image_url")
                                          if isinstance(value.get(k), str) and value[k].startswith(("http://", "https://"))}),
                          "association_level": "declared_local_path"}
                # 全局图片表的态度可来自多个用户，不把聚合 ENJOY 当成某个用户的个人喜好。
                if isinstance(value.get("responses"), list):
                    origin["feedback"] = value["responses"]
                    origin["enjoy_count"] = value.get("enjoy_count")
                    origin["dislike_count"] = value.get("dislike_count")
                if origin not in candidates[key]:
                    candidates[key].append(origin)
            for name, child in value.items():
                if isinstance(child, (list, dict)):
                    escaped = name.replace("~", "~0").replace("/", "~1")
                    walk(child, f"{pointer}/{escaped}", current, document_path, base)

        for document_path in sorted(directory.rglob("*.json")):
            if "backups" in document_path.relative_to(directory).parts or not document_path.resolve().is_relative_to(directory.resolve()):
                continue
            try:
                raw = document_path.read_bytes()
                document = json.loads(raw)
                metadata_files.append({"path": str(document_path), "sha256": sha256(raw).hexdigest()})
                base_value = document.get("local_path_base", ".") if isinstance(document, dict) else "."
                base = document_path.parent / base_value if isinstance(base_value, str) else document_path.parent
                walk(document, "", {}, document_path, base)
            except (OSError, ValueError) as exc:
                warnings.append({"source_file": str(document_path), "message": f"元数据未读取：{exc}；目录内图片仍进入待选库。"})
    # 已找到具体来源时无需再显示同一路径的空记录；没有元数据的文件仍可选择并追溯路径。
    for key, origins in candidates.items():
        described = [origin for origin in origins if origin["association_level"] != "directory_inventory"]
        if described:
            candidates[key] = described
    return candidates, metadata_files, warnings
