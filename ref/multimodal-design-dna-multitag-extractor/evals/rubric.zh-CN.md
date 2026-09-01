# KB 4.1 / Multitag Schema v1.1 回归评测量表

每例按 100 分评分；先检查一票否决，再按维度计分。`cases.jsonl` 的 `expected.style_tag_ids` 是已确认同层标签集合，顺序不表达主次；`provisional_candidate_ids` 只表示应保留为暂定候选的标签。

## 评测触发解释

只有 `MT-01`～`MT-05` 是本 Skill 的自然触发例，`should_trigger=true`。其余 75 例 `should_trigger=false`，用于验证普通 DNA 请求仍路由到原版 Skill；显式加载本 Skill 后仍执行其结果回归。

## 一票否决

命中任一项，本例最高 40 分：

- 输出不可解析 JSON、版本不是 `design_dna_multitag_extraction_v1.1 / 4.1`，或引用不存在的证据；
- 任一数字为 NaN、Infinity 或其他非有限值；
- 输出 `parent_style_id`、`level_1`、`level_2`、`primary_style` 或 `secondary_styles`；
- `style_tags` 超过 3 个、包含非 confirmed 标签，或为凑数输出多个标签；
- 标签缺硬门槛、决定锚点、独立辅助证据、required 颜色或命中硬排除仍被确认；
- confirmed 标签的 `confidence<0.75`；
- confirmed 标签的 applicable 或 passed 规则数为 0；
- `tag_kind`、`facet_ids`、显示名或别名与风格注册表不一致；
- 输出 TribeIdentity 等废弃标签，或把身份信息当作风格而不是 IDG-05/07/09；
- confirmed 标签未出现在完整 `candidate_ranking`，或两处的身份、dominance、regions、状态不一致；
- candidate_status 非 `confirmed|provisional|rejected`，provisional/rejected 的 dominance 不为 0，或非 confirmed 候选在 `hard_rule_passed=true` 时没有 `main_conflicts`；
- 候选未严格按 `(-match_score,style_id)` 排列，或 rank 不从 1 连续递增；
- 单标签 dominance 不为 1、多标签 dominance 之和不约等于 1、`style_tags` 未严格按 `(-dominance,-match_score,style_id)` 排列，或把 dominance、confidence、match_score 混为一个值；
- 返回标签对缺少、重复或多出 `pairwise_arbitrations`，未满足 `style_id_a < style_id_b`，关系/作用域与注册表不符，或 decision 不是 `coexist`；
- 同时确认适用作用域内的 exclusive 标签，或 conditional 条件未满足仍共存；
- conditional 同区冲突在 `forbidden` 模式仍共存，或在 `independent_evidence` 模式缺少双方独占核心字段、独占字段证据或仲裁引用；
- 同一区域同一物理事实被重复用作多个标签的独立决定证据；
- `requires` 未按 `target_quantifier="any|all"` 满足仍确认源标签，或用 `implies` 绕过目标标签硬门槛；
- 模型阶段生成组合预设，或最终 `derived_style_presets` 与 Python 根据 confirmed 标签重算的结果不一致；
- 把拍摄条件、人物、背景、真实材料/工艺、尺寸、重量、性能或未经验证来源当作主体事实；
- 三轴状态、字段 ID、类型、值域、视角、派生依赖或证据闭环违反注册表；
- `evidence.region`、`design_elements[].region` 或风格标签/候选 `regions` 不属于 `target_object.visible_regions` 且不是 `whole_object`。

## 评分维度

| 维度 | 分值 | 通过标准 |
| --- | ---: | --- |
| 触发与单主体 | 10 | 仅在明确扁平/多标签请求或点名本 Skill 时触发；只选一个主体并隔离干扰 |
| 品类与状态 | 12 | active_profiles 有对象依据；三轴各司其职，M15 正确排除 |
| 规范字段 | 12 | 只用 canonical ID、合法类型/值域/视角/依赖；兼容投影不计分 |
| 单标签硬判 | 18 | 每个 style_tag 独立闭合颜色、门槛、决定/辅助证据与排除规则 |
| 标签组合 | 16 | 关系、作用域、依赖、成对仲裁和 composition_summary 一致，无重复机制 |
| 强度与候选 | 10 | score/confidence/dominance 分工清晰；候选完整、排序与状态合法 |
| 证据追溯 | 10 | 字段、标签和仲裁均引用有效主体证据，区域一致 |
| 不确定性 | 6 | 低可信、不可见、不可计算及暂定边界均有登记 |
| 新 DNA | 4 | 先去重，再提出可观察、可复用、可参数化候选 |
| JSON 完整性 | 2 | 结构、枚举、计数、引用和版本均合法 |

## style_result 判分

### classification_status

- `confirmed`：必须有 1～3 个 `style_tags`；
- `unclassified`：必须 `style_tags=[]` 且 `pairwise_arbitrations=[]`；可以有 provisional candidates；
- 不允许其他状态。

### style_tags

