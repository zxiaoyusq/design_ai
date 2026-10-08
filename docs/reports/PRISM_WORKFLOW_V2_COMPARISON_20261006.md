# 同事 v2.0 与本工程棱镜流程的差异（2026-10-06）

对比对象是 `ref/老师对接/最新完整流程1006/棱镜_完整工作流与17个Skills_v2.0_20261006.zip`、工程活跃 `.agents/skills/`，以及本工程实际执行的 `h01_all13_20261005_expanded`。该对比发生在迁移之前，仅分析源码、规则和既有回执。之后用户已明确要求以同事v2为准迁移；本报告的旧优化建议已被覆盖，旧Skill证据入口改指升级前备份。当前实施见 `PRISM_COLLEAGUE_V2_PROJECT_MIGRATION_20261006.md`。

**结论：最终输出可能明显不同，主要原因是上游归组与选向、视觉家族的形成方式、候选预算和成板验收口径不同。R5 DNA核心及便携ID/CMF原生算法基本同源，不能把v2理解成全面换了更强的视觉模型。**

我们的交接包有两层：项目活跃的趋势/用研/H01适配版，以及便携组合版。与便携版相比，同事包的大部分底层算法相同；与实际13方向执行链相比，差异更大。下面以实际项目行为为主。

## 最影响效果的差异

| 环节 | 本工程实际流程 | 同事v2 | 对结果的影响 |
|---|---|---|---|
| 趋势归组 | 原子审美要点归组；一篇文章的不同要点可支持多个方向；默认每趋势至少3个来源组、最多100条 | 每篇文章仅一个主归属；supported才进入H01；编译器没有相同的3来源/100条硬门 | 同一批文章会产生不同簇、证据量和关联图片池。不能只比较趋势名称 |
| 用研与H01 | 接收本工程用户JSON和原子观察；默认extension；要求逐候选审计avoid/conditional/带条件的观察；数量按任务 | 接收预整理units或原生研究dataset；默认exploration、最多12候选、选择5，可显式配置；mandatory negative ledger主要覆盖dislike | 输入通道、可选择资格、探索假设与数量会变。要延续13方向，必须显式对齐模式与数量 |
| 视觉条件形成 | 先固定13个家族，再让已有DNA做全库筛选；跨品类提案须符合原冻结条件 | 原图低成本预览时核可见性、来源容量、主关系、第二强信号和处理动作，再固化material-brief | 可能减少定义过窄或缺素材的问题；不能为通过率事后偷偷改条件 |
| 候选与额度 | 累计原图24→40→60、详细ROI12、整板2次，计入历史、失败和在途 | 更广候选池，最终约10图；容量和预算由任务配置，不套用这些固定累计上限 | 换图/修图空间更大，但模型消耗可能增加，扩大候选本身不保证成板 |
| 品质门 | partial_target/basic/limited可进入实际独立ROI复核；必要关系和载体确实可见才通过 | 原生品质验收要求exact_target和clear，basic需确认；声明状态政策减少把范围外未知误判为缺口 | 直接换原生链可能重新收紧刚放宽的门，不是普遍放宽品质 |
| 裁切与修复 | 已有真实ROI、修订溯源、独立原图/视窗/整板审阅，但整板最多2次 | 新增独立裁切/展示增强Skill、逐图处理台账、同问题最多3轮定点修订 | 更早计划统一尺度、补源或替换，比只在最后发现问题更有针对性；不是自动重发失败模型请求 |
| 数量和PASS | 本轮项目4–8硬底线、目标6；明确为local-existing-r5-board-v1，不宣称原生H2通过 | 默认约10；原生ID源码硬要求minimum≥10，CMF按冻结项目政策（minimum可≥1） | H008的5张和H015的4张不能直接升级为新版原生ID通过；数量门更高可能降低通过率 |

## 对我们现有几个卡点的具体意义

- **H004**：真实group选出6张，但board发现整段衣面、局部近景和窄条墙纸尺度混排，墙纸枝条/花形细节不足，负向颜色处理亦有缺口。新版主/次信号和素材动作可以前置发现问题；统一取景、找清楚同源或替换有针对性。增强不能证明原图看不清的花形。
- **H016**：真实group选出5张，board指出条纹外衣裁掉双袖末端。扩大ROI是具体可修问题。我们已有修ROI的能力，实际差别是前置检查时机和已用完整板额度；新版不是凭空新增了本地没有的裁切能力。
- **H003**：现家族要求闭合/收束轮廓及支持收束的分片、叠合或关节。大量静态柜面/几何闭合边界被拒，并非仅因跨品类，也不是一律要求两种状态照片。新版可在正式冻结前检查这种定义是否有足够独立材料，但不能借“仅当前状态”政策取消已明确要求的收束关系。
- **H007**：同事CMF仍只支持surface/same_object_interface，多个端点须同物件。没有等价的本地paired-surfaces-v2：各物件独立COL表面、跨对象REL上下文、U52/U56场合及基色接受分组。ID的explicit_ensemble比较整件形态组合，不能替代跨物件配色合同。全量覆盖可能恢复原先误伤；本地3个配对候选只通过局部复核，仍缺第4独立来源和后续用户接受/整板判断。

## DNA和原生算法到底有没有换

逐字节比对显示，活跃R5的10份assets（字典、上下文、Prompt、Schema及源解析/精修脚本）和`engine.py`与同事版相同。IDv5、CMFv4主要production源码、原生qualityv2协议/Prompt亦与本地便携组合相同。

