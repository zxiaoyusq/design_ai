---
name: multimodal-design-dna-extractor
description: 从单张图片中只选择一个主物品，依据内置设计 DNA 知识库提取可追溯的风格、规范 DNA 字段、不确定项及知识库外新候选。Use for multimodal aesthetic analysis, design tagging, retrieval, scoring, or knowledge-base growth. Do not use for multi-object comparison, image generation, or exact physical/material claims from pixels.
metadata:
  author: "AI审美洞察项目"
  version: "2.0.0"
  language: "zh-CN"
  schema-version: "design_dna_extraction_v4.0"
  knowledge-base-version: "3.0"
---

# Multimodal Design DNA Extractor

## 任务边界

本 Skill 从恰好一张图片中选择一个主物品，提取风格、适用品类的规范 DNA、证据、置信度和不确定项，并发现知识库外新 DNA 候选。

不要用于多物品比较、多图聚合、图片生成、纯文本设计咨询，也不要从像素断言真实尺寸、成分、重量、触感或耐久性。图片缺失或不可读时停止，不依据文件名或备注虚构结论。

## 执行前加载

1. 读取 `references/extraction-protocol.zh-CN.md` 与 `references/output-contract.zh-CN.md`。
2. 读取 `schemas/design-dna-output.schema.json`，它是输出结构的权威定义。
3. 读取完整 `references/style-registry.json`；用 `references/knowledge-index.zh-CN.md` 定位 `references/field-registry.json` 和知识库中当前品类相关的字段。风格判定必须读取全局规则、全部候选及其同混淆组风格，不得只读取支持某一候选的片段。
4. 跨品类时读取 `references/category-adaptation.zh-CN.md`；出现知识库外元素时再读取 `references/novel-dna-governance.zh-CN.md`。

## 核心工作流

### 1. 锁定主体与评估图像

按视觉焦点、面积、完整度和展示意图选择一个主物品，输出归一化包围框。背景、人物、支架、包装、UI、水印、倒影及其他物品不得进入主体 DNA。

记录视角、可见区域、遮挡、模糊、曝光、透视、白平衡与反射干扰；颜色可靠度、材质可靠度和拍摄光线属于图像质量，不属于产品 DNA。

### 2. 判断适用性并先提取可观察 DNA

先确定品类和 profile，将实际启用项写入 `module_applicability.active_profiles`，再逐字段判断适用性。当前单图只允许 `core` 与可见对象支持的单视图品类 profile，不激活 multi-face、参考或趋势 profile。相同字段 ID 在不同品类中不得改义。

- `applicability_status`：`applicable` 或 `not_applicable`，只表示品类适用性；
- `observability`：`observed`、`not_observable` 或 `unknown`，只描述直接证据可见性；
- `evidence_mode`：`direct`、`derived`、`inferred` 或 `reference_computed`，说明结论来源；
- `computation_status`：直接字段固定 `not_requested`；其余字段只能为 `computed` 或 `not_computable`，缺依赖时不得猜测；
- 确认不存在：使用字段值域中的“无”、空列表等类型内取值，并保持 `observability="observed"`；不得跨类型写通用 `none`。

先提取规范 DNA，再依据决定性锚点召回候选风格。原 MD 六维兼容视图由宿主派生；当前提取结果固定输出空数组。

### 3. 风格硬判与混淆仲裁

一级标签只作导航，二级 `style_id` 承担判定。一个风格只有同时满足以下条件才可确认：

1. 硬门槛通过；
2. 至少一个决定性锚点；
3. 至少一个来自不同区域或不同视觉机制的辅助证据；
4. 未命中硬排除。

同一区域或同一物理现象只计一次。颜色是否为必要项以具体风格记录为准，不设全局强制颜色门槛。
颜色角色为 `required` 时必须通过并引用证据，不能写 `not_applicable`；每条核心或辅助命中必须显式引用本次已确认、且位于该风格注册 allowlist 的规范 `field_id`，辅助命中至少使用一个不同字段。

对候选逐项核对 `异混淆特征` 和混淆组：共享表象不能作为双方的独立决定证据；决定性差异不可见时只能输出 `provisional` 或 `unclassified`。主风格最多一个，次风格最多两个。DNA-M13 语义坐标只能在硬判完成后排序，不能绕过门槛、排除或仲裁。

### 4. 不确定项与新 DNA

置信度低于 0.75、存在多个合理候选、视角不足或定义不足时写入 `uncertain_fields`，并与对应设计元素的字段、区域、状态和置信度一致；列出支持、反对证据和建议补充视角。无法判断时保持空候选。

完成既有字段映射后，才可提出 `new_module`、`new_field`、`new_enum_value` 或 `new_relation_rule`。候选必须可观察、可复用、可参数化，并与已有字段去重；背景、拍摄光线、损伤、污渍和偶然状态不是新 DNA。

### 5. 证据与输出

证据必须位于主体框内并描述“看到了什么”。观察字段至少引用一条证据；已计算的推断字段至少引用两条独立观察证据。真实材质、工艺、品牌归属、文化来源、随角变化、趋势和创新度只能按知识库规定输出视觉候选或上下文计算结果。

最终只返回一个符合 Schema 的 JSON 对象，不附加 Markdown、解释、路径或思考过程。输出前检查：单主体、字段适用性、风格硬门槛与混淆仲裁、状态组合、证据闭环、低置信度登记、新 DNA 去重及版本一致性。

本 Skill 不负责保存结果或生成业务视图；宿主应用在模型返回后统一校验、保存和转换。

## 确定性校验

宿主可在 Skill 目录运行：

```bash
python scripts/validate_output.py result.json
```

传统宿主需要合并上下文时运行：

```bash
python scripts/build_prompt_bundle.py --output prompt_bundle.txt
```

校验失败时只修复结构或语义错误，不改变有证据支持的视觉事实。

## 支持文件

- 提取协议：`references/extraction-protocol.zh-CN.md`
- 输出合同：`references/output-contract.zh-CN.md`
- 知识库：`references/design-dna-knowledge-base.zh-CN.md`
- 机器注册表：`references/style-registry.json`、`references/field-registry.json`
- 稳定索引：`references/knowledge-index.zh-CN.md`
- 品类 profile：`references/category-adaptation.zh-CN.md`
- 新 DNA 治理：`references/novel-dna-governance.zh-CN.md`
- JSON Schema：`schemas/design-dna-output.schema.json`
- 结果校验器：`scripts/validate_output.py`
- 评测：`evals/rubric.zh-CN.md`、`evals/cases.jsonl`
