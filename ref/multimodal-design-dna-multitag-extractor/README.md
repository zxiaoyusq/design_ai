# Multimodal Design DNA Multitag Extractor

面向单图、单主体的扁平多标签设计 DNA 提取 Skill。它先提取可观察 DNA，再对每个风格独立执行硬门槛，并验证返回标签之间是否可共存。

它与原 `multimodal-design-dna-extractor` 并存，不替换原版：普通设计 DNA 请求继续使用原版；只有用户点名本 Skill，或明确要求“扁平、多标签、无主次、组合风格”时使用本版。

## 关键约束

- 每次只处理一张图片并选择一个主物品。
- 风格是同层稳定 `style_id`，不输出一级/二级或主/次风格。
- `style_tags` 只含 0～3 个已确认标签；多标签不是强制目标。
- 已确认标签置信度不低于 0.75；单标签 dominance=1，多标签 dominance 之和约为 1。
- `style_tags` 严格按 `(-dominance,-match_score,style_id)` 排序，候选严格按 `(-match_score,style_id)` 排序；所有区域值均来自主体 `visible_regions` 或 `whole_object`。
- 每个标签保留匹配度、置信度、视觉主导度、适用区域、规则闭环与证据。
- provisional/rejected 的 dominance 固定为 0；若自身硬门槛已通过但因标签对冲突降级，必须记录非空 `main_conflicts`。
- 当前有 38 个活动标签：37 个 atomic 参与相似检索，只有 MysticOrganic 为零权重 composite。
- 组合预设不交给模型判断；Python 仅根据 confirmed 原子标签确定性写入最终 `derived_style_presets`。
- `facet_ids` 只用于后台导航；TribeIdentity 已废弃，身份只写入 IDG-05/07/09，不再生成风格标签。
- 每对返回标签必须通过关系仲裁；conditional 同区模式为 `forbidden` 时必拒，为 `independent_evidence` 时须有双方独占核心证据。
- NeoRetro 还须由两族不共享证据及 `DET-17=历史造型化` 闭环；该值只描述可见语法，不证明年代或来源。
- 规范 DNA 继续约束 profile、必要视角、派生依赖、值域和证据状态。
- 单图只描述视觉材质候选，不断言真实成分、工艺或随角变化。
- JSON 禁止 `NaN` 和 `Infinity`。

## 主要资源

- `SKILL.md`：任务边界与核心流程。
- `references/design-dna-knowledge-base.zh-CN.md`：风格与规范 DNA 定义。
- `references/style-registry.json`、`references/tag-relations.json`：扁平标签及其组合关系。
- `references/style-combination-presets.json`：宿主专用的组合派生与查询规则。
- `references/field-registry.json`：规范字段机器表。
- `references/extraction-protocol.zh-CN.md`：完整执行协议。
- `references/output-contract.zh-CN.md`：输出语义约束。
- `schemas/design-dna-model-output.schema.json`：模型阶段结构。
- `schemas/design-dna-output.schema.json`：包含 Python 派生字段的最终结构。
- `scripts/derive_style_presets.py`：确定性写入组合预设。
- `scripts/validate_output.py`：Schema 与语义校验。
- `evals/`：单标签、多标签共存、冲突和通用回归。

## 使用

向宿主提供恰好一张图片。Agent 返回模型阶段 JSON；宿主必须先派生组合预设，再校验或保存最终 JSON。

```bash
python scripts/derive_style_presets.py model_result.json --output result.json
python scripts/validate_output.py result.json
python scripts/validate_skill_package.py
```

不原生支持 Skill 的宿主可生成完整上下文：

```bash
python scripts/build_prompt_bundle.py --output prompt_bundle.txt
```

## 版本

- Skill：`1.2.0`
- 输出 Schema：`design_dna_multitag_extraction_v1.1`
- 设计 DNA 知识库：`4.1`

本 Skill 独立维护，不依赖外部 Excel 或旧 Skill 运行时。
