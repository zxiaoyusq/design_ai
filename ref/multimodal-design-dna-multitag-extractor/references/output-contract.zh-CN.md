# 扁平多标签输出协议

适用于最终 `schema_version="design_dna_multitag_extraction_v1.2"` 与 `knowledge_base_version="4.1"`。模型阶段通过 `schemas/design-dna-model-output.schema.json` 输出 `design_dna_multitag_observation_v2`；宿主编译后的完整结果通过 `schemas/design-dna-output.schema.json`。

模型只负责经过字段准入后的视觉值、证据、风格候选、支持与冲突说明、不确定性和摘要。字段/风格静态元数据、模块清单、统计、排序和组合预设由宿主生成。

## 1. 顶层结构

最终结果必须包含：

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

`target_object` 只描述一个对象。`bbox_norm` 各值位于 0～1，且最小坐标小于最大坐标。背景、人物、道具及其他物品不得混入主体 DNA。

`active_profiles` 必须包含 `core`，只列有对象依据的单视图 profile。当前不得激活 multi-face、reference 或 trend profile；DNA-M15 必须以 `profile_not_applicable` 排除。

## 3. 规范字段状态

- `applicability_status` 只回答品类/profile 是否适用；
- `evidence_mode` 由字段注册表固定；
- `observability` 只回答必要输入是否可见；
- `computation_status` 只回答是否完成计算。

只输出 canonical `field_id`。纯字符串标签集合使用 `multi_label`，结构化集合使用 `list`；派生字段必须具备全部注册依赖和源证据。当前 `original_md_dimensions` 固定为 `[]`。

宿主再次检查字段准入，并按 `value-normalization.json` 处理显式别名、关系词和离散刻度。无法无损归一化的受控值不得猜测，必须转为未知或不确定。

## 4. style_result

`style_result` 只包含：

- `style_candidates`
- `derived_style_presets`
- `composition_summary`

不得出现一级/二级、父级、主/次风格、确认状态、`style_tags`、`candidate_ranking` 或 `pairwise_arbitrations`。

### 4.1 style_candidates

保存零到五个有真实视觉支持的候选。每个已输出候选包含：

- `rank`：从 1 连续递增；
- `style_id`、`label_en`、`label_zh`、`aliases`、`tag_kind`、`facet_ids`；
- `match_score`：0～100；
- `confidence`：0～1；
- `regions`：至少一个主体可见区域；
- `main_support`：至少一条可见支持；
- `main_conflicts`：可见的削弱因素，没有时为 `[]`。

宿主从风格注册表补全静态身份，并按 `(-match_score, style_id)` 稳定排序。候选不要求达到 0.75，也不使用旧版 confirmed 的硬规则闭环、dominance、状态或成对仲裁。未知、废弃和 identity 迁移记录不得作为候选；明显不匹配的拒绝项也不写入列表。

### 4.2 derived_style_presets

该数组不是模型输出。宿主由 `scripts/derive_style_presets.py` 仅根据 `style_candidates[].style_id` 和 `style-combination-presets.json` 确定性覆盖写入；无命中时为 `[]`。

每项包含稳定 `preset_id`、中英文显示名及实际参与匹配的 `matched_style_ids`。预设只用于展示和查询，不替代候选、不参与候选排序，也不能反向补足 DNA。

### 4.3 composition_summary

只总结候选的空间分布、主要视觉支持和整体组合，不得隐式增加候选或恢复主/次结构。

## 5. 证据、不确定项与新 DNA

所有 `evidence_refs` 必须指向存在的证据。`evidence.region`、设计元素区域及候选 `regions` 只能取 `target_object.visible_regions` 中的值或 `whole_object`。`direct + observed` 至少一条证据；`derived + computed` 覆盖源字段证据；`inferred + computed` 至少两条独立观察证据。

置信度低于 0.75、存在竞争、视角不足或不可计算的字段进入模型观察的 `uncertainties`，由宿主编译成最终 `uncertain_fields`。`novel_dna_elements` 只容纳知识库不能充分表达、位于主体上且可复用、可参数化的内容。

## 6. JSON 与宿主职责

- 输出只包含 JSON，不使用 Markdown 围栏、注释、尾逗号、NaN 或 Infinity；
- 中文描述使用简体中文；稳定 ID、英文标签和标准枚举保持原样；
- 模型只生成精简观察 JSON；
- 宿主负责静态元数据、字段规范化、候选排序、统计、组合派生、最终校验、保存及业务视图转换；
- 宿主不得新增视觉事实，也不得把候选升级或降级为确认状态。
