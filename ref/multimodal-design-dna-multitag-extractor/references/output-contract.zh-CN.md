# 扁平多标签输出协议

适用于最终 `schema_version="design_dna_multitag_extraction_v1.1"` 与 `knowledge_base_version="4.1"`。模型阶段通过 `schemas/design-dna-model-output.schema.json` 输出 `design_dna_multitag_observation_v1`；宿主编译后的完整结果通过 `schemas/design-dna-output.schema.json`。

模型阶段只负责经过字段准入后的视觉值、证据、风格判断、组合关系理由、不确定性和业务摘要。字段/风格静态元数据、模块清单、统计值、排序、confirmed 候选镜像及可推导证据引用由 `scripts/compile_model_output.py` 确定性生成；宿主同时复核 profile/视角、受控值域、低置信镜像与风格证据闭环。

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

禁止添加未定义顶层字段。空集合使用 `[]`，单值不可得使用 `null`。

## 2. 单主体与模块

`target_object` 只描述一个对象。`bbox_norm` 各值位于 0～1，且满足最小坐标小于最大坐标。背景、人物、道具及其他物品不得混入主体 DNA。

`active_profiles` 必须包含 `core`，只列有对象依据的单视图 profile。当前不得激活 multi-face、reference 或 trend profile；DNA-M15 必须以 `profile_not_applicable` 排除。

## 3. 规范字段状态

- `applicability_status` 只回答品类/profile 是否适用；进入 `design_elements` 的字段必须适用。
- `evidence_mode` 由字段注册表固定。
- `observability` 只回答必要输入是否可见。
- `computation_status` 只回答是否完成计算。

`direct` 固定 `not_requested`；`derived|inferred|reference_computed` 只能为 `computed|not_computable`。不可见或不可计算时值为 `null`。确认不存在使用 enum 的“无”或空列表，并保持 `observed`。

只输出 canonical `field_id`。纯字符串标签集合使用 `multi_label`，结构化集合使用 `list`；派生字段必须具备全部注册依赖和源证据。当前 `original_md_dimensions` 固定为 `[]`。

模型开始字段提取前必须先按目标视角与 `active_profiles` 获取准入集合。宿主会再次移除不适用字段，并按 `value-normalization.json` 处理显式别名、从描述性关系中提取标准关系词、把 ordinal 与规定的强度值量化到 `0|25|50|75|100`。无法无损归一化的受控值不得猜测，必须转为未知或不确定。

## 4. style_result

`style_result` 由以下部分组成：

- `classification_status`
- `style_tags`
- `derived_style_presets`
- `candidate_ranking`
- `pairwise_arbitrations`
- `composition_summary`

结果中不得出现一级/二级、父级或主/次风格字段。

### 4.1 classification_status

- `confirmed`：`style_tags` 含 1～3 个标签；
- `unclassified`：`style_tags=[]`。有支持但规则未闭合的项仍可保留在完整候选排序中。

### 4.2 style_tags

`style_tags` 只包含 confirmed 标签，最多三个。每个标签必须使用活动 `style_id`，并包含 Schema 规定的中英文显示名、匹配度、置信度、主导度、作用区域、规则覆盖、颜色状态、决定与辅助命中、缺失项、排除项和证据引用。

`tag_kind` 与 `facet_ids` 必须原样取自风格注册表，不由单次图片推断。facet 是可多归属的导航/检索元数据，不形成层级。当前 38 个活动标签中，37 个 atomic 的 `similarity_weight=1`；仅 MysticOrganic 为 composite/0。输出中的 match_score 不覆盖注册表权重。

TribeIdentity 已废弃，不能出现在 `style_tags` 或 `candidate_ranking`。可见文字与图标写入 `IDG-05`，身份显性度写入 `IDG-07`，经批准参考库确认的实体写入 `IDG-09`；身份字段不生成风格标签，也不因其显眼而绕过图形类风格的自身门槛。

确认标签必须同时满足：

- `hard_rule_passed=true`；
- `confidence>=0.75`；
- `applicable_rule_count>=1` 且 `passed_rule_count>=1`；
- `failed_rule_count=0` 且 `unknown_rule_count=0`；
- `missing_required_items=[]`、`exclusion_hits=[]`；
- required 颜色为通过；
- 决定命中和辅助命中分别引用允许的规范字段；
- 至少有一项独立辅助证据；
- `regions` 非空并属于主体可见区域或 `whole_object`。

三个数值不可互换：

- `match_score` 为 0～100 的规则匹配度；
- `confidence` 为 0～1 的正确概率；
- `dominance` 为 0～1 的相对视觉贡献。

若有确认标签，dominance 总和应约为 1；单标签固定为 1。`style_tags` 严格按 `(-dominance,-match_score,style_id)` 排序，但不形成主/次语义。

### 4.3 derived_style_presets

