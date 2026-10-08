# 趋势提案与支持复核

prepare输出corpus.json和文本分批。目录归纳、各批逐篇直接归类和独立文字支持复核由实际分析者完成；程序不替你填写主题。

完整proposal：

```json
{
  "corpus_digest":"当前corpus的规范JSON摘要",
  "analyst":{"actor_id":"当前实际分析者","model":"实际模型或unknown"},
  "themes":[{"theme_id":"G001","title":"方向名称","definition":"共同含义","boundary":"不应外推的边界","design_question":"可探索的问题"}],
  "assignments":[{"article_id":"A001","theme_id":"G001","anchor":"输入text中实际存在的连续原句","reason":"该句为什么支持目录定义"}]
}
```

未归组的theme_id为null，并保留原因。全库每article_id恰好一次主去向；相关候选标签可另存，不能加入支持主成员计数。大库各批合并先检验ID不重不漏，目录版本一致；不要依据小样传播未读过文章的标签。

support review绑定完整proposal文件SHA256，覆盖每条非null主归属：

```json
{
  "proposal_sha256":"实际提案文件SHA256",
  "reviewer":{"actor_id":"实际复核者","model":"实际模型或unknown","review_kind":"fresh_context或same_analyst_review"},
  "reviews":[{"article_id":"A001","theme_id":"G001","status":"supported","anchor":"实际原句","reason":"明确文字依据"}]
}
```

status只取supported/uncertain/unsupported，缺复核不默认supported。独立上下文需要真实执行记录，单纯填review_kind不能证明独立。compile只验证结构、引用与覆盖，不证明语义准确。

helper的io_utils.digest使用UTF-8、sort_keys=true、separators=(',', ':')的规范JSON SHA256；文件SHA则按原文件字节。两者不要混用。H01配置中trend_clusters_path指向trend-clusters.json，trend_catalogue_path指向text-catalogue.json。新图片关联可后续另登记，无图不是H01阻断。