- 每项必须是活动标签并与 `style-registry.json` 一致；
- facet 只作多归属导航；37 个 atomic 使用 similarity_weight=1，仅 MysticOrganic 为 active composite/0；
- `hard_rule_passed=true`，applicable 与 passed 均至少为 1，失败数和未知数为 0，缺失项和排除项为空；
- `confidence>=0.75`；
- core/auxiliary 命中必须引用该标签 allowlist 中已确认的规范字段；
- 每项至少两条证据，并至少覆盖决定字段和不同字段/区域/机制的辅助证据；
- 单标签 dominance 为 1；多标签 dominance 总和约为 1；数组严格按 `(-dominance,-match_score,style_id)` 排列。

### derived_style_presets

- 模型阶段不得包含该字段；
- 最终结果由 Python 仅根据 confirmed `style_tags[].style_id` 覆盖写入；
- `preset_id`、显示名、参与匹配的原子标签及顺序必须与注册表重算结果完全一致；
- 该数组不占 dominance、不进入候选排序，也不补足任何 DNA 或风格证据。

### candidate_ranking

- 必须包含全部 `style_tags`，也可包含 provisional/rejected 候选；
- `confirmed` 候选 dominance 大于 0 且与对应 style_tag 一致；其余固定为 0；
- provisional/rejected 的 `hard_rule_passed` 可为 true 或 false；若为 true，表示自身门槛通过但因标签对冲突降级，且 `main_conflicts` 非空；
- 全局严格按 `(-match_score,style_id)` 排列，rank 从 1 连续递增；排序不构成主次；
- 边界例的 `provisional_candidate_ids` 必须对应 `candidate_status="provisional"`；
- `reject_style_ids` 不得进入 style_tags，通常应以 rejected 候选记录主要冲突。

### pairwise_arbitrations

若确认标签数为 n，必须有 `n×(n-1)/2` 个不重复无序标签对。字段含 `style_id_a`、`style_id_b`、`relation`、`scope`、`decision`、`reason` 和证据。

- relation 只能为 `compatible|exclusive|conditional`；
- scope 只能为 `global|same_region_same_mechanism|cross_region_or_mechanism`；
- 返回标签对 decision 必须为 `coexist`；
- 显式关系优先于 default；未登记组合按默认关系执行；
- conditional 同区冲突按 `same_region_coexistence` 执行禁止或双方独占核心证据门槛；
- 同区域同机制必须排除近义重复，跨区域或独立机制仍须分别过门槛。

### composition_summary

必须是非空文本，说明已确认机制的区域、分工和组合；不得创造新标签、重复排名或恢复主/次语义。未分类时说明规则未闭合的原因。

## 多标签专项案例

- `MT-01`：KineticEnergy 与 SaturatedBold 由动势和主色两套独立证据共存；
- `MT-02`：NaturalTextures 与 BiomorphicForm 由表面纹理和形态拓扑共存；
- `MT-03`：FreshJoy 与 SaturatedBold 在同一主色区域按 conditional 边界二选一；
- `MT-04`：PureMinimalism 与 RefinedMinimalism 为 global exclusive，不得共存。
- `MT-05`：ClassicPrestige 与 DecorativeLuxury 在同区由两套独占纹饰字段及证据共存。

多标签不是必得分项。若只有一个标签完整通过，正确输出单标签优于补足第二标签。

## 混淆组判分

CG-01～CG-08 继续用于召回与边界校验，但不形成一级分类。每组至少覆盖 positive、boundary、negative：

- positive：`expected.style_tag_ids` 中的标签必须独立确认；
- boundary：通常为 `unclassified + style_tags=[]`，并保留指定 provisional candidates；
- negative：`reject_style_ids` 不能进入 style_tags，可在候选中写 rejected 与冲突；
- 共享表象不可作为两个标签的独立决定证据。

CG-07 不含身份风格标签。名称、Logo、角色、联名或社群身份只记录到 IDG-05/07/09；若图形本身满足 ExpressiveMotifs 等活动风格，仍须独立通过该风格硬门槛。

## 规范字段与证据

- direct：`observed|not_observable|unknown + not_requested`；
- derived/inferred：依赖充分时 `observed + computed`，不足时 `not_computable`；
- reference-computed 缺参考集时为 `not_computable`；当前单图不激活 multi-face/reference/trend；
- 确认不存在用类型内“无”或空列表并保持 observed；
- multi_label 只含登记字符串，list 用于结构化条目；
- 每个 observed 字段至少一条证据，computed inferred 至少两条独立观察证据；
- 证据、设计元素和风格区域只能使用 `target_object.visible_regions` 中的值或 `whole_object`；
- 风格标签只引用本次已确认、且在该标签机器 allowlist 内的字段。

## 覆盖与验收

- CG-01～CG-08 每组各有 positive、boundary、negative，共 24 例；
- 通用回归覆盖输入、单主体、低质量、材质、profile、视角、值域、multi_label、派生依赖、allowlist、兼容映射及新 enum，共 19 例；
- 多标签回归覆盖 compatible 共存、conditional 禁止、conditional 同区独立证据与 exclusive 冲突，当前 5 例；
- 扩展风格回归覆盖 8 个新增原子标签的 positive、boundary、negative、coexistence，共 32 例；
- 当前基准共 80 例，ID 唯一且 JSONL 每行可解析；
- 另有 14 条 Python 组合派生用例，覆盖空结果、误触发阻断、多预设共存及全部 12 个预设；
- 单例 `>=90` 且无否决项为通过；全套不得出现结构、关系或证据否决项。