同事新增的是选材合同、处理与审阅流程、移植修补、可选compact-wire准备/解封，以及future-negative适配。compact-wire本身不发模型；future-negative保留原否定/未决，不取消当前冲突，也不替代H007跨物件配对。

实际结果仍可能受宿主影响：同事R5要求gpt-6-sol/low/Codex CLI，本工程在用户授权下可使用DeepAgents和可选模型，并有不同的有效Prompt外壳。比较算法效果时须对齐图像、目标、规则、模型、推理档位和Prompt。不能仅因v2版本号重新提取8千张已有DNA。

## 建议如何吸收新版

1. 继续复用当前DNA和完整文本覆盖，保留全部失败/未决；先做输入契约适配，不把两种H01协议文件直接互换。
2. 若比较同一任务，显式保持13方向、extension或约定模式、同样的原话/条件、相同数量目标和成本预算；默认12候选/选择5不是等价实验。保留全部19历史提案时需max≥19（原生允许配置到20）。
3. 优先吸收material-brief的低成本预览、来源容量、第二强信号、逐图处理动作，以及裁切后再看；这些直接针对H004/H016卡点。
4. 保留本工程明确采用的品质复核放宽、累计预算和H007配对合同。若改为原生ID最少10图，先声明数量/实现版本和预算变更，不把4/5图结果伪装成新原生PASS。
5. 先做少量相同候选的受控对照，再决定是否迁移。此次分析不启动该实验。

同事包提供一个20原图、最终10图的linear-relief单板案例，第一次因花色干扰更换成员；这不是我们的8,461张、13方向新流程对照。其验证报告明确无新付费/全库批次、未证明新的视觉准确率。因此以上是规则与源码的影响分析，不能断言哪一版全面更好。

## 可核查来源

同事原包与总说明：

- [START-HERE](/root/dev/work/design_ai/ref/老师对接/最新完整流程1006/START-HERE.md)
- [完整工作流HTML](/root/dev/work/design_ai/ref/老师对接/最新完整流程1006/完整工作流.html)
- [v2原包](/root/dev/work/design_ai/ref/老师对接/最新完整流程1006/棱镜_完整工作流与17个Skills_v2.0_20261006.zip)

下列同事路径均相对ZIP内`棱镜工作流_v2/`，解压后可以直接查：

- `skills/prism_skill_support/scripts/trend_text.py:49–81`：文章主归属/支持/排名；`references/trend-proposal-format.md:21,43`。
- `skills/prism-h01-semantic-handshake/scripts/h01_core/h01.py:72–74,134,163–177,243–249`：模式、数量、负向与范围；`h01_core/research.py:31`：原否定通道。
- `skills/prism-visual-family/SKILL.md:21–25`：预览与来源容量校准。
- `skills/prism_skill_support/references/material-contract.md`：主/次信号、处理动作和前置冻结。
- `skills/prism_skill_support/runtime/prism_sidecars/quality_selected_target_v2/protocol.py:261,277`：exact/clear；`references/declared-visible-scope-policy.txt`：声明范围解释。
- `skills/prism_skill_support/runtime/prism_runtime/clustering/id_reference_board_v5/protocol.py:52–53`：ID最低10；`cmf_reference_board_v4/protocol.py:38,123–127`：同表面/同物件；CMF数量在52–53行另按显式政策。
- `skills/prism-crop-enhancement/SKILL.md`、`skills/prism-board-review/SKILL.md`、`references/review-contract.md`：处理及独立审阅责任。
- `validation/validation-report.json`与`validation/observed-v2-tests.json`：实跑与离线验证边界。

本工程来源：

- [趋势规则](/root/dev/work/design_ai/.agents/legacy-skills/prism_before_colleague_v2_20261006/prism-trend-themes/SKILL.md:37)、[要点归组](/root/dev/work/design_ai/.agents/legacy-skills/prism_before_colleague_v2_20261006/prism-trend-themes/references/selection.md:14)。
- [活跃H01](/root/dev/work/design_ai/.agents/legacy-skills/prism_before_colleague_v2_20261006/prism-h01-semantic-handshake/SKILL.md:26)、[H01校验](/root/dev/work/design_ai/.agents/legacy-skills/prism_before_colleague_v2_20261006/prism-h01-semantic-handshake/scripts/handshake.py:320)。
- [累计预算](/root/dev/work/design_ai/.agents/legacy-skills/prism_before_colleague_v2_20261006/prism_skill_support/references/budgeted-visual-selection.md)、[真实配置](/root/dev/work/design_ai/data/result/visual_workflow/h01_all13_20261005_expanded/visual-budget-policy.json)。
- [品质复核入口](/root/dev/work/design_ai/data/result/visual_workflow/h01_all13_20261005_expanded/preparation/native_bridge.py:243)、[独立ROI/板审](/root/dev/work/design_ai/data/result/visual_workflow/h01_all13_20261005_expanded/preparation/run_board_models.py:15)。
- [实际13家族](/root/dev/work/design_ai/data/result/visual_workflow/h01_all13_20261005_expanded/visual-families.json)、[本轮结果](/root/dev/work/design_ai/data/result/visual_workflow/h01_all13_20261005_expanded/codex61_20261006/round-result.json)、[跨物件配对](/root/dev/work/design_ai/backend/app/services/visual_workflow/paired_surfaces.py:15)。
