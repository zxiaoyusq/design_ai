# 扁平多标签设计 DNA 提取执行协议

> 适用于 `schema_version="design_dna_multitag_extraction_v1.0"` 与 `knowledge_base_version="4.1"`。宿主应同时提供一张图片、完整知识库、注册表与权威 Schema。

## 一、任务

从图片中选择唯一一个主物品，先提取可追溯的规范设计 DNA，再独立判定零到三个可共存的扁平风格标签，并输出候选、不确定项、成对仲裁、组合摘要和知识库外新 DNA 候选。

知识库与机器注册表决定已有标签、字段、值域、硬门槛、排除项、混淆边界及关系。通用设计知识只能帮助识别视觉事实和发现知识库缺口，不得改写已有规则。

## 二、基本原则

### 1. 一张图只分析一个物品

主物品按视觉焦点、面积、完整度、中心性和展示意图选择，并输出 `bbox_norm=[x_min,y_min,x_max,y_max]`。背景、人物、道具、包装、UI、水印、倒影、环境投影和其他物品不得混入主体 DNA。

服装可使用穿着后的轮廓、垂坠和合体关系，但人体特征不属于服装 DNA。

### 2. 标签同层且允许组合

所有活动 `style_id` 均为同层标签。结果不输出 `parent_style_id`、`level_1`、`level_2`、`primary_style` 或 `secondary_styles`。后台 facet 只用于导航和检索扩展，不构成排他分类。

KB 4.1 共有 38 个活动标签：37 个 `atomic`，仅 `MysticOrganic` 为 `composite`。`TribeIdentity` 已废弃，不得进入 `style_tags` 或 `candidate_ranking`。可见文字/图标、身份显性度和参考确认实体分别记录为 `IDG-05`、`IDG-07`、`IDG-09`；身份信息不是风格判定结果。

一张图可以有零个、一个或多个标签，但最多确认三个。多标签不是目标；每个标签都必须独立通过自身规则，并有不能完全被其他标签替代的证据。

### 3. 先 DNA，后风格

不得先猜风格再反向寻找证据。先输出当前品类和视角可用的规范字段，再用决定锚点召回候选。DNA-M13 与 M14 只能在硬判后用于排序或解释，不能补足门槛。

### 4. 三轴状态互不替代

- `applicability_status="applicable|not_applicable"`：字段是否属于当前品类/profile；
- `observability="observed|not_observable|unknown"`：必要视觉输入是否可见；
- `computation_status="computed|not_computable|not_requested"`：计算状态；
- `evidence_mode="direct|derived|inferred|reference_computed"`：注册表固定的取值方式。

`direct` 固定 `not_requested`；非直接字段只能 `computed` 或 `not_computable`。确认不存在使用字段值域中的“无”或空列表，并保持 `observed`；不得跨类型写通用 `none`。

### 5. 只陈述像素可支持的事实

真实尺寸、重量、材料成分、内部结构、耐久性、真实触感、未展示视角、真实工艺、随角变化、品牌实体、文化来源和趋势关系，除非相应协议提供外部依据，否则不得确认为事实。

## 三、执行流程

### 步骤 A：主体与图像质量

记录：

- 主体类别、子类别、选择依据和包围框；
- 视角与可见区域；
- 遮挡、模糊、曝光、透视、背景、白平衡及反射干扰；
- 颜色可靠度与材质可靠度。

不得用全图平均颜色替代主体主色，也不得把拍摄光线、滤镜或背景模糊当成产品风格。

### 步骤 B：profile 与模块适用性

`active_profiles` 必须包含 `core`，只增加当前物品和视图确实支持的单视图品类 profile。当前流程不得激活 multi-face、reference 或 trend profile，DNA-M15 固定以 `profile_not_applicable` 排除。

只有 profile、品类和必要视角均满足的字段才可确认。未激活 profile 的字段不进入 `design_elements`；core 中缺参考集的 reference-computed 字段记为 `not_computable`，不能写成不适用。

### 步骤 C：提取规范 DNA

字段身份、类型、证据模式、profile、视角与派生依赖以 `field-registry.json` 为准，enum/multi_label 值域以知识库为准。每项记录规范 `field_id`、值、可见描述、区域、状态、置信度和证据引用。

要求：

