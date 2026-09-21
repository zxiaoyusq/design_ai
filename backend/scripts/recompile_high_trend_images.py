"""按当前 Skill 的图片规则重编译既有高潜趋势结果，不重新调用模型。"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.high_trends.skill import PROJECT_ROOT, lean
from lean_images import selected_user_images


OUTPUT_FILES = (
    "manifest.json",
    "sources.json",
    "high_potential_trends.json",
    "high_potential_trends.jsonl",
    "report.md",
    "image_paths.md",
    "validation_report.json",
    "completion.json",
    "web_task.json",
)


def published_text(run, manifest, receipt):
    """有已确认的局部修订时复用修订稿，避免刷新图片时恢复旧综合正文。"""
    revision = manifest.get("output_revision")
    if not revision:
        return receipt["text"]
    relative = Path(revision["text_file"])
    path = (run / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(run.resolve()):
        raise ValueError("修订正文必须位于本任务目录内")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != revision["text_sha256"]:
        raise ValueError("修订正文与已登记版本不一致，不能发布")
    return raw.decode("utf-8")


def _frozen_users(manifest):
    """读取任务冻结的用户文件；内容变化时拒绝把新资料混入旧结论。"""
    source = manifest["inputs"]["users"]
    path = Path(source["path"]).resolve()
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError("用户数据已不同于任务冻结版本，不能重编译既有结果")
    document = json.loads(raw)
    users = document.get("users", [])
    limit = manifest.get("selection", {}).get("user_limit")
    selected = users if limit is None else users[:limit]
    expected = [str(value) for value in manifest.get("selection", {}).get("selected_user_ids", [])]
    actual = [str(user["id"]) for user in selected]
    if expected and actual != expected:
        raise ValueError("用户顺序或范围已变化，不能重编译既有结果")
    return selected, path.parent


def _refresh_trend_images(manifest, sources, root):
    """仅在趋势文本身份完全一致时，从现有索引回填后来下载的图片路径。"""
    selection = manifest.get("selection", {})
    refreshed = lean.build_sources(
        manifest["inputs"]["trends"]["path"],
        manifest["inputs"]["users"]["path"],
        root,
        selection.get("start_date"),
        selection.get("end_date"),
        selection.get("undated_policy", "exclude"),
        selection.get("user_limit"),
    )["sources"]
    identity_fields = (
        "id", "kind", "source_id", "fields", "release_time",
        "clustering_label", "source_file", "json_pointer",
    )
    refreshed_images = 0
    for alias, record in sources.items():
        if record.get("kind") != "trend":
            continue
        current = refreshed.get(alias)
        if current is None or any(record.get(key) != current.get(key) for key in identity_fields):
            raise ValueError(f"趋势 {alias} 的文本或身份已变化，不能只刷新图片路径")
        record["image_refs"] = current.get("image_refs", [])
        refreshed_images += sum(bool(ref.get("local_path")) for ref in record["image_refs"])
    return refreshed_images


def recompile(run, root=PROJECT_ROOT):
    """复用已接受的综合文字或明确登记的局部修订，不调用模型。"""
    run = Path(run).resolve()
    root = Path(root).resolve()
    if run.parent != root / "data/result/high_trend":
        raise ValueError("结果目录必须直接位于 data/result/high_trend")

    manifest = lean.read(run / "manifest.json")
    sources = lean.read(run / "sources.json")
    previous = lean.read(run / "high_potential_trends.json")
    synthesize_jobs = sorted((run / "requests").glob("synthesize-*.json"))
    if len(synthesize_jobs) != 1:
        raise ValueError("结果必须包含且只包含一个综合任务")
    job = lean.read(synthesize_jobs[0])
    receipt_path = run / "accepted" / synthesize_jobs[0].name
    if not receipt_path.is_file():
        raise ValueError("综合任务没有已接受的模型文字")
    receipt = lean.read(receipt_path)
    text = published_text(run, manifest, receipt)

    users, users_root = _frozen_users(manifest)
    inventory = selected_user_images(users, users_root)
    refreshed_trend_images = _refresh_trend_images(manifest, sources, root)
    manifest["user_image_inventory"] = inventory
    manifest["output_compiler_version"] = lean.VERSION

    backup = run / "pre_like_enjoy_filter"
    backup.mkdir(exist_ok=True)
    for name in OUTPUT_FILES:
        source = run / name
        destination = backup / name
        if source.is_file() and not destination.exists():
            shutil.copy2(source, destination)

    lean.write(run / "manifest.json", manifest)
    lean.write(run / "sources.json", sources)
    selected_sources = {source_id: sources[source_id] for source_id in job["source_ids"]}
    execution = dict(previous.get("execution") or {})
    execution["output_compiler_version"] = lean.VERSION
    if manifest.get("output_revision"):
        execution["output_revision"] = manifest["output_revision"]
    summary = lean.publish(
        run,
        manifest,
        selected_sources,
        text,
        job.get("aliases", {}),
        execution,
        image_sources=sources,
    )

    result = lean.read(run / "high_potential_trends.json")
    result["output_compiler_version"] = lean.VERSION
    lean.write(run / "high_potential_trends.json", result)
    if (run / "web_task.json").is_file():
        task = lean.read(run / "web_task.json")
        task["updated_at"] = lean.timestamp()
        revised = bool(manifest.get("output_revision"))
        task["message"] = "设计方向与核心来源关联已更新" if revised else "用户喜欢图片与已下载趋势图片均已更新"
        task.setdefault("events", []).append({
            "time": task["updated_at"],
            "stage": "result_refresh" if revised else "image_refresh",
            "message": ("复用已登记的局部修订，更新核心/背景来源与图片关联" if revised else
                        "用户图库仅保留 LIKE / ENJOY，并已回填下载完成的趋势图片路径"),
        })
        task["output_compiler_version"] = lean.VERSION
        lean.write(run / "web_task.json", task)

    return {
        "run": run.name,
        "status": summary["status"],
        "trends": len(result.get("trends", [])),
        "previous_user_images": len(previous.get("user_images", [])),
        "positive_user_images": len(result.get("user_images", [])),
        "refreshed_trend_images": refreshed_trend_images,
        "user_image_filter": result.get("user_image_filter"),
        "backup": str(backup),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    print(json.dumps(recompile(parser.parse_args().run), ensure_ascii=False, indent=2))
