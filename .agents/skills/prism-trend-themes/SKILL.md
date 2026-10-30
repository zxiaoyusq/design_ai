---
name: prism-trend-themes
description: 趋势页面兼容入口；使用多篇共同支持、主次语义归属与独立复核的纯文本聚类，按证据优先级排序，无结果数量上限。
metadata:
  version: "3.0.0-project"
---

# 趋势网页名称兼容入口

实际算法全部使用 [prism-trend-semantic-clustering](../prism-trend-semantic-clustering/SKILL.md) 3.0 与其 [字段合同](../prism-trend-semantic-clustering/references/format.md)。只用标题和摘要；图片、URL、标签、DNA 不进入语义请求。每篇文章一个主归属，其他机制以有准确原文锚点的次级关联保存，两类关系都需独立复核。

正式主题默认至少 3 个去重来源组共同支持，最低 2；不设 100 条或其他数量上限。按已复核去重来源组数、主归属来源组数、去重文章数降序和稳定 ID 排序。弱、单源和不支持线索完整留池。使用新 `scripts/semantic.py`，不调用旧要点级 `select_trends.py` 或旧共享编译器运行新版规则。

保留历史结果，不将旧结果冒充新版已重跑。网页支持查看全库、选择范围和启动新运行，结果明确展示运行范围及证据优先级。H01 如需读取，应做显式新旧契约适配，不直接把新 result.json 当旧原生接口。默认小样本离线验证，未授权不全量回放。
