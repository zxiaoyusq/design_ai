---
name: prism-id-moodboard
description: 按选定视觉家族比较完整对象的轮廓、比例、构造与主次，完成ID第二次视觉选组及整板复核。用于整体风格情绪卡；不把CMF局部或共同功能当成整体一致。
metadata:
  version: "1.1.0-local"
---

# ID整体形态第二次握手

先读 [组合输入输出合同](../prism_skill_support/references/contracts.md) 的“原生H2”和 [ID接口](../prism_skill_support/references/native-api.md)。当前实现是家族条件下的实际视觉选组，不是全库无监督向量聚类。

使用id-reference-board-v5（同字节别名记录全程使用alias-id入口）：prepare重放原图、R5、质量、对象声明、绑定与实际视窗，再grouping_view准备模型阅读。不要信任外部profile的supported缓存。原负向和未决义务逐条携带。

给分组者原图、当前视窗、明确视觉brief、候选自身的已知观察和校准参考。比较整件主导形态、比例和结构关系，说明成员及全部排除项；同功能/颜色/品类/参数ID不足以成组。保持每个观察的原值/位置，不跨对象借证据。

启用已有DNA省额度模式时遵守 [省额度选图政策](../prism_skill_support/references/budgeted-visual-selection.md)。本地关系预组和代表选择只是候选，不替代实际原图/ROI分组与独立整板判断；不为扩大组员池默认让供应商重读全库。继承累计入围与整板请求账本，改名、换批或修布局不重置上限；到限保留已形成内容和真实缺口，不凑数量或补PASS。

按本次项目事先冻结的数量政策执行accept_grouping；数量不足与视觉不一致分开报告。历史十张硬门是案例配置，不是用户所有新项目的必然要求。不得见到结果后静默降低native条件使其变PASS。

整板有真实渲染后，独立比较整板＋每张原图/视窗，不沿用组员PASS。核主体完整、比较尺度、共同主关系、离群项、原负向适用对象。只有真实完成审阅才调用accept_board_review记录结果。未进入原生整板门的候选可如实展示，但不能补造原生通过。

原生prepare→grouping_template→accept_grouping→prepare_board_review→board_review_template→accept_board_review的方法签名可由native_api describe查看。交接grouping、board-review、渲染和每图来源；若失败，给出最小反例及受影响部分，交由流程入口继续定点改良而非全批重跑。
