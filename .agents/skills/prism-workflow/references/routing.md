# 当前项目流程与合并入口

| 位置 | 当前Skill | 交给下游什么 |
|---|---|---|
| 启动/恢复 | prism-run-contract | 项目范围、当前授权/模型/预算、候选及最终数量政策、状态 |
| 资料未整理时 | prism-research-intake | 有原文和角色/对象/图片出现位置的reviewed研究输入 |
| 两侧文字，可独立并行 | prism-trend-semantic-clustering / prism-research-semantic-clustering | 完整趋势簇/文字目录与研究dataset/run、覆盖和负向 |
| 第一次握手 | prism-h01-semantic-handshake | 候选方向、双侧原文、边界、负向、未决 |
| 实际选向 | prism-direction-selection | 原生selection、分支与真实选择依据/身份 |
| 视觉转译及素材预览 | prism-visual-material-planning | 冻结视觉条件、广候选池、来源、逐图计划及容量缺口 |
| 可见事实提取/覆盖复用 | prism-dna-sol-r5 | 原R5结果、原观察/at、known/unknown/pending/invalid、完整身份与回执 |
| 单图闭环 | prism-reference-image-preparation | 当前绑定、原生品质、真实裁片及独立复核、可入组/待定/排除及原因 |
| ID或CMF第二次握手 | prism-visual-grouping | 对应原生prepared/grouping、成员、全候选去向与待板审材料 |
| 独立整板审阅 | prism-board-review | 当前真实整板审阅及原生验收、逐成员否决、替换/修复要求 |
| 交付 | prism-moodboard-delivery | 按真实状态生成HTML/网页投影、证据及接续说明 |
| 贯穿 | prism-independent-evaluation-loop | 问题卡、受影响部分复验、三轮到限的明确下一决策 |

三个合并入口内部规则在各自references按需读取。共享代码仍经prism_skill_support复用；原生IDv5和CMFv4不混成一个比较标准，R5固定配置不变。以上为13个主Skill；总入口与旧网页名只路由，不增加业务判断。

预览与视觉条件相互校准，冻结后不为凑数改条件。单图准备可以按真实依赖先预绑定或先品质，但进入视觉选组前须闭合当前范围的品质和实际裁片复核。范围/ROI变动只重做受影响部分；板审否决成员后回单图准备、必要时补R5，再重放受影响选组和当前整板审阅。

整板审阅与结果交付本次仍为两个Skill。没有第10个合格独立项目时保持未完成；合并入口不减少真实看图、不解除暂停、不重置预算、也不把程序重放计为新模型推理。

原包资料中出现旧visual-family/source-image-selection、target-view-binding/target-quality/crop-enhancement、id-moodboard/cmf-moodboard，分别理解为这三个入口的内部阶段，不再额外启动七个旧Skill。
