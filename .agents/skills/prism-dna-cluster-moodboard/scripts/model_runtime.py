"""DeepAgents 单轮视觉模型：通过真实 Codex CLI 附图，记录原始输入与执行回执。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import signal
from pathlib import Path
import subprocess
import tempfile
from time import monotonic, sleep
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents.middleware import wrap_model_call
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, PrivateAttr
import jsonschema

MODEL = "gpt-6.1-sol"
EFFORT = "high"
REPO = Path(__file__).resolve().parents[4]
TRANSPORT_PATH = REPO / "backend/app/services/visual_workflow/codex_transport.py"
_spec = importlib.util.spec_from_file_location("prism_existing_cli_transport", TRANSPORT_PATH)
_transport = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_transport)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path: str | Path) -> dict:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path)}


def write_new(path: str | Path, value: Any) -> None:
    """每个模型调用目录不可覆盖，避免将失败历史伪装为一次成功。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
        stream.write("\n")


def close_process_group(process: subprocess.Popen) -> dict:
    """每次CLI拥有独立会话；成功、超时或Python中断均清理本次整组子孙进程。"""
    group_id = process.pid
    audit = {"process_id": process.pid, "process_group_id": group_id, "signals": [],
             "group_isolated_with_start_new_session": True}

    def group_exists() -> bool:
        try:
            os.killpg(group_id, 0)
            return True
        except ProcessLookupError:
            return False

    if group_exists():
        try:
            os.killpg(group_id, signal.SIGTERM)
            audit["signals"].append("SIGTERM")
        except ProcessLookupError:
            pass
        deadline = monotonic() + 2
        while group_exists() and monotonic() < deadline:
            process.poll()
            sleep(.05)
        if group_exists():
            try:
                os.killpg(group_id, signal.SIGKILL)
                audit["signals"].append("SIGKILL")
            except ProcessLookupError:
                pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        audit["launcher_wait_timeout"] = True
    def active_group_members() -> list[int]:
        # Linux中等待init回收的僵尸仍使kill(0)成功；只把非僵尸成员视作活跃请求。
        members = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == group_id and fields[0] not in {"Z", "X"}:
                    members.append(int(entry.name))
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
        return members

    deadline = monotonic() + 2
    remaining = active_group_members()
    while remaining and monotonic() < deadline:
        sleep(.02)
        remaining = active_group_members()
    audit["active_group_members_after_cleanup"] = remaining
    audit["process_group_present_after_signals"] = group_exists()
    audit["launcher_returncode_after_cleanup"] = process.returncode
    return audit


def run_cli_process(argv: list[str], *, prompt: str, cwd: str, environment: dict,
                    stdout, stderr, timeout: int, cleanup: dict) -> int:
    """CLI启动器可能再生原生子进程；finally保证异常也不会只杀启动器遗留模型进程。"""
    with subprocess.Popen(argv, stdin=subprocess.PIPE, text=True, cwd=cwd, env=environment,
                          stdout=stdout, stderr=stderr, start_new_session=True) as process:
        try:
            process.communicate(input=prompt, timeout=timeout)
            return process.returncode
        finally:
            cleanup.update(close_process_group(process))