- 只输出 canonical 字段；alias 和 compatibility projection 不参与计分；
- `multi_label` 只含登记过的字符串标签，`list` 用于结构化或混合条目；
- derived 字段必须闭合全部依赖并覆盖源证据；
- 同一区域、同一物理现象不重复计数；
- 当前模型固定输出 `original_md_dimensions=[]`。

可见名称、Logo、角色或联名组合先按像素事实写入 IDG 字段。`IDG-09` 缺批准参考库时保持 `not_computable`；无论身份是否可确认，都不得恢复或新建身份风格标签。

### 步骤 D：召回与单标签硬判

只用步骤 C 的规范 DNA 召回候选。每个候选分别检查：

1. 硬门槛；
2. 至少一个位于注册 allowlist 的决定字段；
3. 至少一个不同字段、区域或机制的辅助证据；
4. required 颜色状态；
5. 缺失必要项与硬排除；
6. 相关混淆组和异混淆特征。

共享表象不能同时充当两个标签的独立决定证据。决定边界不可见、可由功能结构解释或置信度不足时，该项只能保留为暂定候选，不进入 `style_tags`。

### 步骤 E：选择 confirmed-only 标签

`style_tags` 只容纳已确认标签，数量为 0～3。每项必须：

- `hard_rule_passed=true`；
- `confidence>=0.75`；
- 无失败规则、未知规则、缺失项和排除项；
- required 颜色通过；
- 至少引用决定证据与独立辅助证据；
- `regions` 只列主体上实际起作用的区域；
- 使用当前活动 `style_id`，不得输出别名或废弃 ID。

`tag_kind` 与 `facet_ids` 必须原样取注册表。当前除 `MysticOrganic` 外的活动标签均为 atomic；废弃的 identity 记录不能作为候选。

三个强度字段含义不同：

- `match_score`：该标签规则与当前物品的匹配程度，0～100；
- `confidence`：该判断正确的概率，0～1；
- `dominance`：该标签在已确认组合中的相对视觉贡献，0～1。

存在标签时，所有 `dominance` 之和应约为 1；只有一个标签时固定为 1。`style_tags` 严格按 `(-dominance,-match_score,style_id)` 排序。主导度不等于置信度，排序也不把最高标签变成“主风格”。

### 步骤 F：成对关系与组合

读取 `tag-relations.json`。关系类型只有：

- `compatible`：规则独立通过时可以共存；
- `exclusive`：适用作用域内不得同时确认；
- `conditional`：只有关系记录中的条件和作用域得到有证据的裁决后才能共存。

作用域只有 `global`、`same_region_same_mechanism`、`cross_region_or_mechanism`。显式关系优先；未登记组合按 `default_pair_relation` 执行。一般情况下，同区域同机制必须检查重复表达和决定边界，跨区域或独立机制更可能共存，但仍需各自完整过门槛。

对 `conditional + same_region_same_mechanism` 的同区冲突 facet，读取 `same_region_coexistence`：`forbidden` 必须二选一；`independent_evidence` 只有双方 core 字段各有差集、字段证据各有对方未用的差集，且仲裁引用两侧独占证据时才能共存。跨区仍按原关系条件判断。

对 `style_tags` 中每个无序标签对输出且只输出一条 `pairwise_arbitrations`，数量应为 `n×(n-1)/2`；每对按字典序写为 `style_id_a < style_id_b`，最终 `decision` 必须为 `coexist`。仲裁必须说明：

- 使用的关系及作用域；
- 两标签各自的独立机制、区域和证据；
- 是否满足关系条件；
- 最终为何允许共存。

命中 `exclusive` 或未满足 `conditional` 时，只保留证据更完整的标签；另一项进入 `candidate_ranking` 并记录冲突。依赖使用 `target_quantifier="any|all"`：`requires` 必须由相应数量的已确认目标满足，否则源标签不得确认；`implies` 按量词召回目标进入完整候选排序，但不能代替目标自身硬门槛。

`composition_summary` 概括已确认机制如何在主体上组合。它不创建新风格、不重复排名，也不能作为硬判证据。

`style-combination-presets.json` 仅在原子标签提取完成后，把已确认标签映射为用户熟悉的组合检索入口。预设名不进入 `style_tags`，不参与硬判，也不得反向补足任何标签证据。

### 步骤 G：状态与候选排序

