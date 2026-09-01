# Multimodal Design DNA Extractor

面向单图、单主体的设计 DNA 提取 Skill，用于审美标签、检索索引、方案匹配和知识库增量维护。它先提取可观察 DNA，再执行风格硬门槛和混淆仲裁，避免先猜标签再寻找证据。

## 能力边界

- 每次只处理一张图片并选择一个主物品。
- 输出稳定风格 ID、规范 DNA、定位证据、置信度、不确定项和新 DNA 候选。
- 一级风格仅作导航；二级风格由决定性锚点、独立辅助证据、硬排除和混淆边界共同判定。
- 风格锚点与辅助命中受机器 allowlist 约束；字段 profile、必要视角、派生依赖、枚举与标签值域均可确定性校验。
- 单图只描述视觉材质候选，不断言真实成分、工艺或随角变化。
- 结果显式记录 `active_profiles`；单图不激活 multi-face/reference/trend，M15 固定以 `profile_not_applicable` 排除。

## 目录职责

- `SKILL.md`：任务边界和核心决策流程。
- `references/design-dna-knowledge-base.zh-CN.md`：风格与规范 DNA 字典。
- `references/style-registry.json`、`field-registry.json`：稳定风格与字段机器表。
- `references/extraction-protocol.zh-CN.md`：完整执行协议。
- `references/output-contract.zh-CN.md`：状态、证据和置信度约束。
- `references/category-adaptation.zh-CN.md`：通用核心与品类 profile。
- `schemas/design-dna-output.schema.json`：权威输出结构。
- `scripts/validate_output.py`：Schema 与语义校验。
- `evals/`：边界、冲突与回归评测。

## 使用

将整个目录安装或挂载到支持 Agent Skills 的视觉宿主，并向 Agent 提供恰好一张图片。Agent 最终只返回符合 Schema 的 JSON；保存和业务视图转换由宿主应用负责。

本地校验：

```bash
python scripts/validate_output.py result.json
python scripts/validate_skill_package.py
```

不原生支持 Skill 的宿主可生成完整上下文；生成物同时包含知识库与权威 Schema：

```bash
python scripts/build_prompt_bundle.py --output prompt_bundle.txt
```

## 版本

- Skill：`2.0.0`
- 输出 Schema：`design_dna_extraction_v4.0`
- 设计 DNA 知识库：`3.0`

知识库在本 Skill 内独立维护。
