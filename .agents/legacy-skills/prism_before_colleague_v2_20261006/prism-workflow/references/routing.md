# 只加载当前需要的环节

| 阶段 | Skill | 输出给谁 |
|---|---|---|
| 报告原始证据 | prism-research-intake | 用研语义 |
| 用研文字归纳 | prism-research-semantic-clustering | H01 |
| 趋势文字归组/库内规模 | prism-trend-semantic-clustering | H01 |
| 第一次纯语义握手与选择 | prism-h01-semantic-handshake | 视觉家族 |
| 可见设计关系与范围 | prism-visual-family | 选图 |
| 复用已有DNA、本地关系预组与代表、预算内原图目标和来源 | prism-source-image-selection | 品质 |
| 指定目标用途品质 | prism-target-quality | R5 |
| 同图ID/CMF可见事实 | prism-dna-sol-r5 | 目标绑定 |
| 原位置对应与实际视窗 | prism-target-view-binding | ID/CMF分组 |
| 整件风格 | prism-id-moodboard | 整板与交付 |
| 局部表面/界面 | prism-cmf-moodboard | 整板与交付 |
| 原图内嵌、状态、来源和证据包 | prism-moodboard-delivery | 用户反馈 |

本Skill只编排，不吞并所有算法。每个环节可以独立调用；若单独复制某个新Skill，须一起带prism_skill_support及manifest声明的依赖。三个旧便携Skill的独立算法入口仍可单独使用。

已有DNA的本地预选与预算编排读 [省额度选图政策](../../prism_skill_support/references/budgeted-visual-selection.md)。是否暂停、执行或扩档继承当前项目状态，路由本身不启动模型。
