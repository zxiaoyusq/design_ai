---
name: prism-trend-semantic-clustering
description: 对全量趋势文章的标题摘要标签作语义归组，独立检查主方向文字支持并输出库内规模排名及H01接口。用于趋势文字库；不看图片做归类、不把篇数解释为市场热度。
metadata:
  version: "1.0.0"
---

# 趋势文字聚类与规模排名

先读 [组合输入输出合同](../prism_skill_support/references/contracts.md) 的“趋势文字”；根据完整来源文字归纳，不以已解析图库限制主题。

输入稳定article_id、标题、摘要、标签、来源和图片链接旁表。声明文字是原文还是既有模型释义。图片URL保留供下游定位，但不送入第一阶段视觉判断；旧图片描述不冒充新DNA。

```text
python -B -X utf8 ../prism_skill_support/scripts/trend_text.py prepare --input articles.json --out trend-prepared --batch-size 64
```
准备器只冻结/分批，没有模型调用。先归纳带definition/boundary/design_question的方向目录，再对每篇完整文字直接回标；大库按固定ID分批，合并时核对全覆盖，不能从小样标签机械传播到全库。主题数由数据决定，不固定190。

主归属逐条用新的实际阅读上下文检查supported/uncertain/unsupported；准确文本锚点只是来源门，不自动证明语义蕴含。每条都要去向；待定、未归组和采集失败保留。相关标签与已支持主标签分开，不能累加为支持规模。

将真实提案及主归属复核按 [趋势交换格式](references/format.md)保存：
```text
python -B -X utf8 ../prism_skill_support/scripts/trend_text.py compile --corpus trend-prepared/corpus.json --proposal proposal.json --review review.json --out trend-result
```
脚本仅检查身份、引用、覆盖并导出，不会替你做语义判断。排名沿用本轮实际口径：支持主成员数降序、不同详情URL数降序、主题ID稳定排序。注明不是市场热度、增长或商业潜力。

交接trend-clusters.json、text-catalogue.json、ranking.json和coverage.json给H01；source-records保存完整材料池和图像旁表。不要把每簇少量握手例句当作后续全部图片池。
