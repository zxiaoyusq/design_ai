# 架构决策

## 2026-08-31：统一管理模型目录与调用入口

- 所有可用模型及其 `model_provider` 统一维护在 `app/services/llm/catalog.py`。
- 业务模块必须通过 `app.services.llm` 创建或调用模型，不直接实例化供应商 SDK。
- Claude 模型使用 Anthropic 协议；当前 GPT、MiniMax 和 Qwen 模型使用 OpenAI 兼容协议。
- OpenAI 兼容协议统一使用网关的 `/v1` 路径，配置已包含该路径时不重复追加。
- 模型 Key 和网关地址只从 `LLM_KEY`、`LLM_URL` 读取，调用方不能覆盖连接参数。
- 前端通过 `GET /api/v1/llm/models` 获取目录中的可选模型，接口不返回凭据或网关地址。
