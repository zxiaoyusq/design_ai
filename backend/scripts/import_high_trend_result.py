"""把已完成的 Codex 宿主 Skill 结果登记到网页，不调用模型、不重跑研究。"""

import argparse
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.high_trends.skill import PROJECT_ROOT, SKILL_ROOT, lean


def import_result(run, root=PROJECT_ROOT):
    """只登记结果根目录下已完成的 web_* 任务；旧登记不可覆盖，支持幂等读取。"""
    import re
    run, root = Path(run).resolve(), Path(root).resolve()
    if run.parent != root / "data/result/high_trend" or not re.fullmatch(r"web_[a-f0-9]{32}", run.name):
        raise ValueError("导入目录必须为 data/result/high_trend/web_<32位编号>")
    if (run / "web_task.json").exists():
        return lean.read(run / "web_task.json")
    manifest = lean.read(run / "manifest.json")
    completion = lean.read(run / "completion.json")
    result = lean.read(run / "high_potential_trends.json")
    state = lean.read(run / "state.json")
    if completion["status"] not in {"complete", "partial", "empty"} or any(
        job["status"] == "pending" for job in state["jobs"].values()
    ):
        raise ValueError("研究尚未结束，不登记为网页结果")
    if not (run / "report.md").is_file() or not (run / "sources.json").is_file():
        raise ValueError("研究报告或来源索引缺失")
    model = (manifest.get("model_profile") or {}).get("model") or "Codex host"
    selected = manifest["selection"]
    original = root / "data/trend_data/article_table_2/trends.json"
    dataset = "article_table_2_selected_5" if Path(manifest["inputs"]["trends"]["path"]).resolve() == original else "original"
    timestamp = datetime.now(UTC).isoformat()
    skill_text = (run / "agent_skill.md").read_text() if (run / "agent_skill.md").exists() else (SKILL_ROOT / "SKILL.md").read_text()
    lean.atomic_text(run / "agent_skill.md", skill_text)
    receipts = [lean.read(p) for p in sorted((run / "accepted").glob("*.json"))]
    performance = lean.read(run / "performance_report.json")
    # 宿主步骤数可数，Codex 内部请求/Token 不可由 Skill 推算，不能用适配器的零用量冒充。
    performance.update(engine="Codex host", model=model, actual_model_calls=None,
                       input_tokens_known=None, output_tokens_known=None, call_seconds=None,
                       host_analysis_steps=len(receipts), stage_attempts=len(receipts),
                       usage_available=False, note="由当前 Codex GPT-6 Astra 执行；记录归纳步骤数，未获取宿主精确 token 或内部请求次数；外部模型 API 调用为 0。")
    lean.write(run / "performance_report.json", performance)
    task = {"id": run.name, "status": {"complete": "completed", "partial": "partial", "empty": "empty"}[completion["status"]],
            "stage": "finished", "message": "Codex GPT-6 Astra 研究结果已导入" if not result.get("partial") else "Codex 研究结果已导入，请查看范围提示",
            "created_at": manifest["created_at"], "updated_at": timestamp,
            "request": {"start_date": selected.get("start_date") or "1900-01-01",
                        "end_date": selected.get("end_date") or timestamp[:10], "all_dates": not selected.get("start_date") and not selected.get("end_date"),
                        "dataset": dataset, "model_id": model, "max_calls": manifest["settings"]["max_calls"],
                        "user_scope": "all", "user_limit": None,
                        "prompt": "按指定两个文件全量分析，以 clustering_label 聚合趋势大类，结合用研提炼高潜方向并展示用户本地图片。"},
            "scope": {"user_limit": selected.get("user_limit"), "origin": "option", "label": "指定文件中的全部用户", "note": "Codex 宿主执行，使用冻结的指定数据文件。"},
            "selection": selected, "source_inputs": manifest["inputs"], "counts": manifest["counts"],
            "plan": manifest["plan"], "completed_jobs": len(receipts), "total_jobs": len(state["jobs"]),
            "skill_version": manifest["skill_version"], "agent_prompt_version": f"codex-host-skill-{manifest['skill_version']}",
            "skill_sha256": sha256(skill_text.encode()).hexdigest(), "error": None,
            "events": [{"time": receipt["accepted_at"], "stage": "host_analysis", "message": f"Codex 已完成资料步骤 {index}"}
                       for index, receipt in enumerate(receipts, 1)] + [{"time": timestamp, "stage": "finished", "message": "研究报告、分类与用户图片已导入网页"}]}
    lean.write(run / "web_task.json", task)
    return task


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    print(import_result(args.run)["id"])
