# OpenAI ChatGPT / Codex 接入

- 导入整个目录，不要只复制 `SKILL.md`。
- 只有用户点名本 Skill，或明确要求扁平、多标签、无主次或组合风格时才触发；普通设计 DNA 请求使用原版 Skill。
- 提供一张当前请求中的图片，并要求提取扁平多标签设计 DNA、证据与置信度。
- 有结构化输出能力时使用 `schemas/design-dna-output.schema.json`。
- 生成后运行 `scripts/validate_output.py`；Agent 只返回 JSON，保存与业务视图转换由宿主负责。
- 分析时加载的知识库版本必须与结果中的 `knowledge_base_version` 一致。
- 当前有 38 个活动标签；TribeIdentity 已废弃，身份信息只记录为 IDG-05/07/09。组合预设只用于检索，不写入结果。
