---
name: multimodal-design-dna-extractor
description: 从单张图片中只选择一个主物品，依据内置设计 DNA 知识库提取一级/二级风格、适用品类的设计元素与扩展 DNA，并输出可定位证据、置信度、不确定字段及知识库外新 DNA 候选。Use for multimodal aesthetic analysis, design tagging, retrieval, scoring, or knowledge-base growth. Do not use for multi-object comparison, image generation, or exact physical/material claims from pixels.
metadata:
  author: "AI审美洞察项目"
  version: "1.1.0"
  language: "zh-CN"
  schema-version: "design_dna_extraction_v3.1"
  knowledge-base-version: "2.0"
---

# Multimodal Design DNA Extractor

## 任务边界

使用本 Skill 处理以下任务：

- 从一张图片中识别并只分析一个主物品；
- 判断一级风格、二级风格及候选风格；
- 按物品品类动态启用适用的设计元素和 DNA 字段；
- 输出字段值、可见证据、区域、可观察性和置信度；
- 管理低置信度、不可见、定义边界不足的字段；
- 发现知识库尚未覆盖的新模块、新字段、新枚举值或新关系规则。

不要使用本 Skill 完成：

- 多物品比较、系列对比或多图聚合；
- 图片生成、图片编辑或审美评分文案；
- 从单张图片断言真实尺寸、真实材料成分、真实重量、真实触感、真实耐久性；
- 不依赖图片的纯文本设计咨询。

## 必需输入

运行条件：宿主必须具备单图视觉能力，并能读取 UTF-8 Markdown 与 JSON。本工程使用 Python 3.9+ 和 `jsonschema>=4.21,<5` 完成确定性校验与落盘。

1. **恰好一张图片**。图片中可以存在多个物体，但最终只选择一个主物品。
2. 可选文本备注：品类先验、业务场景、需要重点关注的区域。
3. 本 Skill 自带知识库：`references/design-dna-knowledge-base.zh-CN.md`。

图片缺失或不可读取时，不执行 DNA 提取，直接说明缺少有效图片。不要根据文件名或用户描述虚构视觉结论。

## 执行前加载

每次激活本 Skill 后：

1. 读取 `references/extraction-protocol.zh-CN.md`，执行完整提取流程。
2. 读取 `references/output-contract.zh-CN.md`，遵循状态、证据、置信度及 JSON 约束。
3. 读取 `schemas/design-dna-output.schema.json`，把它作为最终输出结构的权威定义。
4. 读取 `references/design-dna-knowledge-base.zh-CN.md`：
   - 上下文允许时加载完整知识库；
   - 上下文受限时，先读取 `references/knowledge-index.zh-CN.md`，再从完整知识库读取全局判定规则、全部候选风格的完整记录、当前品类适用模块和所有冲突风格；
   - 不得只检索支持某个风格的片段而忽略排除项和冲突规则。
5. 只有在需要跨品类适配时读取 `references/category-adaptation.zh-CN.md`。
6. 只有在发现知识库外元素时读取 `references/novel-dna-governance.zh-CN.md`。

## 核心工作流

### 1. 主物品锁定

按视觉焦点、面积、完整度、中心性和展示意图选择一个主物品，输出其归一化包围框。背景、人物、支架、包装、UI、水印、倒影和其他物品不得混入主物品 DNA。

### 2. 图像质量与视角评估

识别视角、可见区域、遮挡、模糊、曝光、透视、复杂背景、白平衡和反射干扰。分别估计颜色可靠度与材质可靠度。

### 3. 品类与模块适用性

先判断 `category`、`subcategory`，再逐模块、逐字段确定：

- `applicable`：适用于当前品类；
- `not_applicable`：与当前品类无关；
- `not_observable`：该字段有意义，但当前视角看不到；
- `unknown`：相关区域可见，但无法可靠判定；
- `none`：字段适用且已确认不存在该元素，表现为 `value="none"` 与 `observability="observed"`。

`design_elements` 只允许包含 `applicable` 字段。不适用模块只进入 `excluded_modules`。例如服装不得输出相机架构或手机正面字段。

### 4. 风格判定

使用知识库中的一级、二级风格原名，按以下顺序判断：

1. 入围门槛与颜色必要项；
2. 核心视觉特征；
3. 辅助特征；
4. 排除规则，一票否决；
5. 冲突仲裁与优先判定；
6. DNA-M13 语义坐标只用于排序辅助，不能绕过硬规则。

主风格最多一个，次风格最多两个。证据不足时输出 `provisional` 或 `unclassified`，不得为了填满字段强行分类。

### 5. 已有 DNA 提取

同时输出：

