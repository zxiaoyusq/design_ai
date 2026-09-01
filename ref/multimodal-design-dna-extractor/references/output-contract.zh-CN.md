# 输出协议与字段语义

本协议适用于 `schema_version="design_dna_extraction_v4.0"` 与 `knowledge_base_version="3.0"`。完整结果必须是合法 JSON，并通过 `schemas/design-dna-output.schema.json`；结构冲突时以该 Schema 为权威。

## 1. 顶层结构

必须包含：

- `schema_version`
- `knowledge_base_version`
- `target_object`
- `image_quality`
- `module_applicability`
- `style_result`
- `design_elements`
- `uncertain_fields`
- `novel_dna_elements`
- `evidence`
- `quality_summary`

禁止添加未定义的顶层字段。空集合使用 `[]`，单值不可得使用 `null`。

`module_applicability.active_profiles` 必须包含 `core`，只列当前对象确实支持的单视图 profile；当前不得激活 `profile:multi_face_device`、`profile:reference_analysis` 或 `profile:trend_analysis`。M15 必须进入 `excluded_modules`，原因为 `profile_not_applicable`。

## 2. 单主体约束

`target_object` 是单个对象。`bbox_norm=[x_min,y_min,x_max,y_max]` 的值域为 0–1，且满足 `x_min < x_max`、`y_min < y_max`。背景、人物、道具及其他物品不得混入主体 DNA。

## 3. 三轴状态与证据模式

每个规范字段由三条状态轴和一项固定证据模式共同表达，禁止互相代用：

- `applicability_status="applicable|not_applicable"`：字段是否适用于当前品类；进入 `design_elements` 的字段只能是 `applicable`。
- `evidence_mode="direct|derived|inferred|reference_computed"`：字段定义规定的取值方法，不随单次结果改变。
- `observability="observed|not_observable|unknown"`：必要视觉输入是否可见，只允许这三个枚举。
- `computation_status="computed|not_computable|not_requested"`：计算状态，不表达可见性或品类适用性。

使用规则：

- `direct`：`computation_status="not_requested"`；可直接确认时为 `observed`，否则为 `not_observable` 或 `unknown`。
- `derived|inferred`：必要视觉输入可见且完成计算时为 `observed + computed`；输入不足时为 `not_computable`。
- `reference_computed`：core 字段在当前单图缺参考集时为 `not_computable`；未激活 profile 中的字段不进入结果，由扩展工作流处理。
- `not_applicable` 字段不进入 `design_elements`，只在模块适用性中记录。
- `not_requested` 仅表示直接字段无需计算；已进入结果的非直接字段不得用它代替 `not_computable`。

“不存在”是字段值，不是状态：enum 使用注册值域中的“无”，list 使用 `[]`；未声明缺省取值的其他类型不输出“无”结论。确认不存在时仍写 `observability="observed"`，不得跨类型写通用字符串 `none`。

直接字段为 `not_observable|unknown`，或非直接字段为 `not_computable` 时，`value` 使用 `null`。这些情况及置信度低于 0.75 的已有字段应进入 `uncertain_fields`。

## 4. 字段值与证据

- 使用字段注册表中的稳定 `field_id`、`value_type`、`evidence_mode`、profile 与必要视角；enum/multi_label 值域取知识库规范表。真别名不得重复提取，兼容 derived 只作零权重投影。
- 推荐类型为 `enum|float|integer|boolean|list|multi_label|object|text`；`list` 可含结构化条目，`multi_label` 只含字符串标签，无值状态允许 `null`。
- 所有 `evidence_refs` 必须引用 `evidence` 中存在的 ID。
- `direct + observed` 至少引用 1 条证据；`derived + computed` 至少引用 1 条输入证据；`inferred + computed` 至少引用 2 条独立观察证据。
- core 中的 `reference_computed` 字段缺参考上下文时是 `not_computable`，不能写成 `not_applicable`；仅属未激活 profile 的模块才是不适用。
- 证据描述只写可见事实，不写“高级、科技、时尚”等抽象结论。
- 证据框应位于主体框内；整体比例或整体风格可引用主体整体框。
- `original_md_dimensions` 是宿主兼容槽，当前模型输出必须为 `[]`，不得独立生成旧六维值。

## 5. 风格结果

风格判断必须在可观察 DNA 提取之后；DNA-M13 只能在硬门槛和混淆仲裁完成后参与排序。

- `confirmed`：主风格硬规则通过，颜色要求通过或不适用，无缺失、失败、未知及排除项，并完成必要的混淆仲裁。
- `provisional`：存在最佳候选，但决定性分界不可观察、不可计算或证据不足。
- `unclassified`：没有风格通过硬门槛；必须同时满足 `primary_style=null`、`secondary_styles=[]`。

风格使用活动记录中的稳定 `style_id` 与 `parent_style_id`，并保留 `label_en`、`label_zh`、`aliases`、`level_1`、`level_2`。未知或已废弃 ID 不得作为结果。

`primary_style` 最多一个；`secondary_styles` 最多两个，且每项都须独立通过硬规则。未通过但外观相似的风格只能进入 `candidate_ranking`。候选排名从 1 连续递增，风格不得重复。

规则计数必须满足：

`applicable_rule_count = passed_rule_count + failed_rule_count + unknown_rule_count`

`not_applicable_rule_count` 不进入适用规则分母；`confirmed` 的 `failed_rule_count` 与 `unknown_rule_count` 必须为 0。

“异混淆特征”是判定规则，不新增结果字段。相关候选的共享表象、分界证据和裁决写入 `conflict_arbitration`；`core_feature_hits` 与 `auxiliary_feature_hits` 每项须写规范 `field_id`，且分别属于 style-registry 的决定/辅助 allowlist，对应证据须纳入风格 `evidence_refs`；分界不可确认时不得输出 `confirmed`。

## 6. 不确定字段与置信度

置信度表示结论正确概率，而非显眼程度：

- `0.90–1.00`：证据直接且定义唯一；
- `0.75–0.89`：证据较强，存在轻微干扰；
- `0.55–0.74`：候选竞争明显；
- `<0.55`：只作候选或无值处理。

`uncertain_fields` 同时容纳低置信度、多候选、遮挡或质量干扰、直接字段不可见，以及非直接字段不可计算等情况。候选概率之和应约为 1；无可靠候选时使用空数组，不得伪造。

## 7. 新 DNA

`novel_dna_elements` 只容纳知识库不能充分表达、位于主体上且可复用、可参数化的内容。每项须有证据、与已有字段的差异、值类型或值域、适用品类及设计价值，并标记为 `new_module|new_field|new_enum_value|new_relation_rule`。`new_enum_value` 仅用于既有 enum 字段，必须引用规范 `existing_field_id`、保持 enum 类型且提出值域外新值；其他类型该字段为 `null`。没有可靠候选时输出 `[]`。

## 8. 颜色、材质与语义

- 无标准光源、色卡或可信元数据时，不伪造高精度 NCS、CIELAB 或 OKLCH。
- 材质只输出视觉材质候选，不等同于真实成分或具体工艺。
- 单张静态图不能证明随角变色、真实尺寸、重量、触感或内部结构。
- 推断语义使用 `evidence_mode="inferred"`，不能补足风格锚点或抵消排除项。

## 9. JSON 与宿主职责

- 提取结果只包含 JSON，不使用 Markdown 围栏、注释、尾逗号、NaN 或 Infinity。
- 中文描述使用简体中文；稳定 ID、英文标签和标准枚举保持原样。
- 提取器只负责生成符合协议的结果。文件保存、命名、防覆盖、业务视图转换及路径回执由宿主应用负责，不属于结果 Schema。