class CodexVisionChatModel(BaseChatModel):
    """实际接入 DeepAgents 的模型适配；只允许一个无工具、带原图的模型轮次。"""

    folder: Path
    image_refs: list[dict] = Field(default_factory=list)
    response_schema: dict = Field(default_factory=dict)
    timeout_seconds: int = 900
    _invoked: bool = PrivateAttr(default=False)
    _receipt: dict = PrivateAttr(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "codex-cli-image-deepagents"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        if tools:
            raise ValueError("本观察阶段禁止工具和额外模型轮次")
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._invoked:
            raise RuntimeError("单批只授权一次模型调用；禁止自动重发")
        self._invoked = True
        systems = [str(m.content) for m in messages if m.type == "system"]
        humans = [m for m in messages if m.type == "human"]
        if len(systems) != 1 or len(humans) != 1 or len(messages) != 2:
            raise ValueError("只接受当前 system + 一个当前 user，不继承历史上下文")
        user = humans[0].content
        if not isinstance(user, str):
            raise ValueError("图片由适配器按 SHA 附件列表传输，用户内容必须为序列化事实")
        payload = json.loads(user)
        prompt = _transport.build_stdin(systems[0], payload, self.image_refs)
        env = _transport.isolated_environment()
        auth = _transport.verify_chatgpt_auth(env)
        for item in self.image_refs:
            if digest(item["path"]) != item["sha256"]:
                raise ValueError("附图字节与当前输入 SHA 不一致")
        write_new(self.folder / "prompt.txt", prompt)
        write_new(self.folder / "schema.json", self.response_schema)
        argv = ["codex", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "-m", MODEL, "--json", "--color", "never"]
        for config in ('model_reasoning_effort="high"', 'service_tier="default"',
                       'features.shell_tool=false', 'features.multi_agent=false',
                       'features.view_image=false', 'features.image_generation=false',
                       'web_search="disabled"', 'project_doc_max_bytes=0'):
            argv.extend(["--config", config])
        for item in self.image_refs:
            argv.extend(["-i", item["path"]])
        argv.extend(["--output-schema", str(self.folder / "schema.json"),
                     "-o", str(self.folder / "answer.raw.txt"), "-"])
        started, clock_start = now(), monotonic()
        metadata = {"framework": "DeepAgents", "deepagents_version": importlib.metadata.version("deepagents"),
                    "model_adapter": self._llm_type, "transport": "Codex CLI", **auth,
                    "requested_model": MODEL, "requested_reasoning_effort": EFFORT,
                    "requested_service_tier": "default", "actual_service_tier": None,
                    "actual_model": None, "actual_provider": None, "started_at": started,
                    "automatic_host_retries": False, "images": self.image_refs,
                    "prompt_ref": ref(self.folder / "prompt.txt"),
                    "schema_ref": ref(self.folder / "schema.json"), "argv": argv,
                    "runtime_ref": ref(__file__), "event_parser_ref": ref(TRANSPORT_PATH)}
        write_new(self.folder / "request.json", metadata)
        failure, returncode = None, None
        process_cleanup = {}
        with tempfile.TemporaryDirectory(prefix="prism-dna-vision-") as cwd:
            with (self.folder / "events.jsonl").open("x", encoding="utf-8") as out, \
                    (self.folder / "stderr.txt").open("x", encoding="utf-8") as err:
                try:
                    returncode = run_cli_process(argv, prompt=prompt, cwd=cwd, environment=env,
                                                 stdout=out, stderr=err, timeout=self.timeout_seconds,
                                                 cleanup=process_cleanup)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    failure = f"{type(exc).__name__}: {exc}"
        parsed = _transport.parse_events((self.folder / "events.jsonl").read_text(encoding="utf-8"))
        metadata.update({key: value for key, value in parsed.items() if key != "last_agent_message"})
        metadata.update(finished_at=now(), seconds=round(monotonic() - clock_start, 3),
                        exit_code=returncode, failure=failure, status="failed", process_cleanup=process_cleanup)
        raw_path = self.folder / "answer.raw.txt"
        if not raw_path.exists() and parsed["last_agent_message"] is not None:
            write_new(raw_path, parsed["last_agent_message"])
        rejected = (failure or returncode != 0 or parsed["tool_event_count"] or
                    parsed["invalid_jsonl_line_numbers"] or parsed["failure_events"] or
                    parsed["completed_turn_count"] != 1 or parsed["started_turn_count"] != 1 or
                    not raw_path.exists() or
                    any(model != MODEL for model in parsed["reported_models"]))
        try:
            if rejected:
                raise RuntimeError(f"单轮模型执行失败，保留回执且不自动重发：{failure or returncode}")
            raw = raw_path.read_text(encoding="utf-8")
            answer = json.loads(raw)
            jsonschema.Draft202012Validator(self.response_schema).validate(answer)
            write_new(self.folder / "answer.json", answer)
            metadata["status"] = "completed"
            metadata["answer_ref"] = ref(self.folder / "answer.json")
        except Exception as exc:
            metadata["failure"] = str(exc)
            raise
        finally:
            metadata["events_ref"] = ref(self.folder / "events.jsonl")
            self._receipt = metadata
            write_new(self.folder / "receipt.json", metadata)
        usage = parsed["usage"]
        ai = AIMessage(content=raw, response_metadata={"model_name": parsed["actual_model"],
                       "requested_model": MODEL, "finish_reason": "stop", "receipt_path": str(self.folder / "receipt.json")},
                       usage_metadata={"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                                       "total_tokens": usage["total_tokens"]})
        return ChatResult(generations=[ChatGeneration(message=ai)])


def execute_structured(folder: str | Path, *, system: str, payload: dict,
                       images: list[dict], schema: dict, timeout: int = 900) -> dict:
    """执行真实 DeepAgents 图像观察，所有附件对应当前原始字节，不加载预设风格。"""
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    write_new(folder / "system.txt", system)
    write_new(folder / "payload.json", payload)
    model = CodexVisionChatModel(folder=folder, image_refs=images,
                                 response_schema=schema, timeout_seconds=timeout)
    invoked = False

    @wrap_model_call
    def one_call(request, handler):
        nonlocal invoked
        if invoked:
            raise RuntimeError("禁止 DeepAgents 自动追加模型轮次")
        invoked = True
        return handler(request.override(tools=[], system_message=SystemMessage(content=system)))

    agent = create_deep_agent(model=model, tools=[], subagents=[], backend=StateBackend(),
                              middleware=[one_call], system_prompt=system, name="prism-dna-observation")
    result = agent.invoke({"messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
                          config={"recursion_limit": 4})
    if result["messages"][-1].tool_calls:
        raise RuntimeError("模型产生了非授权工具调用")
    return json.loads((folder / "answer.json").read_text(encoding="utf-8"))
