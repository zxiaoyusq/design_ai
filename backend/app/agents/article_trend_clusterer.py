"""每个聚类或独立复核阶段使用全新、无工具的 DeepAgent 上下文。"""

from time import monotonic

from app.agents.bounded import AGENT_RUNTIME_VERSION, create_bounded_agent
from app.services.llm import create_chat_model
from app.services.llm.telemetry import ModelCallTelemetry


def run_text_step(model_id: str, system: str, payload: str) -> dict:
    telemetry = ModelCallTelemetry()
    started = monotonic()
    try:
        model = create_chat_model(model_id, temperature=0, streaming=True, timeout=180, max_retries=0)
        agent = create_bounded_agent(model=model, system_prompt=system,
                                     name="prism-trend-semantic-clustering", max_input_chars=48000)
        response = agent.invoke({"messages": [{"role": "user", "content": payload}]},
                                config={"callbacks": [telemetry], "recursion_limit": 40})
        message = response["messages"][-1]
        content = message.content
        text = content if isinstance(content, str) else "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        metadata = getattr(message, "response_metadata", {}) or {}
        finish = metadata.get("finish_reason", metadata.get("stop_reason"))
        return {"text": text, "truncated": finish in ("length", "max_tokens"),
                "response_model": metadata.get("model_name") or metadata.get("model"),
                "seconds": monotonic() - started, "telemetry": telemetry.snapshot(),
                "agent_runtime_version": AGENT_RUNTIME_VERSION}
    except Exception as exc:
        exc.trend_telemetry = telemetry.snapshot()
        raise