- `confirmed`：`style_tags` 含 1～3 个已确认标签；
- `unclassified`：`style_tags=[]`。可以保留有支持但未闭合规则的暂定候选，原因写入候选冲突与组合摘要。

`candidate_ranking` 是完整候选排序，必须包含全部 `style_tags`，也可包含暂定或失败候选。使用 `candidate_status="confirmed|provisional|rejected"`；confirmed 候选的 dominance 大于 0 且与标签一致，provisional/rejected 固定为 0。非 confirmed 候选的 `hard_rule_passed` 可为 true 或 false；若为 true，表示自身门槛已通过但因标签对冲突降级，且 `main_conflicts` 必须非空。候选严格按 `(-match_score,style_id)` 排列，rank 从 1 连续递增；已确认标签在两处的身份、强度、区域和硬判状态必须一致。该排序不产生主/次语义。

### 步骤 H：不确定项与新 DNA

置信度低于 0.75、存在合理竞争、视角不足、图像干扰、定义边界不足或非直接字段不可计算时，写入 `uncertain_fields`，列出候选概率、支持与反对证据及建议补充信息。

完成已有字段映射后，才可提出：

- `new_module`；
- `new_field`；
- `new_enum_value`；
- `new_relation_rule`。

新 DNA 必须位于主体上、可观察、可复用、可参数化、具有设计价值，并与已有字段和关系去重。背景、拍摄效果、污渍、损伤和偶然状态不是新 DNA。

## 四、证据与置信度

证据框必须位于主体框内。`evidence.region`、`design_elements[].region` 以及风格标签/候选的 `regions` 只能取 `target_object.visible_regions` 中的值或 `whole_object`；不得临时创造区域名。证据描述只写“看到了什么”，不写抽象风格结论。

- `direct + observed` 至少引用一条证据；
- `derived + computed` 至少引用源字段证据；
- `inferred + computed` 至少引用两条独立观察证据；
- 每个确认标签至少覆盖决定字段和独立辅助字段；
- 每个额外标签至少有一项不与其他标签完全重合的决定证据。

置信度建议：

- `0.90～1.00`：直接、清晰且定义唯一；
- `0.75～0.89`：证据较强，有轻微干扰；
- `0.55～0.74`：候选竞争明显，只作暂定候选；
- `<0.55`：弱候选或无法判断。

## 五、输出

完整结果必须满足：

- `schema_version="design_dna_multitag_extraction_v1.0"`；
- `knowledge_base_version="4.1"`；
- 顶层与嵌套结构通过 `schemas/design-dna-output.schema.json`；
- 结果只包含 JSON，不含 Markdown、解释、注释、路径、NaN、Infinity 或尾逗号；
- 空集合使用 `[]`，单值不可得使用 `null`；
- 稳定 ID、英文标签和标准枚举保持原样。

Schema 是字段结构与必填项的唯一权威；本文定义语义与决策顺序。提取器只生成结果，文件保存、命名、防覆盖和业务视图转换由宿主负责。

## 六、输出前自检

1. 只分析一个主物品，已隔离背景与道具；
2. profile、视角、适用性、可见性和计算状态一致；
3. 先规范 DNA，后风格标签；
4. `style_tags` 为 0～3 个 confirmed-only 标签，且每项 `confidence>=0.75`；
5. 每个标签独立通过门槛、颜色、证据和排除检查，未输出 TribeIdentity 等废弃 ID；
6. 每个标签对恰有一条成对仲裁，`style_id_a < style_id_b`；同区 conditional 已满足相应禁止或独立证据模式；
7. 多标签具有独立机制或区域，没有同义重复计票；
8. 单标签 dominance 为 1，多标签之和约为 1，且 `style_tags` 排序合法；
9. `candidate_ranking` 包含全部确认标签并严格排序；非 confirmed 候选 dominance 为 0，硬判通过但因标签对冲突降级时有 `main_conflicts`；
10. 证据、设计元素和风格区域只使用可见区域或 `whole_object`；
11. 组合摘要没有创造结论；
12. 低置信度、不可见或不可计算项已登记；
13. 所有数字有限，未出现 NaN 或 Infinity；
14. confirmed 标签的适用规则数与通过规则数均至少为 1；版本固定为 multitag v1.0 / KB 4.1，并通过 Schema。
