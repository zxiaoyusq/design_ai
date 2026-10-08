# 合并后的完整流程、输入与输出

总入口为`prism-workflow`，以下13项是实际业务职责；旧网页兼容名不重复算步骤。每个入口路径为`.agents/skills/<名称>/SKILL.md`，原生源码由prism_skill_support及同事原包供内部复用。合并的是操作入口，原算法、独立看图与调用台账分别保留。

| 序号 | 阶段／Skill | 输入 | 输出 | 责任与衔接 |
|---|---|---|---|---|
| 1 | 项目约定：prism-run-contract | 当前设计问题、资料范围、已有状态、模型、预算、候选容量及最终数量、执行/代选授权 | project.frozen.json、state.json、输入路径绑定、阶段与复用计划 | 开始/恢复先登记，不把候选量等于最终10图；准备不解除暂停 |
| 2 | 用研证据整理：prism-research-intake | 原报告/PPT、人物对应、页码和实际原话/回答/图片出现关系 | raw-evidence、媒体出现表、来源SHA、reviewed研究输入 | 已有完整整理输入可复用；原话/品牌/愿望/分析笔记分开，不猜喜欢 |
| 3 | 趋势文字聚类：prism-trend-semantic-clustering | 文章标题及全文/摘要、文章ID、来源、日期、图片URL旁表 | trend-clusters.json、text-catalogue.json、ranking.json、coverage.json | 每文一个主归属，多义关联另存；supported主成员进H01，排名不是热度 |
| 4 | 用研语义聚类：prism-research-semantic-clustering | reviewed units或原生dataset；人物/原话/态度/对象/条件/来源 | clusters.json、memberships.jsonl、coverage-ledger.jsonl、summary.json、完整dataset/run及handshake-input.json | 区分共同偏好、单人线索、设计议题/背景；保留反证与直接支持通道；与3可独立并行 |
| 5 | 第一次语义握手：prism-h01-semantic-handshake | 完整用研dataset/run、趋势簇/文字目录、设计问题与模式 | candidate-directions.json、accepted.json、双侧原文引用、负向审计与未决 | 产出探索/设计资格，不是图片或成板已通过 |
| 6 | 方向选择：prism-direction-selection | 合法H01候选、原证据/边界、可用文章来源、当前选择/代选权限 | 原生selection.json、decision-log、ID/CMF分支、选择身份与理由 | 真正确定本次做哪些方向，不能把pending模板当批准；交7 |
| 7 | 视觉转译与选材：prism-visual-material-planning | selection、语义边界、设计参考、项目政策、文章与图片清单/来源、可选旧DNA | 冻结visual-family/material-brief、metadata-pool、原图manifest、逐图material-plan、冻结候选池、容量/证据缺口 | 具体主关系/必要证据/允许变化/干扰/尺度，与素材预览相互校准后冻结；规划包不授视觉PASS |
| 8 | DNA提取/复用：prism-dna-sol-r5 | 已选范围中的原图及身份、可复用原R5结果、当前明确的执行授权 | result.json、原ID/CMF观察及at、known/unknown/pending/invalid、原prompt/schema/request/answer/receipt | 冻结Sol R5；真实覆盖时复用，scope_gap定点处理，不因入口合并重提全库 |
| 9 | 单图参考准备：prism-reference-image-preparation | 冻结brief、单图计划、原图和来源、R5观察/位置、已有真实品质包（可选） | reference-material包：target_binding、quality_bundle、comparison_view、crop_review、provenance、action_log、candidate_eligibility、gaps；可选display_variant_ref | 定位/品质/实际裁片闭合；原生品质与独立裁片阅读不能省；ready_for_grouping不等板通过 |
| 10 | 视觉选组：prism-visual-grouping | 显式branch、冻结brief/候选manifest、R5、9的真实绑定/品质/原图/裁片及审阅、项目来源、原负向/义务 | 原生prepared/grouping、共同关系及精选成员、全候选selected/excluded/pending与原因、数量/来源缺口、待审板资料 | IDv5比整件；CMFv4比同表面或同物件界面；双分支分别产物，不混标准；交11 |
| 11 | 独立整板审阅：prism-board-review | 冻结标准、实际渲染整板、逐图原图/真实裁片、分组、来源及原负向 | board-review、逐成员是否保留/离群原因、修复/替换要求、原生验收及分维度状态 | 能否决单图；当前10合格图/10可核项目不足则未完成；修复回9/10后审当前版本 |
| 12 | 结果交付：prism-moodboard-delivery | 当前组板/板审结果、原图/视窗/处理/来源、原答复/版本/调用与问题台账 | 按真实状态渲染HTML/网页格式投影、证据与交接包、未完成及接续说明 | 包装不授视觉PASS；交付改变已审画面时重审受影响内容；本次不与11合并 |
| 13 | 独立评估修订：prism-independent-evaluation-loop | 新规则/版本、受影响输入输出、真实依赖和现有判标、问题最小证据 | 独立评估、issue卡、最多三轮定点修订记录、复验或下一决策 | 贯穿，非最后必跑一遍；不重发失败模型、不靠换issue名字无限循环 |

## 单图与板级回路

- 7的条件与预览可以反复校准；正式冻结后改变条件是新版本，不改原答案凑通过。
- 9若scope_gap回8，若target/ROI改变只重绑、重审实际覆盖；增强图只是展示版本。
- 10或11发现离群，按原条件回9修图/补源/换成员，再重放受影响10及当前整板11。不需要重提其他已满足范围的DNA。
- 无法补齐第10个合格独立项目或预算耗尽，交12输出未完成和缺口，不能压低一致性或数量门。

## 三个合并入口的详细合同

- [视觉转译与选材](../../prism-visual-material-planning/references/io-contract.md)
- [单图参考准备](../../prism-reference-image-preparation/references/input-output.md)
- [视觉选组](../../prism-visual-grouping/references/io-contract.md)

当前模型暂停继续有效。实际看图、品质主判/复核、独立整板判断仍需真实上下文；程序格式检查不是审美正确性的证明。