- 原始 MD 六个维度中适用的元素；
- DNA-M01 至 DNA-M15 中适用且可观察/可推断的字段。

每个字段必须包含标准化值、可见描述、区域、可观察性、置信度和证据引用。观察型字段至少一个证据；推断型字段至少两个观察证据或观察字段支撑。

### 6. 不确定字段

以下情况进入 `uncertain_fields`：

- 置信度低于 0.75；
- 存在两个以上合理候选；
- 遮挡、模糊、反射、光照、透视或视角不足；
- 字段适用但不可见；
- 知识库定义不足以唯一归类。

给出最佳估计、候选概率、支持/反对证据及建议补充视角。无法判断时保持空候选，不得编造。

### 7. 新 DNA 发现

完成已有字段映射后，再查找知识库无法充分表达、但可观察、可复用、可参数化且对设计有意义的元素。只允许输出：

- `new_module`
- `new_field`
- `new_enum_value`
- `new_relation_rule`

新 DNA 必须与现有字段做去重和差异说明。背景、拍摄光线、损伤、污渍、遮挡和偶然状态不是新 DNA。

### 8. 证据闭环

证据必须定位到主物品内部的具体区域或整个主物品，描述“看到了什么”，不要在证据文字中重复抽象结论。所有引用的证据 ID 必须真实存在。

### 9. 输出、自检与落盘

完整结果必须是符合 `schemas/design-dna-output.schema.json` 的单个 JSON 对象。结果文件中不得混入 Markdown、解释、思考过程、代码围栏或保存路径。

输出前必须确认：

- 只分析一个主物品；
- 没有把背景或其他物品混入结果；
- 没有输出不适用品类的 DNA 字段；
- 风格已检查必要项、排除项和冲突规则；
- `none`、`unknown`、`not_observable`、`not_applicable` 未混用；
- 低置信度字段已进入 `uncertain_fields`；
- 新 DNA 不是已有字段同义词；
- JSON 可解析，证据引用闭合。

在本工程中，完成自检后必须执行以下落盘流程：

1. 从工程根目录使用 `base` Conda 环境运行 `scripts/save_result.py`，通过 `--image` 传入原始图片路径或文件名，并通过输入文件或标准输入提供完整结果 JSON。
2. 保存脚本会再次执行 Schema 与语义校验；校验失败时不得写入，也不得声称保存成功。
3. 完整结果固定写入 `data/result/`，文件名为 `YYYYMMDD_HHMMSS_<图片名>_design_dna.json`。时间戳使用 `Asia/Shanghai`，图片名不含扩展名并经过文件名安全化。
4. 若目标文件已存在，保留原文件，并使用 `_02`、`_03` 等序号生成新文件。
5. 完整结果保存成功后，若工程根目录存在 `extract_design_dna_business_view.py`，运行它处理刚生成的完整结果。业务视图写入同一目录，文件名为 `<完整结果文件名去扩展名>_business_view.json`。

示例：

```bash
conda run -n base python ref/multimodal-design-dna-extractor/scripts/save_result.py \
  --image "/path/to/product.jpg" result.json

conda run -n base python extract_design_dna_business_view.py \
  "data/result/20260830_153012_product_design_dna.json"
```

落盘成功后的对话回执只需报告完整结果与业务视图的路径和校验状态，不要把文件路径添加进结果 JSON。用户明确要求在对话中查看完整 JSON 时，再单独返回与文件内容一致的 JSON 对象。

## 确定性校验

宿主 Agent 可以在生成后运行：

```bash
python scripts/validate_output.py result.json
```

在本工程中优先直接使用 `scripts/save_result.py`，它会在写入前调用同等的 Schema 与语义校验。

需要把本 Skill 转换为传统“系统提示词 + 知识库”调用时运行：

```bash
python scripts/build_prompt_bundle.py --output prompt_bundle.txt
```

校验失败时，只修复报告指出的结构或语义问题，不要改变有证据支持的视觉事实。

## 支持文件

- 完整提取协议：`references/extraction-protocol.zh-CN.md`
- 输出语义与状态协议：`references/output-contract.zh-CN.md`
- 完整知识库：`references/design-dna-knowledge-base.zh-CN.md`
- 知识库索引：`references/knowledge-index.zh-CN.md`
- 跨品类适配：`references/category-adaptation.zh-CN.md`
- 新 DNA 治理：`references/novel-dna-governance.zh-CN.md`
- JSON Schema：`schemas/design-dna-output.schema.json`
- 结果校验器：`scripts/validate_output.py`
- 结果校验与落盘器：`scripts/save_result.py`
- 评测规范：`evals/rubric.zh-CN.md`
