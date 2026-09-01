# OpenAI ChatGPT / Codex 接入

本目录遵循开放 Agent Skills 结构，核心入口是带 YAML frontmatter 的 `SKILL.md`。

- 在支持独立 Skill 的 ChatGPT/Codex 环境中，导入整个目录，而不是只复制 `SKILL.md`。
- 通过显式选择该 Skill，或提出“从图片提取设计 DNA、一级二级风格、证据与置信度”等请求触发。
- 图片必须作为当前请求的视觉输入提供；Skill 中的知识库不能替代实际图片。
- 有结构化输出能力时，使用 `schemas/design-dna-output.schema.json`。
- 在具备本地/容器 Python 的环境中，生成后运行 `scripts/validate_output.py`。
- Agent 只返回 JSON，不自行写入工程目录。宿主应用在模型返回后统一调用校验、保存与业务视图转换。

若部署为插件或服务，可把知识库放在受控资源中，但必须保证分析时加载的知识库版本与输出中的 `knowledge_base_version` 一致。
