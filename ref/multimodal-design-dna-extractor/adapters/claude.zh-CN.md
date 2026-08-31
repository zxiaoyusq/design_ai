# Claude / Claude Code 接入

把完整目录安装到 Claude 支持的 Skills 位置，确保父目录名与 `SKILL.md` 中的 `name` 完全一致：`multimodal-design-dna-extractor`。

使用时向会话提供一张图片，并要求提取主物品设计 DNA。Skill 会按渐进披露方式读取协议、知识库和 Schema。

注意：
- 不要只复制长提示词；需要保留 `references/`、`schemas/` 和 `scripts/`。
- 若 Claude 环境不能执行 Python，仍可按 Schema 生成 JSON，但应由外部服务执行同等校验。
- 如果请求是多图聚合或多物品比较，应使用另一个工作流，不要让本 Skill 静默扩展任务边界。
