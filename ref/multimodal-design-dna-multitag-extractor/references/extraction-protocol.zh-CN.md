# 扁平多标签设计 DNA 提取执行协议

> 最终结果适用于 `schema_version="design_dna_multitag_extraction_v1.2"` 与 `knowledge_base_version="4.1"`；模型阶段只输出 `design_dna_multitag_observation_v2`。

## 一、任务

从图片中选择唯一主物品，先提取可追溯的规范设计 DNA，再输出零到五个有真实视觉支持的扁平风格候选、组合摘要、不确定项和知识库外新 DNA 候选。

知识库与机器注册表决定已有标签、字段、值域和边界。模型通过 `model-reference-bundle.json` 读取活动风格、字段 allowlist 与字段类型；完整注册表由宿主编译和校验使用。通用设计知识只能帮助识别视觉事实和发现知识库缺口，不得改写已有枚举或稳定 ID。

## 二、基本原则

### 1. 一张图只分析一个物品

主物品按视觉焦点、面积、完整度、中心性和展示意图选择，并输出 `bbox_norm=[x_min,y_min,x_max,y_max]`。背景、人物、道具、包装、UI、水印、倒影、环境投影和其他物品不得混入主体 DNA。

### 2. 候选同层且允许组合

所有活动 `style_id` 均为同层候选。结果不输出 `parent_style_id`、`level_1`、`level_2`、`primary_style`、`secondary_styles`、确认状态或主导占比。后台 facet 只用于导航和检索。

`TribeIdentity` 已废弃，不得进入候选。可见文字、图标、身份显性度和参考确认实体分别记录为 IDG 字段，身份信息不是风格候选。

### 3. 先 DNA，后风格

不得先猜风格再反向寻找事实。先输出当前品类和视角可用的规范字段，再据此选择图片中确有视觉支持的风格候选。DNA-M13 与 M14 可用于解释，但不能替代像素支持。

### 4. 只陈述像素可支持的事实

真实尺寸、重量、材料成分、内部结构、耐久性、真实触感、未展示视角、真实工艺、品牌实体、文化来源和趋势关系，除非协议提供外部依据，否则不得确认为事实。

## 三、执行流程

### 步骤 A：主体与图像质量

记录主体类别、子类别、选择依据、包围框、视角、可见区域及图像干扰。不得用全图平均颜色替代主体主色，也不得把拍摄光线、滤镜或背景模糊当成产品风格。

### 步骤 B：profile 与字段准入

`active_profiles` 必须包含 `core`，只增加当前物品和视图确实支持的单视图品类 profile。当前流程不得激活 multi-face、reference 或 trend profile。

确定视角和 profile 后，模型先调用宿主字段准入工具，只在返回的 canonical 字段中选择图片实际可观察、风格判断需要或用户明确关注的字段。不要穷举 M13/M14。

### 步骤 C：提取规范 DNA

字段身份、类型、证据模式、profile、视角与派生依赖以 `field-registry.json` 为准，enum/multi_label 值域以知识库为准。模型每项只记录规范 `field_id`、值、可见描述、区域、可观察性、置信度和原始证据引用；名称、路径、类型、证据模式、计算状态和模块归属由宿主补全。

- `applicability_status` 表示品类或 profile 是否适用；
- `observability` 表示输入是否可见；
- `computation_status` 表示非直接字段能否计算；
- `evidence_mode` 由注册表固定；
- 确认不存在使用字段值域中的“无”或空列表，不借用状态表达。

### 步骤 D：输出风格候选

从活动风格中选择零到五个有实际视觉支持的候选。每个已输出候选必须包含：

- `style_id`；
- `match_score`（0～100）；
- `confidence`（0～1）；
- 至少一个来自 `target_object.visible_regions` 的 `regions`；
- 至少一条 `main_support`；
- `main_conflicts`，没有时为 `[]`。

候选不是 confirmed 结论。置信度可低于 0.75，也不要求旧版的决定字段、独立辅助字段、颜色门槛、完整规则计数和两两仲裁全部闭合。候选仍必须有像素支持；确无支持时返回空数组，明显不匹配、仅由风格名称联想或只为凑数量的风格不得输出。

宿主按 `(-match_score, style_id)` 稳定排序并生成 rank。模型不输出 rank、标签静态信息、确认/拒绝状态、dominance、硬规则状态、规则覆盖或仲裁结构。

### 步骤 E：组合与摘要

`composition_summary` 说明候选分别由哪些区域和视觉机制支持，不创建候选列表之外的新风格。

模型不输出 `derived_style_presets`。宿主直接用最终 `style_candidates[].style_id` 匹配组合注册表；候选分数、置信度和文字不参与组合计算，派生结果也不反向补足候选或 DNA。

### 步骤 F：不确定项与新 DNA

字段置信度低于 0.75、存在合理竞争、视角不足、图片受干扰或无法计算时，写入 `uncertainties`。完成已有字段映射后，才可提出 `new_module`、`new_field`、`new_enum_value` 或 `new_relation_rule`。新 DNA 必须位于主体上、可观察、可复用、可参数化并与现有字段去重。

## 四、证据与置信度

证据框必须位于主体框内。`evidence.region`、设计元素区域和风格候选区域只能取 `target_object.visible_regions` 中的值或 `whole_object`。证据描述只写“看到了什么”，不写抽象风格结论。

- `direct + observed` 至少引用一条证据；
- `derived + computed` 覆盖源字段证据；
- `inferred + computed` 至少引用两条独立观察证据；
- 每个风格候选至少有一条可见支持。

置信度建议：0.90～1.00 为直接且定义明确；0.75～0.89 为证据较强；0.55～0.74 为竞争明显；低于 0.55 仅在仍有清楚视觉支持且对用户有解释价值时保留。

## 五、输出

- `schema_version="design_dna_multitag_observation_v2"`；
- `knowledge_base_version="4.1"`；
- 结果只包含 JSON，不含 Markdown、解释、注释、路径、NaN、Infinity 或尾逗号；
- 空集合使用 `[]`，单值不可得使用 `null`；
- 稳定 ID、英文标签和标准枚举保持原样。

宿主使用 `compile_model_output.py` 生成 `design_dna_multitag_extraction_v1.2`，补全静态元数据、字段状态、候选 rank、统计值与低置信镜像。宿主不得新增视觉事实，也不得把候选升级或降级为确认状态。`save_result.py` 只根据候选 ID 派生组合并完成最终校验。

## 六、输出前自检

1. 只分析一个主物品，已隔离背景与道具；
2. profile、视角、适用性、可见性和计算状态一致；
3. 先规范 DNA，后风格候选；
4. `candidate_tags` 有 0～5 项，每个已输出候选至少一条真实视觉支持；
5. 没有 confirmed、unclassified、dominance、硬规则状态或两两仲裁字段；
6. 没有 TribeIdentity 等废弃 ID，也没有只为凑数的拒绝项；
7. 证据、设计元素和候选区域只使用可见区域或 `whole_object`；
8. 组合摘要没有创造结论，组合预设留给宿主生成；
9. 低置信、不可见或不可计算字段已登记；
10. 所有数字有限，版本固定为 observation v2 / KB 4.1，并通过模型阶段 Schema。
