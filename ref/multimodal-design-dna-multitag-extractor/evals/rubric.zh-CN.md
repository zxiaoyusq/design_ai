# KB 4.1 / Multitag Schema v1.2 回归评测量表

每例按 100 分评分；先检查一票否决，再按维度计分。`cases.jsonl` 的 `expected.style_candidate_ids` 是图片中应输出的同层候选集合，顺序不表达主次；空数组表示没有足够可见支持的候选。

## 评测触发解释

只有 `MT-01`～`MT-05` 是本 Skill 的自然触发例，`should_trigger=true`。其余 75 例用于验证普通 DNA 请求仍路由到原版 Skill；显式加载本 Skill 后仍可执行结果回归。

## 一票否决

命中任一项，本例最高 40 分：

- 输出不可解析 JSON、版本不是 `design_dna_multitag_extraction_v1.2 / 4.1`，或引用不存在的证据；
- 任一数字为 NaN、Infinity 或其他非有限值；
- 输出 `parent_style_id`、`level_1`、`level_2`、`primary_style`、`secondary_styles`、`classification_status`、`style_tags`、`candidate_ranking` 或 `pairwise_arbitrations`；
- `style_candidates` 超过 5 个、出现重复 ID，或为凑数输出没有可见支持的候选；
- 任一候选缺少 `main_support`，或区域不属于主体可见区域且不是 `whole_object`；
- `tag_kind`、`facet_ids`、显示名或别名与风格注册表不一致；
- 输出 TribeIdentity 等废弃标签，或把身份信息当作风格而不是 IDG-05/07/09；
- 候选未严格按 `(-match_score,style_id)` 排列，或 rank 不从 1 连续递增；
- 模型阶段生成组合预设，或最终 `derived_style_presets` 与 Python 根据候选 ID 重算的结果不一致；
- 把拍摄条件、人物、背景、真实材料/工艺、尺寸、重量、性能或未经验证来源当作主体事实；
- 三轴状态、字段 ID、类型、值域、视角、派生依赖或证据闭环违反注册表。

## 评分维度

| 维度 | 分值 | 通过标准 |
| --- | ---: | --- |
| 触发与单主体 | 10 | 仅在明确扁平/多标签请求或点名本 Skill 时触发；只选一个主体并隔离干扰 |
| 品类与状态 | 12 | active_profiles 有对象依据；三轴各司其职，M15 正确排除 |
| 规范字段 | 16 | 只用 canonical ID、合法类型/值域/视角/依赖；兼容投影不计分 |
| 候选真实性 | 22 | 每个候选有直接可见支持，不输出纯名称联想或明确不匹配项 |
| 候选解释 | 12 | score/confidence 分工清晰，支持、冲突、区域和组合摘要一致 |
| 组合派生 | 8 | 仅按候选 ID 进行确定性派生，不反向补足候选或 DNA |
| 证据追溯 | 10 | 字段引用有效主体证据，区域一致 |
| 不确定性 | 5 | 低可信、不可见和不可计算字段均有登记 |
| 新 DNA | 3 | 先去重，再提出可观察、可复用、可参数化候选 |
| JSON 完整性 | 2 | 结构、枚举、统计、引用和版本均合法 |

## style_result 判分

### style_candidates

- 数量为 0～5，使用活动 `style_id`；
- 静态身份字段由宿主从注册表补全；
- 每个已输出候选至少有一条 `main_support`；
- `main_conflicts` 只记录图片中确实可见的削弱因素，没有时为 `[]`；
- `match_score` 为 0～100，`confidence` 为 0～1，二者不得混用；
- 严格按 `(-match_score,style_id)` 排列，rank 从 1 连续递增；
- 低于 0.75 仍可作为候选，不需要输出 confirmed、provisional 或 rejected 状态；
- 明显不匹配的风格不作为“拒绝项”保留。

### derived_style_presets

- 模型阶段不得包含该字段；
- 最终结果由 Python 仅根据 `style_candidates[].style_id` 覆盖写入；
- `preset_id`、显示名、参与匹配的候选及顺序与注册表重算结果完全一致；
- 该数组不进入候选排序，也不补足任何 DNA 或风格证据。

### composition_summary

必须是非空文本，说明候选的区域、主要支持和组合关系；不得创造新候选、重复排名或恢复主/次语义。没有候选时简洁说明图片中没有足够支持。

## 混淆与多候选案例

- positive：`expected.style_candidate_ids` 中的风格应有清楚支持；
- boundary：可保留有视觉支持但信心较低的候选，并把边界写入 `main_conflicts`；
- negative：没有真实支持时使用空候选数组，不输出 rejected 记录；
- 多候选允许共享整体语境，但每项都应有自身可说明的视觉支持；
- 组合预设直接使用最终候选集合，因此不要为了命中组合而补造候选。

## 规范字段与证据

- direct：`observed|not_observable|unknown + not_requested`；
- derived/inferred：依赖充分时 `observed + computed`，不足时 `not_computable`；
- reference-computed 缺参考集时为 `not_computable`；当前单图不激活 multi-face/reference/trend；
- 确认不存在用类型内“无”或空列表并保持 observed；
- multi_label 只含登记字符串，list 用于结构化条目；
- 每个 observed 字段至少一条证据，computed inferred 至少两条独立观察证据；
- 证据、设计元素和候选区域只能使用 `target_object.visible_regions` 中的值或 `whole_object`。

## 覆盖与验收

- 当前基准共 80 例，ID 唯一且 JSONL 每行可解析；
- 另有 14 条 Python 组合派生用例，覆盖空结果、误触发阻断、多预设共存及全部 12 个预设；
- 单例 `>=90` 且无否决项为通过；全套不得出现结构、值域或证据否决项。