该数组不是模型输出。宿主在原子标签确认完成后，由 `scripts/derive_style_presets.py` 仅根据 confirmed `style_tags[].style_id` 和 `style-combination-presets.json` 确定性覆盖写入；无命中时为 `[]`。

每项包含稳定 `preset_id`、中英文显示名及实际参与匹配的 `matched_style_ids`。预设只用于派生展示和查询，不进入 `style_tags`、不占 dominance、不参与候选排序，也不能反向补足 DNA 或风格证据。最终校验器会重算并拒绝缺失、伪造、过期或顺序不一致的派生值。

### 4.4 candidate_ranking

保存完整候选排序，必须覆盖全部 `style_tags`，也可包含活动标签中的暂定或未通过项；未知、废弃或 identity 迁移记录不得作为候选。`candidate_status` 只能为 `confirmed|provisional|rejected`：confirmed 候选的 dominance 大于 0 且与对应标签一致，provisional/rejected 固定为 0。非 confirmed 候选的 `hard_rule_passed` 可为 true 或 false；若为 true，表示自身门槛已通过但因标签对冲突降级，且 `main_conflicts` 必须非空。候选严格按 `(-match_score,style_id)` 排列，排名从 1 连续递增；确认标签在两处的身份、主导度、区域和硬判状态必须一致。排序不等于主/次。边界未知、门槛未闭合或关系冲突未解决的候选不得进入 `style_tags`。

### 4.5 pairwise_arbitrations

对 `style_tags` 的每个无序标签对恰好输出一条，数量为 `n×(n-1)/2`。每对必须按字典序满足 `style_id_a < style_id_b`。单标签或空标签时必须为 `[]`；返回标签对的 `decision` 必须为 `coexist`。

关系值只能为 `compatible|exclusive|conditional`，作用域只能为 `global|same_region_same_mechanism|cross_region_or_mechanism`，并与 `tag-relations.json` 一致。每项应引用有助于证明两标签独立机制、区域及关系条件的证据。

适用作用域内的 `exclusive` 标签不得共同返回。`conditional` 未满足时只能保留一个标签；另一个进入候选。未登记组合按 `default_pair_relation` 处理。

对同区 conditional 冲突 facet，`same_region_coexistence=forbidden` 时不得共存；`independent_evidence` 时须有双方独占核心字段、独占字段证据，且仲裁引用两侧独占证据。跨区照常按关系条件判断。

### 4.6 composition_summary

只总结已确认标签的空间分布、机制分工与整体组合，不得充当证据、隐式增加标签或恢复主/次结构。空标签时说明未分类及候选尚未闭合的原因。

## 5. 关系依赖

关系注册表中的 dependency 只有：

- `requires`：按 `target_quantifier="any|all"` 检查已确认目标；未满足时源标签不能确认；
- `implies`：按量词召回目标进入 `candidate_ranking`，目标仍须独立通过硬门槛。

任何关系都不能绕过标签自身的 required 颜色、决定锚点、辅助证据或硬排除。

## 6. 规则计数与证据

`applicable_rule_count = passed_rule_count + failed_rule_count + unknown_rule_count`，`not_applicable_rule_count` 不进入分母；confirmed 标签的 applicable 与 passed 均至少为 1。

所有 `evidence_refs` 必须指向存在的证据。`evidence.region`、`design_elements[].region` 以及风格标签/候选的 `regions` 只能取 `target_object.visible_regions` 中的值或 `whole_object`。`direct + observed` 至少一条；`derived + computed` 覆盖源字段证据；`inferred + computed` 至少两条独立观察证据。每个额外确认标签必须有不完全重合的决定证据，防止同一现象生成多个近义标签。

## 7. 不确定字段与新 DNA

置信度低于 0.75、存在竞争、视角不足或不可计算的已有字段应进入模型观察的 `uncertainties`，并保留可观察性、置信度和原始证据。宿主将其编译为最终 `uncertain_fields`；模型无需在 `design_observations` 重复同一低置信字段。候选概率之和由宿主归一化；无可靠候选时使用空数组。

`novel_dna_elements` 只容纳知识库不能充分表达、位于主体上且可复用、可参数化的内容。`new_enum_value` 只能指向已有 enum 字段；没有可靠候选时输出 `[]`。

## 8. JSON 与宿主职责

- 输出只包含 JSON，不使用 Markdown 围栏、注释、尾逗号、NaN 或 Infinity。
- 中文描述使用简体中文；稳定 ID、英文标签和标准枚举保持原样。
- 模型只生成精简观察 JSON；宿主负责完整结构编译、组合预设派生、最终校验、保存及业务视图转换。
- 宿主只允许执行不增加视觉事实的保守整理；风格命中不在 allowlist、引用字段无可用值、区域没有对应证据或规则闭环不足时，将 confirmed 标签降为 provisional。
