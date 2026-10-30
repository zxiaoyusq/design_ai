# 18个技能的路由

|阶段|技能|输入与输出|
|---|---|---|
|0|prism-run-contract|当前指令/状态 → 范围、政策、账本|
|1|prism-research-intake|原报告 → 来源绑定的文字、媒体出现关系|
|2A|prism-research-semantic-clustering|已核原话 → 语义簇、覆盖、正负边界|
|2B|prism-trend-semantic-clustering|文章文字 → 趋势语义簇、规模和未知|
|3|prism-h01-semantic-handshake|两侧语义 → 双侧依据和逐方向负向审计|
|4|prism-direction-selection|H01候选 → 真实选择、依据和未决|
|5|prism-source-image-selection|方向关联文章 → 有来源的广候选池|
|6|prism-visual-family|候选预览/设计师标准 → 总体设计语言与情绪假设|
|7 可选|prism-dna-sol-r5|当前授权的原图 → 冻结R5可见特征及未知|
|7 可选|prism-dna-clustering|已有DNA → 辅助检索分组，不给成板通过|
|8|prism-target-view-binding|实际原图+解析 → 当前对象/范围/ROI|
|9|prism-target-quality|当前视窗 → 可读性、表面和干扰|
|10A|prism-id-moodboard|形体/色材/构造组合 → ID与总体风格候选|
|10B|prism-cmf-moodboard|同物表面/邻接组合 → CMF与总体风格候选|
|11|prism-crop-enhancement|保留原像素的裁切/编排 → 双版本实际板|
|12|prism-board-review|原图、板、绑定 → 多维设计情绪及版本反馈|
|13|prism-moodboard-delivery|审阅后产物 → 原图/可编辑排版/来源包|
|贯穿|prism-independent-evaluation-loop|真实失败/反馈 → 定点更新与复验|

两侧语义可以独立完成。5/6之间允许有界迭代：先看真实素材能力，再明确风格假设；冻结后不能为凑数暗改。7按需要使用，原图观察+已有解析是当前核心；不以没有DNA拒绝一张有用的待核图，不恢复DINO。

已有方向/绑定时从最近有效阶段接续，不重做整条链。visual_trial也保留已有用研前提，仅将未做的正式H01/H2标not_executed。historical_replay严格保留旧输入/算法/结论，不套新规则回写。

同一图可跨ID、CMF和不同板复用，各板独立审；同板同项目不重复。变更目标/裁切回到绑定和受影响复核；改文案不重跑全库。加载当前技能及必要引用即可，未知问题再查原生文档。
