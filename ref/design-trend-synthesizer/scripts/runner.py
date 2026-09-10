"""可移植文本模型宿主：适配器自行提供，模型并行调用，状态与接收串行写入。"""

from __future__ import annotations

import argparse
import hashlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import json
import math
from pathlib import Path
import random
import signal
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True

import core
from contracts import validate_response
import workflow

VERSION = core.VERSION
TRANSPORT_ERRORS = {"overload", "rate_limit", "timeout", "transport"}
ADAPTER_ERRORS = TRANSPORT_ERRORS | {"authentication", "permanent"}


def strict_json(text):
    """拒绝重复键和非标准常数，不能修补模型输出使其通过契约。"""
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"JSON 重复字段：{key}")
            value[key] = item
        return value

    def constant(value):
        raise ValueError(f"JSON 非法常数：{value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


@contextmanager
def run_lock(path):
    """锁随进程退出释放；Windows 与 POSIX 均使用标准库文件锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if sys.platform == "win32":
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("已有 runner 正在写入该运行目录") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("已有 runner 正在写入该运行目录") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def invoke_adapter(command, request_path, result_path):
    """源文本只进请求文件；适配器始终用参数数组执行，不经过 shell。"""
    argv = [*command, "--request", str(request_path), "--result", str(result_path)]
    try:
        completed = subprocess.run(argv, shell=False, capture_output=True, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "error", "category": "timeout", "message": "适配器超过 180 秒未结束"}
    except OSError as exc:
        return {"status": "error", "category": "permanent", "message": f"适配器无法启动：{type(exc).__name__}"}
    if completed.returncode != 0:
        # 不回显任意 stderr，避免适配器无意把凭据打印到运行日志。
        return {"status": "error", "category": "permanent", "message": f"适配器退出码 {completed.returncode}"}
    if not result_path.is_file():
        return {"status": "error", "category": "permanent", "message": "适配器没有写入结果文件"}
    return None


class Runner:
    """协调器独占状态写入；工作线程仅运行外部适配器。"""

    def __init__(self, run, command, concurrency=2, max_jobs=None, *,
                 record_repair_rounds=2,
                 clock=time.time, sleep=time.sleep, jitter=random.random,
                 adapter=invoke_adapter, workflow_api=workflow):
        self.run = Path(run).resolve()
        self.command = command
        self.concurrency = concurrency
        self.max_jobs = max_jobs
        if type(record_repair_rounds) is not int or not 0 <= record_repair_rounds <= 2:
            raise ValueError("record-repair-rounds 须为 0–2；只补齐可复用批次中的缺口")
        self.record_repair_rounds = record_repair_rounds
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.adapter, self.workflow = adapter, workflow_api
        self.stop = threading.Event()
        self.root = self.run / "runner"
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = core.read(self.run / "manifest.json")
        if self.manifest.get("skill_version") != VERSION:
            raise ValueError(f"runner 仅接受 {VERSION} 运行，不能混用旧版本任务")
        self.profile = self.manifest.get("model_profile")
        if (not isinstance(self.profile, dict) or not isinstance(self.profile.get("model"), str)
                or not self.profile["model"].strip() or not isinstance(self.profile.get("parameters"), dict)):
            raise ValueError("runner 要求 manifest.model_profile 明确指定 model 和 parameters")
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) or "\0" in arg for arg in command):
            raise ValueError("adapter-command-json 必须是非空字符串参数数组")
        if type(concurrency) is not int or not 1 <= concurrency <= 16:
            raise ValueError("concurrency 须为 1–16；建议保持 2–4")
        if max_jobs is not None and (type(max_jobs) is not int or max_jobs < 1):
            raise ValueError("max-jobs 须为正整数")
        state_path = self.root / "state.json"
        self.state = core.read(state_path) if state_path.exists() else {
            "runner_version": VERSION, "model_profile": self.profile, "jobs": {},
            "current_concurrency": concurrency, "consecutive_overload": 0,
            "cooldown_until": 0, "status": "ready", "created_at": core.timestamp(),
        }
        if self.state.get("runner_version") != VERSION or self.state.get("model_profile") != self.profile:
            raise ValueError("已保存 runner 状态的版本或模型配置与本轮不一致")
        # 续跑不自动扩大曾因过载降低的并发度。
        self.state["current_concurrency"] = min(concurrency, self.state["current_concurrency"])
        self.cooling = self.state["cooldown_until"] > self.clock()
        self.authentication_failed = False
        if not self.cooling and self.state["status"] == "cooldown":
            self.state["consecutive_overload"] = 0
        self.submitted = set()

    def save(self, status=None):
        if status:
            self.state["status"] = status
        self.state["updated_at"] = core.timestamp()
        core.write(self.root / "state.json", self.state)

    def job_state(self, job):
        return self.state["jobs"].setdefault(job["id"], {
            "processed_attempts": 0, "transport_failures": 0, "validation_failures": 0,
            "status": "pending", "ready_at": 0, "last_validation_raw": None,
            "last_validation_error": None,
        })

    def classify(self, job, folder, adapter_error=None, *, output_folder=None):
        """区分适配器/传输故障与模型内容失败，二者使用独立重试额度。"""
        raw_path = folder / "result.raw.json"
        output_folder = output_folder or folder
        outcome = {"attempt": int(folder.name), "stage": job["stage"], "finished_at": core.timestamp(),
                   "input_tokens": None, "output_tokens": None}
        try:
            envelope = adapter_error if adapter_error is not None else strict_json(raw_path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict):
                raise ValueError("适配器结果必须是对象")
        except (OSError, ValueError) as exc:
            return outcome | {"kind": "permanent", "error": f"适配器 envelope 无效：{exc}"}
        if envelope.get("status") == "error":
            category = envelope.get("category")
            if category not in ADAPTER_ERRORS:
                category = "permanent"
            retry_after = envelope.get("retry_after_seconds", 0)
            if type(retry_after) not in (int, float) or not math.isfinite(retry_after) or retry_after < 0:
                retry_after = 0
            return outcome | {"kind": category, "error": str(envelope.get("message", "适配器失败")),
                              "retry_after_seconds": retry_after}
        if envelope.get("status") != "ok":
            return outcome | {"kind": "permanent", "error": "适配器结果 status 不是 ok/error"}
        if envelope.get("model_profile") != self.profile or not isinstance(envelope.get("model"), str) or not envelope["model"].strip():
            return outcome | {"kind": "permanent", "error": "适配器模型配置不匹配或实际模型缺失"}
        outcome["model"] = envelope["model"]
        outcome["model_reported_by_provider"] = envelope.get("model_reported_by_provider")
        outcome["model_profile"] = envelope["model_profile"]
        for name in ("input_tokens", "output_tokens"):
            value = envelope.get(name)
            if value is not None and (type(value) is not int or value < 0):
                return outcome | {"kind": "permanent", "error": f"适配器 {name} 必须为非负整数或 null"}
            outcome[name] = value
        response = envelope.get("response")
        raw = envelope.get("raw_response")
        if raw is None and isinstance(response, dict):
            raw = core.encode(response)
        if not isinstance(raw, str):
            return outcome | {"kind": "permanent", "error": "适配器未提供 response 对象或 raw_response 原文，不能构造修复"}
        core.atomic_text(output_folder / "model_response.raw.txt", raw)
        parsed = None
        validation_job = job
        try:
            from json_repair import JSON_REPAIR_VERSION, parse_model_json
            from runner_repair import compile_subset, effective_job
            parsed, syntax_changes = parse_model_json(raw)
            if response is not None and parsed != response:
                raise ValueError("raw_response 与 response 对象不一致")
            if syntax_changes:
                outcome["json_syntax"] = {"version": JSON_REPAIR_VERSION, "changes": syntax_changes,
                                          "original_raw_file": str((output_folder / "model_response.raw.txt").relative_to(self.run)),
                                          "original_raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "parsed_sha256": core.digest(parsed)}
                core.write(output_folder / "json_syntax.json", outcome["json_syntax"])
            request = core.read(folder / "request.json")
            validation_job = effective_job(self, job, request)
            parsed, normalization = workflow.normalize_with_trace(validation_job, parsed)
            if normalization:
                normalization["original_raw_file"] = str((output_folder / "model_response.raw.txt").relative_to(self.run))
                core.write(output_folder / "normalization.json", normalization)
                outcome["normalization"] = normalization
            validate_response(validation_job, parsed)
            if request.get("record_repair"):
                parsed, outcome["record_repair"] = compile_subset(self, job, request, parsed, output_folder)
        except (ValueError, TypeError, KeyError) as exc:
            from repair_feedback import build_feedback
            from extract_transport import record_aliases
            feedback = build_feedback(validation_job, parsed, str(exc))
            if validation_job["stage"] == "extract":
                # 诊断使用规范来源，回给模型时显示该实际请求中的短 ID。
                for alias, identifier in record_aliases(validation_job).items():
                    feedback = feedback.replace(json.dumps(identifier, ensure_ascii=False), json.dumps(alias, ensure_ascii=False))
                    feedback = feedback.replace(repr(identifier), repr(alias))
            return outcome | {"kind": "validation", "error": str(exc),
                              "repair_feedback": feedback,
                              "raw_file": str((output_folder / "model_response.raw.txt").relative_to(self.run))}
        core.write(output_folder / "response.json", parsed)
        return outcome | {"kind": "valid", "response_file": str((output_folder / "response.json").relative_to(self.run))}

    def apply_outcome(self, job, folder, outcome):
        state = self.job_state(job)
        request = core.read(folder / "request.json")
        if request.get("record_repair"):
            # 请求先于 state 落盘；崩溃若恰在两者之间，恢复必须补记已开始的轮次。
            state["record_repair_rounds"] = max(state.get("record_repair_rounds", 0),
                                                request["record_repair"]["round"])
        kind = outcome["kind"]
        state["processed_attempts"] = outcome["attempt"]
        state["last_outcome_file"] = str((folder / "outcome.json").relative_to(self.run))
        state["last_error"] = outcome.get("error")
        state["status"] = "pending"
        if kind in {"overload", "rate_limit"}:
            self.state["current_concurrency"] = max(1, self.state["current_concurrency"] // 2)
            self.state["consecutive_overload"] += 1
            if self.state["consecutive_overload"] >= 3:
                self.cooling = True
                self.state["cooldown_until"] = max(self.state["cooldown_until"], self.clock() + max(30, outcome.get("retry_after_seconds", 0)))
        else:
            self.state["consecutive_overload"] = 0
        if kind in TRANSPORT_ERRORS:
            state["transport_failures"] += 1
            base = 10 if kind in {"overload", "rate_limit"} else 2
            delay = max(base * 2 ** (state["transport_failures"] - 1) + self.jitter(), outcome.get("retry_after_seconds", 0))
            state["ready_at"] = self.clock() + delay
            if state["transport_failures"] >= 3:
                state["status"] = "blocked"
        elif kind == "validation":
            state["validation_failures"] += 1
            state["last_validation_raw"] = outcome["raw_file"]
            state["last_validation_error"] = outcome["error"]
            # 修复提示可聚合各观察问题；原始首个错误和失败 outcome 仍完整保存。
            state["last_validation_feedback"] = outcome.get("repair_feedback", outcome["error"])
            state["ready_at"] = self.clock()
            if state["validation_failures"] >= 2:
                state["status"] = "blocked"
        elif kind == "valid":
            state["status"] = "valid"
        else:
            state["status"] = "blocked"
            if kind == "authentication":
                # 凭据为所有任务共用，继续对全队列派发只会重复同一个配置故障。
                self.authentication_failed = True
        self.save("cooldown" if self.cooling else "running")

    def finish(self, job, folder, adapter_error=None):
        if adapter_error is not None:
            core.write(folder / "adapter_failure.json", adapter_error)
        outcome = self.classify(job, folder, adapter_error)
        core.write(folder / "outcome.json", outcome)
        self.apply_outcome(job, folder, outcome)
        if outcome["kind"] == "valid":
            self.accept_valid(job, folder, outcome)
        elif outcome["kind"] == "validation":
            from runner_repair import recover_records
            recover_records(self, job)
        return outcome

    def accept_valid(self, job, folder, outcome):
        request = core.read(folder / "request.json")
        source = core.read(self.run / "requests" / f"{job['id']}.json")
        if (request["model_profile"] != self.profile or request["messages_sha256"] != core.digest(request["messages"])
                or request["job_sha256"] != core.digest(job) or request["request_sha256"] != core.digest(source)):
            raise ValueError("持久化模型请求或模型配置已改变")
        if outcome.get("record_repair"):
            from runner_repair import receive_compiled
            receive_compiled(self, job, self.run / outcome["response_file"], outcome["model"], outcome["record_repair"],
                             {"attempt_file": str((folder / "request.json").relative_to(self.run)),
                              "messages_sha256": request["messages_sha256"], "model": outcome["model"],
                              "started_at": request["started_at"], "finished_at": outcome["finished_at"],
                              "json_syntax": outcome.get("json_syntax"), "normalization": outcome.get("normalization")})
            return
        self.workflow.receive(self.run, job["id"], self.run / outcome["response_file"], outcome["model"],
                              outcome.get("input_tokens"), outcome.get("output_tokens"),
                              execution={"model_profile": self.profile,
                                         "model_reported_by_provider": outcome.get("model_reported_by_provider"),
                                         "messages_sha256": request["messages_sha256"],
                                         "attempt_file": str((folder / "request.json").relative_to(self.run)),
                                         "runner_prompt_version": request["runner_prompt_version"],
                                         "started_at": request["started_at"], "finished_at": outcome["finished_at"],
                                         **({"json_syntax": outcome["json_syntax"]} if outcome.get("json_syntax") else {}),
                                         **({"normalization": outcome["normalization"]} if outcome.get("normalization") else {}),
                                         **({"recovery": outcome["recovery"]} if outcome.get("recovery") else {})})
        self.job_state(job)["status"] = "accepted"
        self.save()

    def recover(self, job):
        """结果已落盘但未接收时直接恢复；崩溃中的尝试计入传输失败，不能清零额度。"""
        state = self.job_state(job)
        for folder in sorted((self.root / "attempts" / job["id"]).glob("[0-9]*")):
            ordinal = int(folder.name)
            outcome_path = folder / "outcome.json"
            if ordinal > state["processed_attempts"]:
                if outcome_path.exists():
                    outcome = core.read(outcome_path)
                    self.apply_outcome(job, folder, outcome)
                else:
                    error = None if (folder / "result.raw.json").exists() else {
                        "status": "error", "category": "transport", "message": "上次进程中断，未获得完整适配器结果"}
                    self.finish(job, folder, error)
            if state["status"] == "valid" and ordinal == state["processed_attempts"]:
                self.accept_valid(job, folder, core.read(outcome_path))
        self.recover_normalizable(job)
        from runner_repair import recover_records
        recover_records(self, job)

    def recover_normalizable(self, job):
        """旧失败原文若能通过确定性整理直接恢复，不新增调用、不清零失败额度、不改历史 outcome。"""
        state = self.job_state(job)
        if state["status"] not in {"blocked", "pending"} or not state["last_validation_raw"]:
            return
        original_folder = (self.run / state["last_validation_raw"]).parent
        original_outcome = core.read(original_folder / "outcome.json")
        if original_outcome["kind"] != "validation":
            return
        try:
            from json_repair import parse_model_json
            from runner_repair import effective_job
            request = core.read(original_folder / "request.json")
            validation_job = effective_job(self, job, request)
            original, syntax_changes = parse_model_json((self.run / state["last_validation_raw"]).read_text(encoding="utf-8"))
            normalized, trace = workflow.normalize_with_trace(validation_job, original)
            if not trace and not syntax_changes:
                return
            validate_response(validation_job, normalized)
        except (OSError, ValueError, TypeError, KeyError):
            return
        folder = self.root / "recoveries" / job["id"] / core.digest([trace, syntax_changes, original])[:20]
        outcome = self.classify(job, original_folder, output_folder=folder)
        if outcome["kind"] != "valid":
            return
        # 模型完成时间和用量仍归属于原调用；恢复时间单独记录，统计不重复计算模型 token。
        outcome["finished_at"] = original_outcome["finished_at"]
        outcome["recovery"] = {"recovered_at": core.timestamp(),
                               "original_outcome_file": str((original_folder / "outcome.json").relative_to(self.run)),
                               "original_outcome_sha256": core.digest(original_outcome), "additional_model_calls": 0}
        core.write(folder / "recovery.json", outcome)
        self.accept_valid(job, original_folder, outcome)
        state["normalization_recovery_file"] = str((folder / "recovery.json").relative_to(self.run))
        self.save()

    def prepare_attempt(self, job):
        state = self.job_state(job)
        source = core.read(self.run / "requests" / f"{job['id']}.json")
        if source["job_sha256"] != core.digest(job):
            raise ValueError("原始请求与任务哈希不一致")
        from runner_repair import request_patch
        patch = request_patch(self, job)
        messages = list(source["messages"])
        if patch:
            messages = patch["messages"]
        elif state["last_validation_raw"] is not None:
            messages.extend([
                {"role": "assistant", "content": (self.run / state["last_validation_raw"]).read_text(encoding="utf-8")},
                {"role": "user", "content": "上一份回复未通过校验。只修正下列错误，返回符合原契约的完整 JSON，"
                 "保留引用、覆盖与原语义，不添加来源：\n" + (state.get("last_validation_feedback") or state["last_validation_error"])},
            ])
        request = {"job_id": job["id"], "stage": job["stage"], "job_sha256": core.digest(job), "prompt_version": job["prompt_version"],
                   "request_sha256": core.digest(source), "model_profile": self.profile,
                   "messages": messages, "messages_sha256": core.digest(messages),
                   "runner_prompt_version": VERSION + ":code-repair-3", "started_at": core.timestamp()}
        if patch:
            request["record_repair"] = patch["record_repair"]
        folder = self.root / "attempts" / job["id"] / f"{state['processed_attempts'] + 1:04d}"
        folder.mkdir(parents=True, exist_ok=False)
        core.write(folder / "request.json", request)
        if patch:
            state["record_repair_rounds"] = patch["record_repair"]["round"]
        state["status"] = "in_flight"
        self.save("running")
        return folder

    def result(self, status, code):
        self.save(status)
        from performance import summarize_performance
        performance = summarize_performance(self.run)
        core.write(self.run / "performance_report.json", performance)
        totals = {"input_tokens": 0, "output_tokens": 0, "missing_usage_attempts": 0}
        for path in (self.root / "attempts").glob("*/*/outcome.json"):
            outcome = core.read(path)
            for name in ("input_tokens", "output_tokens"):
                totals[name] += outcome.get(name) or 0
            if outcome.get("input_tokens") is None or outcome.get("output_tokens") is None:
                totals["missing_usage_attempts"] += 1
        snapshot = self.workflow.status(self.run, limit=0)
        summary = {"status": status, "complete": status == "complete", "run_dir": str(self.run),
                   "current_concurrency": self.state["current_concurrency"], "cooldown_until": self.state["cooldown_until"],
                   "accepted_jobs": sum(snapshot["accepted"].values()),
                   "runner_accepted_jobs": sum(s["status"] == "accepted" for s in self.state["jobs"].values()),
                   "pending_count": snapshot["pending_count"],
                   "blocked_jobs": [jid for jid, s in self.state["jobs"].items() if s["status"] == "blocked"],
                   "code_recovered_jobs": sum(bool(s.get("normalization_recovery_file")) for s in self.state["jobs"].values()),
                   "record_repaired_jobs": sum(bool(s.get("record_repair_receipt")) for s in self.state["jobs"].values()),
                   "usage": totals, "updated_at": core.timestamp(),
                   "performance": {"report_file": str(self.run / "performance_report.json"),
                                   "slowest_single_call_stage": performance["slowest_single_call_stage"],
                                   "largest_total_call_stage": performance["largest_total_call_stage"]}}
        core.write(self.root / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return code

    def execute(self):
        if self.cooling:
            return self.result("cooldown", 3)
        while not self.stop.is_set() and not self.cooling and not self.authentication_failed:
            try:
                snapshot = self.workflow.advance(self.run, limit=1000000)
            except ValueError as exc:
                # 阶段规划故障是代码/预算问题，不能靠重试模型掩盖，也不丢掉当前可续跑状态。
                core.write(self.root / "planning_failure.json", {"error": str(exc), "at": core.timestamp()})
                return self.result("planning_failed", 2)
            if snapshot["complete"]:
                return self.result("complete", 0)
            jobs = [core.read(self.run / "jobs" / f"{item['job_id']}.json") for item in snapshot["pending"]]
            for job in jobs:
                self.recover(job)
            if self.cooling or self.stop.is_set() or self.authentication_failed:
                break
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                active = {}
                while True:
                    for job in jobs:
                        state = self.job_state(job)
                        if self.stop.is_set() or self.cooling or self.authentication_failed or len(active) >= self.state["current_concurrency"]:
                            break
                        if state["status"] != "pending" or state["ready_at"] > self.clock():
                            continue
                        if self.max_jobs is not None and len(self.submitted) >= self.max_jobs and job["id"] not in self.submitted:
                            continue
                        folder = self.prepare_attempt(job)
                        active[pool.submit(self.adapter, self.command, folder / "request.json", folder / "result.raw.json")] = (job, folder)
                        self.submitted.add(job["id"])
                    if not active:
                        eligible = [job for job in jobs if self.job_state(job)["status"] == "pending"
                                    and (self.max_jobs is None or len(self.submitted) < self.max_jobs or job["id"] in self.submitted)]
                        if self.stop.is_set() or self.cooling or self.authentication_failed or not eligible:
                            break
                        self.sleep(min(1, max(0.01, min(self.job_state(j)["ready_at"] for j in eligible) - self.clock())))
                        continue
                    finished, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
                    for future in finished:
                        job, folder = active.pop(future)
                        try:
                            error = future.result()
                        except Exception as exc:
                            error = {"status": "error", "category": "permanent", "message": f"未知宿主异常：{type(exc).__name__}"}
                        outcome = self.finish(job, folder, error)
                        print(json.dumps({"job_id": job["id"], "outcome": outcome["kind"],
                                          "concurrency": self.state["current_concurrency"]}, ensure_ascii=False), flush=True)
            if self.cooling or self.stop.is_set() or self.authentication_failed:
                break
            if any(self.job_state(job)["status"] == "blocked" for job in jobs):
                return self.result("blocked", 2)
            if any(self.job_state(job)["status"] == "pending" for job in jobs):
                return self.result("max_jobs_reached", 3)
        if self.authentication_failed:
            return self.result("authentication_error", 2)
        return self.result("cooldown" if self.cooling else "interrupted", 3)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--adapter-command-json", required=True)
    parser.add_argument("--concurrency", type=int, default=2, help="默认 2；建议不超过 4，显式设置最多 16")
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--record-repair-rounds", type=int, default=2, help="提取缺口最多补齐 0–2 轮；复用完整合法记录，不重做整批")
    args = parser.parse_args(argv)
    try:
        run = Path(args.run).resolve()
        command = strict_json(args.adapter_command_json)
        with run_lock(run / "runner" / "runner.lock"):
            runner = Runner(run, command, args.concurrency, args.max_jobs, record_repair_rounds=args.record_repair_rounds)

            def stop(signum, frame):
                runner.stop.set()

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            return runner.execute()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"status": "host_error", "complete": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
