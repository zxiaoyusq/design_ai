"""离线打包所有已保存 DNA 结果文本与索引，保留原字节、合并重复备份。"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "data/result/visual_workflow/h01_all13_20261005_expanded/inventory.json"
NEW_DNA = ROOT / "data/result/visual_completion/sol61_high_20261007/new-dna-index.json"
NAME = "全部图片DNA结果文本_20261009"
OUT = ROOT / "ref" / f"{NAME}.zip"


def read(path: Path) -> object:
    return json.loads(path.read_bytes())


def dump(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build() -> None:
    if OUT.exists():
        raise FileExistsError(f"目标已存在，拒绝覆盖：{OUT}")
    files: dict[str, dict] = {}
    by_hash: dict[str, str] = {}
    images: dict[str, dict] = {}
    current_images: set[str] = set()
    selected_refs: dict[str, str] = {}
    original_file_count = 0
    temp = OUT.with_suffix(".zip.building")
    if temp.exists():
        raise FileExistsError(f"构建文件已存在：{temp}")

    with zipfile.ZipFile(temp, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        def add(path: Path, category: str, expected_sha: str | None = None) -> str:
            """同字节备份只入包一次，来源路径全部记入旁表，不改原结果。"""
            nonlocal original_file_count
            path = path.resolve()
            relative = path.relative_to(ROOT).as_posix()
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if expected_sha is not None and digest != expected_sha:
                raise ValueError(f"冻结结果 SHA 不符：{relative}")
            json.loads(raw)
            if re.search(rb"data:image/[^;,\s]+;base64,[A-Za-z0-9+/]{100}", raw):
                raise ValueError(f"结果中存在内嵌图片：{relative}")
            original_file_count += 1
            if digest in by_hash:
                destination = by_hash[digest]
                if relative not in files[destination]["source_paths"]:
                    files[destination]["source_paths"].append(relative)
                return destination
            destination = "workspace/" + relative
            archive.writestr(NAME + "/" + destination, raw)
            by_hash[digest] = destination
            files[destination] = {
                "path": destination, "sha256": digest, "bytes": len(raw),
                "category": category, "source_paths": [relative],
            }
            return destination

        def result(path: Path, image_sha: str, category: str, metadata: dict,
                   expected_sha: str | None = None) -> str:
            destination = add(path, category, expected_sha)
            row = images.setdefault(image_sha, {
                "image_sha256": image_sha, "source_paths": [], "source_kinds": [], "dna_versions": [],
            })
            if not any(v["package_path"] == destination for v in row["dna_versions"]):
                row["dna_versions"].append({
                    "package_path": destination, "sha256": files[destination]["sha256"],
                    "category": category, **metadata,
                })
            return destination

        inventory = read(INVENTORY)
        for row in inventory:
            if not row["eligible_for_dna_recall"]:
                continue
            image_sha = row["image_sha256"]
            current_images.add(image_sha)
            for variant in row["dna_variants"]:
                ref = variant["result_ref"]
                metadata = {k: v for k, v in variant.items() if k != "result_ref"}
                destination = result(Path(ref["path"]), image_sha, "r5-results", metadata, ref["sha256"])
                if ref == row["selected_dna_ref"]:
                    selected_refs[image_sha] = destination
            if image_sha not in selected_refs:
                ref = row["selected_dna_ref"]
                selected_refs[image_sha] = result(Path(ref["path"]), image_sha, "r5-results", {}, ref["sha256"])
            images[image_sha]["source_paths"] = row["source_paths"]
            images[image_sha]["source_kinds"] = row["source_kinds"]
            images[image_sha]["r5_readiness"] = row["dna_readiness"]

        # 补提索引也登记失败请求，且后续新增结果可能晚于该索引；以已落盘结果为准。
        new_rows = {row["image_id"]: row for row in read(NEW_DNA)["rows"]}
        for path in sorted(NEW_DNA.parent.glob("new-dna/*/result.json")):
            data = read(path)
            record_path = path.parent / "record.json"
            record = read(record_path)
            image_sha = data["image_sha256"]
            if record["image_sha256"] != image_sha:
                raise ValueError(f"补提结果与绑定记录不是同一图片：{path}")
            current_images.add(image_sha)
            indexed = new_rows.get(path.parent.name, {})
            if indexed and (indexed["sha256"] != image_sha or "result_ref" not in indexed):
                raise ValueError(f"补提索引与实际结果冲突：{path}")
            destination = result(path, image_sha, "r5-results", {
                "model_id": data.get("model"), "reasoning_effort": data.get("reasoning_effort"),
                "status": data.get("status"), "executed_at": data.get("executed_at"),
            }, indexed.get("result_ref", {}).get("sha256"))
            selected_refs[image_sha] = destination
            images[image_sha]["source_paths"] = [record["asset"]["image_path"]]
            images[image_sha]["source_kinds"] = [record["asset"]["source_kind"]]
            add(record_path, "r5-provenance", indexed.get("record_ref", {}).get("sha256"))

        for path in sorted((ROOT / "data/result").glob("*_design_dna.json")):
            trace_path = ROOT / "data/result/.metadata" / path.name
            trace = read(trace_path)
            image_sha = trace["input_image"]["sha256"]
            result(path, image_sha, "historical-results", {
                "model_id": trace["model_id"], "prompt_version": trace.get("agent_prompt_version"),
                "completed_at": trace.get("completed_at"), "skill": trace.get("skill"),
            })
            row = images[image_sha]
            if trace["input_image"]["path"] not in row["source_paths"]:
                row["source_paths"].append(trace["input_image"]["path"])
            add(trace_path, "historical-provenance")
            view = ROOT / "data/result" / trace["business_view_file"]
            if view.is_file():
                add(view, "historical-business-views")

        for path in sorted((ROOT / "data/userreseach_data/liked_images_d02_results").glob("*.json")):
            data = read(path)
            if data.get("schema_version") != "prism_d02_candidate_v1":
                raise ValueError(f"未知的用研结果格式：{path}")
            result(path, data["source"]["image_sha256"], "historical-results", {
                "model_id": data["execution"].get("model_id"),
                "prompt_version": data["execution"].get("prompt_version"),
                "created_at": data.get("created_at"), "skill": data.get("skill"),
            })
            row = images[data["source"]["image_sha256"]]
            research = data["source"].get("research") or {}
            for source in research.get("source_paths", [research.get("source_path")]):
                if source and source not in row["source_paths"]:
                    row["source_paths"].append(source)
            if "research" not in row["source_kinds"]:
                row["source_kinds"].append("research")

        # 归档批次有旧版结果的重复副本；核对每份备份都已收录，补齐来源别名。
        for path in sorted((ROOT / "data/result/batches").glob("*/full_results/*.json")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest not in by_hash:
                raise ValueError(f"发现尚未索引的历史归档结果：{path}")
            add(path, "historical-results")

        for image_sha, destination in selected_refs.items():
            images[image_sha]["selected_r5_package_path"] = destination
        counts = dict(Counter(f["category"] for f in files.values()))
        version_count = sum(counts.get(k, 0) for k in ("r5-results", "historical-results"))
        summary = {
            "schema_version": "design_ai.all_dna_text_package.v1",
            "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "source_project": str(ROOT), "unique_images": len(images),
            "current_r5_images": len(current_images), "dna_result_version_files": version_count,
            "file_categories": counts, "original_result_bytes_preserved": True,
            "images_included": False, "model_calls": 0,
            "scope": "全部已保存R5全库结果、10月7日补提结果及历史多标签/R17结果；已落盘部分结果保留原状态",
            "counts_note": "图片按原图SHA256去重；同图多版本保留；同字节备份合并并保留来源别名。",
        }
        archive.writestr(NAME + "/indexes/dna-index.jsonl", "".join(
            json.dumps(images[key], ensure_ascii=False, separators=(",", ":")) + "\n" for key in sorted(images)
        ))
        archive.writestr(NAME + "/manifest.json", dump({**summary, "files": list(files.values())}))
        archive.writestr(NAME + "/README.txt", (
            f"全部图片 DNA 结果文本\n\n共 {len(images):,} 张不同图片，{version_count:,} 份 DNA 结果版本。\n"
            f"其中当前 R5 全库及后续补提覆盖 {len(current_images):,} 张；历史结果也已收录。\n\n"
            "workspace/：原始 UTF-8 JSON 结果、旧版页面业务视图及其追溯元数据，保持原文件字节。\n"
            "indexes/dna-index.jsonl：每行一张图片，按原图 SHA256 关联来源、模型与所有结果版本；"
            "selected_r5_package_path 指向全库冻结选择或后续补提结果。\n"
            "manifest.json：包内原始文件大小、SHA256、来源别名及统计。\n\n"
            "部分完成、pending、invalid 及困难项复核失败均按原结果保留；结果存在不等于所有字段已确认。\n"
            "本包仅包含结果文本和索引，不含原图、模型请求中的图片数据或流程工程文件；没有重新调用模型。\n"
        ).encode("utf-8"))

    with zipfile.ZipFile(temp) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC 校验失败")
        for entry in files.values():
            raw = archive.read(NAME + "/" + entry["path"])
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError(f"包内 SHA 校验失败：{entry['path']}")
        rows = archive.read(NAME + "/indexes/dna-index.jsonl").splitlines()
        if len(rows) != len(images):
            raise ValueError("DNA 索引行数不一致")
        present = set(archive.namelist())
        for raw in rows:
            row = json.loads(raw)
            if any(NAME + "/" + v["package_path"] not in present for v in row["dna_versions"]):
                raise ValueError("DNA 索引指向缺失结果")
    temp.replace(OUT)
    with OUT.open("rb") as stream:
        archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    summary.update(zip=str(OUT), bytes=OUT.stat().st_size, sha256=archive_sha,
                   archive_files=len(files) + 3, source_file_visits=original_file_count)
    OUT.with_suffix(".zip.manifest.json").write_bytes(dump(summary))
    OUT.with_suffix(".zip.sha256").write_text(archive_sha + "  " + OUT.name + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
