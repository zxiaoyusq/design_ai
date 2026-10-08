---
name: prism-trend-themes
description: 旧趋势页面名称的兼容入口；按同事v2的文章主归属和独立复核做纯文本趋势聚类。
metadata:
  version: "2.0.0-project"
---

# 趋势网页名称兼容入口

实际算法全部使用 [prism-trend-semantic-clustering](../prism-trend-semantic-clustering/SKILL.md) 与其完整契约。每篇文章保留一个主归属，多义关联另存；只有独立语义复核supported的主成员计入排名/H01。输入只是文字，图片URL只作来源旁表。

不继续调用旧要点级`select_trends.py`或旧100条/3来源组编译规则。已有结果保留为历史证据，迁移须按原字段适配并保持真实来源，不将旧结果冒充v2已重跑。网页字段只作投影，不改变语义成员、引用、条件或验收状态。把原生输出交给同级H01。
