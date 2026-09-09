"""高潜趋势任务的文件持久化、串行执行、进度和可控图片访问。"""

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
import logging
from pathlib import Path
import re
from threading import RLock
from time import monotonic
from uuid import uuid4

from app.agents.design_trend_synthesizer import (
    AGENT_PROMPT_VERSION, agent_messages, prompt_prefix, run_trend_step, user_request_message,
)
from app.services.high_trends.skill import PROJECT_ROOT, SKILL_ROOT, lean, prepare
from app.services.high_trends.errors import error_detail
from app.services.llm.catalog import get_model

logger = logging.getLogger(__name__)
ACTIVE = {"queued", "running"}


def now():
    return datetime.now(UTC).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class HighTrendManager:
    """单进程只允许一个活动研究任务，避免昂贵调用并行挤占模型服务。"""

    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root)
        self.output = self.root / "data/result/high_trend"
        self._lock = RLock()
        self._active = set()
        # 重启后不自动重发有费用的请求；已保存笔记与产物可继续查看。
        for path in self.output.glob("web_*/web_task.json"):
            task = read(path)
            if task["status"] in ACTIVE:
                task.update(status="failed", stage="interrupted", updated_at=now(),
                            message="服务重启，任务已中断", error="已保存已有文件；未自动重新调用模型。")
                lean.write(path, task)

    def _folder(self, task_id):
        if not re.fullmatch(r"web_[a-f0-9]{32}", task_id):
            raise FileNotFoundError("任务不存在")
        folder = self.output / task_id
        if not (folder / "web_task.json").is_file():
            raise FileNotFoundError("任务不存在")
        return folder

    def catalog(self):
        trends = read(self.root / "data/trend_data/trends.json")["trends"]
        users = read(self.root / "data/userreseach_data/users.json")["users"]
        dates = sorted(str(x["release_time"])[:10] for x in trends if x.get("release_time"))
        return {"trend_count": len(trends), "user_count": len(users),
                "min_date": dates[0] if dates else None, "max_date": dates[-1] if dates else None,
                "undated_count": len(trends)-len(dates)}

    def preview(self, request):
        get_model(request.model_id)
        skill_text = (SKILL_ROOT / "SKILL.md").read_text()
        overhead = len(prompt_prefix(skill_text)) + len(user_request_message(request.prompt))
        manifest = prepare(self.root, request, self.output / "preview", dry_run=True,
                           overhead=overhead)
        manifest["plan"]["agent_context_chars_per_call"] = overhead
        return {"counts": manifest["counts"], "plan": manifest["plan"],
                "selection": manifest["selection"], "settings": manifest["settings"]}

    def create(self, request):
        get_model(request.model_id)
        with self._lock:
            if self._active:
                raise RuntimeError("已有高潜趋势任务正在运行，请等待完成后再启动。")
            task_id = "web_" + uuid4().hex
            folder = self.output / task_id
            skill_text = (SKILL_ROOT / "SKILL.md").read_text()
            manifest = prepare(self.root, request, folder, dry_run=False,
                               overhead=len(prompt_prefix(skill_text)) + len(user_request_message(request.prompt)))
            lean.atomic_text(folder / "agent_skill.md", skill_text)
            created = now()
            task = {"id": task_id, "status": "queued", "stage": "queued", "message": "资料已整理，等待开始",
                    "created_at": created, "updated_at": created, "request": request.model_dump(mode="json"),
                    "completed_jobs": 0, "total_jobs": manifest["plan"]["planned_calls"],
                    "counts": manifest["counts"], "plan": manifest["plan"], "events": [],
                    "skill_version": manifest["skill_version"], "agent_prompt_version": AGENT_PROMPT_VERSION,
                    "skill_sha256": sha256(skill_text.encode()).hexdigest(), "error": None}
            lean.write(folder / "web_task.json", task)
            self._active.add(task_id)
            return deepcopy(task)

    def _update(self, task_id, *, stage, message, **values):
        with self._lock:
            path = self._folder(task_id) / "web_task.json"
            task = read(path)
            task.update(values, stage=stage, message=message, updated_at=now())
            task["events"] = (task["events"] + [{"time": now(), "stage": stage, "message": message}])[-100:]
            lean.write(path, task)

    def list(self):
        with self._lock:
            tasks = [read(path) for path in self.output.glob("web_*/web_task.json")]
        return sorted(tasks, key=lambda x: x["created_at"], reverse=True)

    def _resume_info(self, folder, task):
        state = read(folder / "state.json")
        remaining = sum(v["status"] != "accepted" for v in state["jobs"].values())
        if state["jobs"] and not any(k.startswith("synthesize-") for k in state["jobs"]):
            remaining += 1
        return {"can_resume": task["status"] == "failed" and not (folder / "completion.json").exists(),
                "used_calls": len(state["calls"]), "remaining_jobs": remaining,
                "minimum_max_calls": len(state["calls"]) + remaining}

    def resume(self, task_id, request):
        """仅用户点击后将未完成步骤重新排队，已接受笔记和累计用量保持不变。"""
        with self._lock:
            if self._active:
                raise RuntimeError("已有高潜趋势任务正在运行，请等待完成后再继续。")
            folder = self._folder(task_id)
            task = read(folder / "web_task.json")
            info = self._resume_info(folder, task)
            if not info["can_resume"]:
                raise RuntimeError("当前任务不可继续；已完成结果不会重新调用模型。")
            maximum = request.max_calls if request.max_calls is not None else task["request"]["max_calls"]
            if maximum < info["minimum_max_calls"]:
                raise ValueError(f"已尝试{info['used_calls']}次，剩余预计{info['remaining_jobs']}步；累计调用上限至少需{info['minimum_max_calls']}次。")
            # 必须复用冻结的数据和Skill，不能把页面中新选的范围混入旧任务。
            skill_text = (folder / "agent_skill.md").read_text()
            if sha256(skill_text.encode()).hexdigest() != task["skill_sha256"]:
                raise ValueError("任务Skill快照发生变化，不能继续原任务。")
            read(folder / "sources.json")
            state = read(folder / "state.json")
            retry_ids = [jid for jid, value in state["jobs"].items() if value["status"] != "accepted"]
            for jid in retry_ids:
                read(folder / "requests" / f"{jid}.json")
                state["jobs"][jid]["status"] = "pending"
            for call in state["calls"]:
                if call["status"] == "running":
                    call["status"] = "interrupted"
            # 已解决失败不混入最终范围提示，完整失败历史仍保留在calls和error_history。
            resolved = {f"{jid}执行失败，保留其他已完成内容，未自动重试。" for jid in retry_ids}
            state["warnings"] = [w for w in state["warnings"] if w not in resolved]
            state["status"] = "ready"
            manifest = read(folder / "manifest.json")
            manifest["settings"]["max_calls"] = maximum
            lean.write(folder / "manifest.json", manifest)
            lean.write(folder / "state.json", state)
            task["request"]["max_calls"] = maximum
            lean.write(folder / "web_task.json", task)
            self._active.add(task_id)
            self._update(task_id, status="queued", stage="queued", error=None,
                         message=f"继续原任务，复用{task['completed_jobs']}个已完成步骤；累计调用上限{maximum}次")
            return self.get(task_id)

    def _safe_image(self, raw):
        if not raw:
            return None
        path = Path(raw)
        path = (path if path.is_absolute() else self.root / path).resolve()
        roots = [self.root / "data/trend_data", self.root / "data/userreseach_data"]
        # 只提供既有研究图片，拒绝越界路径、软链接逃逸及可执行网页内容。
        if (not any(path.is_relative_to(root.resolve()) for root in roots)
                or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
                or not path.is_file()):
            return None
        return path

    def _result(self, folder, *, excerpts=True):
        result = read(folder / "high_potential_trends.json")
        sources = read(folder / "sources.json") if excerpts else {}
        images = []
        for card in result["trends"] + result["user_research_gaps"]["directions"]:
            for ref in card["image_refs"]:
                index = len(images)
                path = self._safe_image(ref.get("absolute_path"))
                images.append(path)
                ref["url"] = f"/api/v1/high-trends/tasks/{folder.name}/images/{index}" if path else None
                ref["file_exists"] = bool(path)
            if excerpts:
                for source in card["source_records"]:
                    original = sources.get(source["short_id"], {}).get("fields", {})
                    source["excerpt"] = original.get("summary_zh", original.get("ai_analysis", original.get("ai_index", "")))
                    source["question"] = original.get("question", original.get("scenario"))
        return result, images

    def get(self, task_id):
        with self._lock:
            folder = self._folder(task_id)
            task = read(folder / "web_task.json")
            task["resume"] = self._resume_info(folder, task)
            if (folder / "high_potential_trends.json").is_file():
                task["result"] = self._result(folder)[0]
            if (folder / "performance_report.json").is_file():
                task["performance"] = read(folder / "performance_report.json")
            return task

    def image(self, task_id, index):
        folder = self._folder(task_id)
        _, images = self._result(folder, excerpts=False)
        if index < 0 or index >= len(images) or images[index] is None:
            raise FileNotFoundError("关联图片不存在或不在研究图片目录内")
        return images[index]

    def download(self, task_id, format):
        folder = self._folder(task_id)
        path = folder / ("report.md" if format == "markdown" else "high_potential_trends.json")
        if not path.is_file():
            raise FileNotFoundError("结果尚未生成")
        return path

    def _performance(self, folder):
        lean.performance(folder)
        report = read(folder / "performance_report.json")
        report.update(actual_model_calls=sum(c.get("telemetry", {}).get("llm_request_count", 0) for c in report["calls"]),
                      calls_with_unknown_request_count=sum("telemetry" not in c for c in report["calls"]),
                      stage_attempts=report["actual_adapter_calls"], engine="DeepAgents",
                      note="本任务 DeepAgents 单步调用统计；缺少 provider 用量的调用未估算，不含宿主对话。")
        lean.write(folder / "performance_report.json", report)

    def run(self, task_id):
        """由后台线程推进 Skill，阶段失败保留笔记，格式差异不触发额外模型调用。"""
        folder = self._folder(task_id)
        task = read(folder / "web_task.json")
        started = monotonic()
        failure = None
        jid = None
        stage = "preparing"
        try:
            self._update(task_id, status="running", stage="preparing", message="正在加载已冻结的资料与 Skill")
            skill_text = (folder / "agent_skill.md").read_text()
            while True:
                progress = lean.next_job(folder)
                if progress["completion"]:
                    break
                if not progress["pending"]:
                    raise RuntimeError("没有可执行阶段，也没有完成结果")
                jid = progress["pending"][0]
                job = read(folder / "requests" / f"{jid}.json")
                job["user_prompt"] = task["request"].get("prompt", "")
                stage = job["stage"]
                count = progress["accepted_jobs"]
                label = "综合设计趋势" if stage == "synthesize" else "归纳趋势资料" if job["source_ids"][0].startswith("T") else "归纳用户调研"
                self._update(task_id, stage=stage, message=f"{label} · 第 {count+1}/{task['total_jobs']} 步", completed_jobs=count)
                state = read(folder / "state.json")
                if len(state["calls"]) >= task["request"]["max_calls"]:
                    raise RuntimeError("已达到本次调用上限，未继续调用模型")
                call = {"job_id": jid, "stage": stage, "started_at": now(), "input_tokens": None,
                        "output_tokens": None, "seconds": 0, "status": "running"}
                state["calls"].append(call)
                state["jobs"][jid]["attempts"] += 1
                attempt = state["jobs"][jid]["attempts"]
                call["attempt"] = attempt
                lean.write(folder / "state.json", state)
                # 保存实际系统消息快照，便于复现绑定 Skill 后的输入及模型配置。
                trace = {
                    "messages": agent_messages(job, skill_text),
                    "model_profile": job["model_profile"], "agent_prompt_version": AGENT_PROMPT_VERSION,
                    "skill_sha256": task["skill_sha256"], "created_at": now()}
                trace_path = folder / "requests" / f"{jid}.agent.json"
                if not trace_path.exists():
                    lean.write(trace_path, trace)
                lean.write(folder / "requests" / f"{jid}.attempt-{attempt}.agent.json", trace)
                call_started = monotonic()
                try:
                    output = run_trend_step(task["request"]["model_id"], job, skill_text)
                    call.update({k: v for k, v in output.items() if k != "text"}, status="completed")
                    state["jobs"][jid]["truncated"] = output["truncated"]
                    if output["truncated"]:
                        state["warnings"].append(f"{jid}输出被截断，保留现有正文，未自动续写。")
                    state["calls"][-1] = call
                    lean.write(folder / "state.json", state)
                    if stage == "synthesize":
                        self._update(task_id, stage="publishing", message="正在整理设计方向、来源与关联图片")
                    lean.accept(folder, jid, output["text"], model=task["request"]["model_id"],
                                execution={"attempt": attempt, "engine": "DeepAgents", "agent_prompt_version": AGENT_PROMPT_VERSION,
                                           "user_prompt": job["user_prompt"]})
                except Exception as exc:
                    logger.exception("高潜趋势单步失败 task=%s job=%s", task_id, jid)
                    # 不把网关异常全文返回浏览器，避免泄露连接配置；没有用量保持未知。
                    state = read(folder / "state.json")
                    call.update(status="failed", seconds=monotonic()-call_started)
                    failure = {**error_detail(exc, job_id=jid, stage=stage, attempt=attempt, seconds=call["seconds"]), "time": now()}
                    call["error_detail"] = failure
                    if hasattr(exc, "trend_telemetry"):
                        call["telemetry"] = exc.trend_telemetry
                    state["calls"][-1] = call
                    state["jobs"][jid]["status"] = "failed"
                    state["warnings"].append(f"{jid}执行失败，保留其他已完成内容，未自动重试。")
                    lean.write(folder / "state.json", state)
                    self._update(task_id, stage=stage, message=f"{label}失败，已保留其他内容")
                    self._performance(folder)
                    raise RuntimeError("模型阶段失败，停止后续调用")
                self._performance(folder)
            completion = read(folder / "completion.json")
            status = {"complete": "completed", "partial": "partial", "empty": "empty"}[completion["status"]]
            self._performance(folder)
            state = read(folder / "state.json")
            self._update(task_id, status=status, stage="finished", message={
                "completed": "设计趋势已生成", "partial": "已生成部分结果，请查看范围提示", "empty": "本轮未生成可交付正文，请查看提示"}[status],
                completed_jobs=sum(x["status"] == "accepted" for x in state["jobs"].values()),
                elapsed_seconds=round(monotonic()-started, 2))
        except Exception as exc:
            logger.exception("高潜趋势流程失败 task=%s", task_id)
            failure = failure or {**error_detail(exc, job_id=jid, stage=stage), "time": now()}
            current = read(folder / "web_task.json")
            history = current.get("error_history", []) + [failure]
            lean.write(folder / "errors.json", history)
            self._update(task_id, status="failed", stage="failed", message="流程已停止，已有资料和笔记已保存",
                         error=failure["message"], error_detail=failure, error_history=history)
        finally:
            with self._lock:
                self._active.discard(task_id)


high_trend_manager = HighTrendManager()
