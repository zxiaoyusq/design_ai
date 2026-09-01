# KB 3.0 / Schema v4.0 回归评测量表

每例按 100 分评分；先检查一票否决，再按维度计分。`cases.jsonl` 中 `expected` 是该例的判定合同，显示名称不替代稳定 `style_id` 与 `confusion_group_id`。

## 一票否决

命中任一项，本例最高 40 分：

- 输出不可解析 JSON、违反 `design_dna_extraction_v4.0`，或引用不存在的证据；
- 同时分析多个主物品，或把背景、人物、道具、滤镜、运动模糊写入主体 DNA；
- 命中硬排除、缺决定锚点或缺独立辅助证据仍标记 `confirmed`；
- required 颜色写成 `not_applicable`，或风格命中未引用本次已确认且属于该风格 allowlist 的规范字段；
- 将混淆组共享表象当成决定性差异，或用 DNA-M13/M14 补足硬门槛；
- 输出未知、废弃或别名风格 ID；`QuietElegantLuxury` 不得作为新结果；
- 在规范字段中使用未知 ID，或让真 alias、legacy/compatibility_derived 兼容项重复计分；
- 由模型生成非空 `original_md_dimensions` 兼容投影；
- 混用三轴：把不可见/不可计算写成 `not_applicable`，或把确认不存在写成状态；
- 用 `list` 代替纯字符串 `multi_label`、输出值域外标签，或在依赖不全时生成 `computed derived`；
- 把真实材料、工艺、尺寸、重量、性能、随角变化、品牌/文化来源当作单图事实。

## 评分维度

| 维度 | 分值 | 通过标准 |
| --- | ---: | --- |
| 触发与单主体 | 10 | 正确处理单图、无图、多图和生成任务；只选一个主体并隔离干扰 |
| 品类与三轴状态 | 14 | `active_profiles` 有对象依据；适用、可见、计算状态各司其职，M15 正确排除 |
| 规范字段与去重 | 12 | 仅用 canonical ID、类型、值域、必要视角和证据模式；兼容投影权重为 0 |
| 风格硬判 | 18 | 颜色角色、硬门槛、决定锚点、独立辅助证据和硬排除逐项闭环 |
| 混淆仲裁 | 14 | 按 CG-01～CG-08 的分界写 `conflict_arbitration`，共享表象不重复计票 |
| 证据可追溯 | 12 | observed 至少一条证据；computed inferred 至少两条；风格命中引用已确认字段；bbox 位于主体内 |
| 不确定性 | 8 | 低于 0.75、不可见、不可计算或多候选均进入 `uncertain_fields`，概率约为 1 |
| 新 DNA 治理 | 6 | 先查规范字段与别名，再选 new_field/new_enum_value/new_relation_rule/new_module，并给差异与证据 |
| JSON 与计数 | 6 | 版本、枚举、类型、引用、候选排名和规则覆盖计数均合法 |

## 三轴与规范字段判分

- `direct`：可见时 `observed + not_requested`；缺视角时 `not_observable|unknown + not_requested`，值为 `null`。
- `derived|inferred`：必要视觉输入可见且依赖充分时 `observed + computed`；依赖不足时 `not_computable`，值为 `null`。
- 非直接字段不得用 `not_requested` 代替 `not_computable`。
- core 内的 `reference_computed` 缺参考库时必须 `not_computable`；当前单图 Skill 不激活 multi-face/reference/trend profile，M15 为 `profile_not_applicable`。
- `not_applicable` 只表示品类/profile 不适用，不进入 `design_elements` 或规则分母。
- 确认元素不存在使用值域内“无”或空列表，并保持 `observed + not_requested`；纯字符串标签集用 `multi_label`，结构化集合用 `list`，不得跨类型写通用 `none`。
- `computed derived` 必须具备注册表声明的全部可用源字段，并覆盖源字段证据；跨区域汇总使用 `whole_object`。
- 规范字段的 ID、类型、值域、必要视角、证据模式和适用 profile 以知识库与注册表为准；同一现象只保留一个规范字段。

## 混淆案例判分

- `positive`：必须得到 `expected.primary_style_id`；只有硬门槛、至少一个决定锚点、一个不同区域或机制的辅助证据全部成立且无硬排除时才可 `confirmed`。
- `boundary`：以每例 `expected` 为准。分界证据不可见时降为 `provisional|unclassified`；若另一候选的硬规则完整且混淆对象被明确排除，可确认另一候选。
- `negative`：`reject_style_ids` 中任何风格都不得成为主风格或次风格；候选可保留在 `candidate_ranking`，但须写缺失项、冲突或排除。
- `rule_coverage.applicable_rule_count = passed_rule_count + failed_rule_count + unknown_rule_count`；`not_applicable_rule_count` 不进入分母。
- `confirmed` 的失败数、未知数、缺失必要项和排除项都必须为 0；次风格也须独立通过同样规则。

| 混淆组 | 决定性边界 | 典型硬排除/降级点 |
| --- | --- | --- |
| CG-01 | 零增量 / 温润柔雾 / 克制增量 / 粉蜡低彩 / 明快中彩 | 只见“简洁、浅色”不足；颜色或表面不可靠时降级 |
| CG-02 | 局部精致增量 / 冷金属封闭秩序 / 暖金属主视觉 / 深色厚重表面 | 局部金属不等于金属主体；光源偏色不得确认暖金属 |
| CG-03 | 冷金属封闭秩序 / 外露连接 / 参数变化 / 信息系统 / 功能结构 / 外扩装甲 | 单螺丝、均匀孔阵、单数字、单挂绳均不足 |
| CG-04 | 流体单体 / 主动界面 / 秘仪符号 / 柔雾光学 / 强虹彩 / 有机异常光层 | 状态灯、摄影色散、普通暗光或单色光泽均不足 |
| CG-05 | 主体运动锚点 / 色彩本身主导 / 几何色块版式 | 背景运动模糊、闭合接缝、窗框、包边和普通腰线不是运动锚点 |
| CG-06 | 自然纹理 / 生长拓扑 / 有机×异常光层 / 精确×粗粝对照 | 背景自然物、普通圆角、暗色摄影、随机损伤均不得触发 |
| CG-07 | 经典重复 / 华饰密度 / 工艺结构 / 表达大图 / 可验证身份 / 几何色块 | 普通 Logo、未知来源符号、文化联想或纯结构分区不足 |
| CG-08 | 集成低噪基体×表达性复古重组 / 深色厚重表面 / 经典重复或镶边 | 通用功能件、结构边界、怀旧滤镜或单一深色不得确认 |

## 覆盖与验收

- CG-01～CG-08 每组必须至少各有 `positive`、`boundary`、`negative` 一例；当前最低覆盖为 8×3=24 例。
- 通用回归必须覆盖：单主体、输入边界、低质量、材质边界、profile 隔离、必要视角、值域、multi_label、派生依赖、风格 allowlist、兼容映射及新 enum。
- 单例 `>=90` 且无否决项为通过；整个回归集要求所有混淆组类型齐全、JSONL 每行可解析，且无否决项失败。
