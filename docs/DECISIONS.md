# 架构决策

## 2026-08-31：统一管理模型目录与调用入口

- 所有可用模型及其 `model_provider` 统一维护在 `app/services/llm/catalog.py`。
- 业务模块必须通过 `app.services.llm` 创建或调用模型，不直接实例化供应商 SDK。
- Claude 模型使用 Anthropic 协议；当前 GPT、MiniMax 和 Qwen 模型使用 OpenAI 兼容协议。
- OpenAI 兼容协议统一使用网关的 `/v1` 路径，配置已包含该路径时不重复追加。
- 模型 Key 和网关地址只从 `LLM_KEY`、`LLM_URL` 读取，调用方不能覆盖连接参数。
- 前端通过 `GET /api/v1/llm/models` 获取目录中的可选模型，接口不返回凭据或网关地址。

## 2026-08-31：图片与结果先使用文件系统存储

- 当前阶段不接入 SQL 数据库；上传文件保存在 `data/uploads/<image_id>/`，成功结果保存在 `data/result/`。
- 上传元数据与图片一同保存，因此服务重启后仍可恢复素材列表。
- 任务状态暂存在后端进程内；服务重启会丢失运行中和历史任务状态，但已上传图片及成功结果不受影响。
- 结果列表只展示同时存在完整结果和 `_business_view.json` 的成功提取，避免暴露半成品。
- 每个成功结果在 `data/result/.metadata/` 保存追溯旁路文件，不向严格的 Skill 输出 Schema 增加字段。

## 2026-08-31：每张图片独立运行 Design DNA Skill

- 使用 DeepAgents 的 `create_deep_agent`、`FilesystemBackend` 和原生 `skills` 参数加载项目 Skill。
- 单次 Agent 执行只接收一张图片；批量和文件夹任务由应用层逐张串行调度，单图失败不阻塞同批其他图片。
- Agent 只读项目 Skill 和参考资料，不允许写文件；应用层统一执行 Schema 校验、语义校验、结果保存和业务视图转换。
- 模型输出校验失败时最多携带确定性错误修复一次；低置信字段数量等可计算统计由应用层重算，不消耗模型修复轮次。

## 2026-08-31：长推理使用流式连接并异步展示

- DeepAgents 完整技能执行可能包含多轮文件读取和长结构化输出，因此 API 以后台任务启动，前端轮询任务状态。
- 模型客户端启用流式响应，避免网关前置代理因长时间没有响应体而触发 524。
- Anthropic provider 使用兼容客户端，将网关字典型 `context_management` 流事件转换为 LangChain 可序列化对象；OpenAI provider 保持标准 LangChain 客户端。
- Claude Opus 5 与 Claude Fable 5 按官方最大输出能力设置为 128K token；其他模型不在应用代码中设置 `max_tokens`，继续由模型和网关决定。
- 确认弹窗只负责确认任务范围，提交后立即关闭；长任务进度在工作台中持续展示。

## 2026-08-31：开发环境由根目录脚本统一启动

- 根目录 `start.sh` 固定激活 conda `base` 环境，并并发启动 FastAPI 与 Vite。
- 任一服务退出或用户按 `Ctrl+C` 时，脚本统一终止另一个服务，避免遗留后台进程。
- 默认端口为后端 8000、前端 5173；可通过 `DESIGN_AI_BACKEND_PORT` 和 `DESIGN_AI_FRONTEND_PORT` 覆盖，Vite 代理目标随之更新。

## 2026-08-31：素材与提取结果采用独立删除生命周期

- 删除素材只清理 `data/uploads/<image_id>/`，不级联删除已完成的提取结果；正在等待或执行提取的素材返回冲突，避免任务中途丢失输入。
- 每条新结果在 `data/result/.images/` 保存最长边 480px 的独立 WebP 缩略图。旧结果首次读取时可通过追溯哈希从素材库补齐，因此素材删除后历史结果缩略图仍然可用。
- 删除提取结果会同时清理完整详情、业务视图、追溯元数据和独立图片，删除范围严格限定在该结果 ID 拥有的文件。
