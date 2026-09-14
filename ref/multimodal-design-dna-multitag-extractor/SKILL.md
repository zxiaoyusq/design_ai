---
name: multimodal-design-dna-multitag-extractor
description: 仅在用户点名本 Skill，或明确要求扁平、多标签、无主次或组合风格时，从单张图片提取可追溯的同层风格候选与设计 DNA；普通设计 DNA 提取继续使用原版 Skill。
metadata:
  author: "AI审美洞察项目"
  version: "2.0.0"
  language: "zh-CN"
  schema-version: "design_dna_multitag_extraction_v1.2"
  knowledge-base-version: "4.1"
---

# Multimodal Design DNA Multitag Extractor

## 任务边界

本 Skill 从恰好一张图片中选择一个主物品，先提取适用品类的规范 DNA，再输出零到五个有真实视觉支持的扁平风格候选及组合预设，并发现知识库外的新 DNA 候选。

不要用于多物品比较、多图聚合、图片生成或纯文本设计咨询。不得从像素断言真实尺寸、成分、重量、触感或耐久性；图片缺失或不可读时停止。

## 执行前加载

若宿主已把本 Skill、执行协议、模型参考包、知识库、适配规则和模型 Schema 作为带版本的完整系统前缀注入，则直接使用该快照，不再通过工具逐文件读取；未预装时按下列顺序读取。

1. 模型阶段读取 `references/extraction-protocol.zh-CN.md`；`references/output-contract.zh-CN.md` 供宿主后处理和最终校验使用。
2. 模型阶段读取 `schemas/design-dna-model-output.schema.json`，只输出 `design_dna_multitag_observation_v2`；最终结果由宿主编译并按 `schemas/design-dna-output.schema.json` 校验。
3. 模型读取 `references/model-reference-bundle.json` 中的活动风格、字段 allowlist 与规范字段类型，不读取宿主专用组合预设。用 `references/knowledge-index.zh-CN.md` 定位品类字段值域和候选规则。
4. 跨品类时读取 `references/category-adaptation.zh-CN.md`；出现知识库外元素时再读取 `references/novel-dna-governance.zh-CN.md`。

## 核心工作流

### 1. 锁定主体与图像质量

按视觉焦点、面积、完整度和展示意图选择一个主物品，输出归一化包围框。背景、人物、支架、包装、UI、水印、倒影及其他物品不得进入主体 DNA。

记录视角、可见区域及图像干扰；颜色和材质可靠度属于输入质量，不属于产品 DNA。

### 2. 先提取可观察 DNA

先确定品类、视角与 `active_profiles`，再调用宿主字段准入工具取得当前图片可用的 canonical 字段。当前单图只允许 `core` 与有对象依据的单视图 profile，不激活 multi-face、reference 或 trend profile。

模型只提取准入集合内且图片实际可观察、风格判断需要或用户明确关注的字段，不穷举全部语义维度。确认不存在时使用字段值域内的“无”或空列表，不借用状态表达。

### 3. 输出真实风格候选

结果不输出一级、二级、主风格、次风格或“已确认风格”。所有 `style_id` 都是同层候选。模型从 KB 4.1 的活动风格中选择零到五个图片中确有可见支持的候选，并为每个已输出候选填写：

- `style_id`：只使用活动稳定 ID；
- `match_score`：规则与当前物品的匹配程度，0～100；
- `confidence`：该候选判断正确的概率，0～1；
- `regions`：风格实际作用区域，只能来自主体可见区域；
- `main_support`：至少一条图片中直接可见的主要支持；
- `main_conflicts`：可见但削弱候选的因素，没有时返回空数组。

候选不需要达到 `confidence>=0.75`，也不需要满足旧版 confirmed 的决定字段、独立辅助字段、颜色门槛、完整规则覆盖或成对仲裁。确无候选时返回空数组；不得输出仅因名称相似而没有像素支持的风格，也不得把明确不匹配的风格当作“拒绝候选”加入列表。

`TribeIdentity` 已废弃，不得进入候选。可见文字、图标和身份显性度记录到 IDG 字段，身份信息不产生风格候选。

宿主根据 `(-match_score, style_id)` 稳定排序并生成连续 rank；模型不输出 rank、静态名称、facet、确认状态、主导占比、硬规则状态、规则计数或两两仲裁。

### 4. 组合摘要、不确定项与新 DNA

`composition_summary` 概括这些候选分别由哪些区域和视觉机制支持，不得创造候选列表之外的新标签。

`derived_style_presets` 不由模型生成。宿主只根据最终 `style_candidates[].style_id` 与组合注册表做确定性集合匹配；候选分数和文字不参与计算，派生组合也不反向修改候选或 DNA。

置信度低于 0.75、字段存在合理竞争、视角不足或不可计算时写入 `uncertainties`。完成既有字段映射后，才可提出 `new_module`、`new_field`、`new_enum_value` 或 `new_relation_rule`；新候选必须可观察、可复用、可参数化并与已有字段去重。

### 5. 证据与输出

证据必须位于主体框内并只描述可见事实。证据、设计元素及风格候选的 `regions` 只能使用 `target_object.visible_regions` 中的值或 `whole_object`。每个观察字段至少引用一条证据；已计算推断字段至少引用两条独立观察证据。

模型只返回符合 `design-dna-model-output.schema.json` 的精简观察 JSON。字段与风格静态元数据、模块清单、统计值、排序和组合预设均不得重复生成。宿主运行 `scripts/compile_model_output.py`：

- 补全注册表静态元数据并稳定排序候选；
- 按 profile 和视角移除不适用字段；
- 依据 `references/value-normalization.json` 归一化显式别名、关系词和离散刻度；
- 重建低置信镜像并计算统计值；
- 不新增视觉事实，不把候选升级或降级为确认状态。

随后 `scripts/save_result.py` 根据候选 ID 写入 `derived_style_presets`，再执行最终 Schema 与语义校验。最终结果只包含 JSON，不附加 Markdown、解释、路径或思考过程，禁止 `NaN` 与 `Infinity`。

## 确定性校验

```bash
python scripts/compile_model_output.py model_observation.json > compiled_result.json
python scripts/derive_style_presets.py compiled_result.json --output result.json
python scripts/validate_output.py result.json
```

校验失败时只修复结构或语义错误，不改变有证据支持的视觉事实。

## 支持文件

- 执行协议：`references/extraction-protocol.zh-CN.md`
- 输出合同：`references/output-contract.zh-CN.md`
- 知识库：`references/design-dna-knowledge-base.zh-CN.md`
- 完整风格与字段注册表：`references/style-registry.json`、`references/field-registry.json`
- 宿主值域归一化规则：`references/value-normalization.json`
- 模型精简索引：`references/model-reference-bundle.json`
- 宿主专用组合派生规则：`references/style-combination-presets.json`
- 品类适配与新 DNA：`references/category-adaptation.zh-CN.md`、`references/novel-dna-governance.zh-CN.md`
- 模型/最终 JSON Schema：`schemas/design-dna-model-output.schema.json`、`schemas/design-dna-output.schema.json`
- 组合派生器：`scripts/derive_style_presets.py`
- 模型观察编译器：`scripts/compile_model_output.py`
- 结果校验器：`scripts/validate_output.py`
- 评测：`evals/rubric.zh-CN.md`、`evals/cases.jsonl`
