# 3.0 纯文本聚类字段与执行合同

本文件是新运行的权威字段合同；共享旧 `trend_text.py` 的 proposal SHA 文件绑定和只统计主成员规则只用于历史复放。

## 函数接口

`scripts/semantic.py` 是标准库模块，不调用模型，可由后台动态加载：

- `normalize_records(rows)`：返回白名单文章数组。输入 article_id（或 id）、title、summary，可有 source_group_id、detail_url/source_url、published_at、text_kind。输出额外包含 text（标题与摘要以换行连接）、text_hash 和程序去重后的 source_group_id。拒绝重复/缺失 ID；空文字可保留但只能主归属 null。
- `pack_records(records, max_chars=24000)`：返回数组的数组，严格依规范 JSON 字符数分包；不截断过长文章。只输出文字、身份、来源组和文字来源性质，不输出 URL、图片、标签、DNA 等附加字段。
- `validate_proposal(records, proposal)`：校验并返回白名单提案；失败抛 ValueError。
- `review_packets(records, proposal, max_chars=24000)`：每包包含若干 `{article_id,theme_id,role,text,theme,assignment,binding_hash}`。绑定基于文章文字、完整主题五字段、关系含义、role 及分析上下文集合。
- `compile_result(records, proposal, reviews, min_source_groups=3)`：reviews 可以是数组或 `{"reviews":[...]}`。完整审阅后返回 `{version,min_source_groups,themes,ranking,candidate_pool,records,proposal,coverage}`。themes 已按支持优先级排序，不限制条数；candidate_pool 保留弱主题。只验证机器可检查的覆盖和引文，不证明模型判断正确。

## 提案

```json
{
  "analysis_context_id": "由宿主记录的真实分析运行上下文",
  "analysis_context_ids": ["包括发现与合并阶段全部真实上下文"],
  "themes": [{"theme_id":"T001","title":"主题名称","definition":"共同含义","boundary":"排除边界","design_question":"设计问题"}],
  "assignments": [{"article_id":"A1","theme_id":"T001","anchor":"输入 text 中的准确连续子串","reason":"支持共同含义的具体理由"}],
  "secondary_assignments": []
}
```

所有文章恰好一条主归属。未归类填 `theme_id:null`，仍须具体 reason，anchor 可空；次级关系不能 null。不得重复同一主/次关系，不得让次级复制主归属。主题五字段必须非空。示例是字段形状，不是语义答案。

analysis_context_id 必填；analysis_context_ids 可省略，此时只使用前者。由宿主注入而非信任模型输出。分批发现与后续归并如使用多个上下文，必须登记完整上下文集合。

## 复核

```json
{"reviews":[{
  "article_id":"A1", "theme_id":"T001", "role":"primary",
  "status":"uncertain", "anchor":"输入 text 中的准确连续子串",
  "reason":"复核依据与疑点", "binding_hash":"复制对应 review packet 的实际绑定值",
  "review_context_id":"宿主记录的实际独立复核上下文"
}]}
```

role 只能 primary 或 secondary；status 只能 supported / uncertain / unsupported。每个非 null 关系恰好一条复核，包括次级关系。复核锚点必须来自当前文章，即使 unsupported 也应引用被误解/证据不足的原文；空文不应进入提案关系。宿主真实创建新上下文并记录回执，再注入 review_context_id。字段必须不同于全部分析上下文，不能仅改 ID 冒充独立。

缓存绑定完全一致时才可复用。不要更新旧哈希使失效复核表面通过。程序不接受遗漏、重复、错误角色、未知成员、同上下文或失效哈希。

## 编译与排名

正式 themes 中每项含原主题字段及 source_group_count、primary_source_group_count、article_count、primary_article_count、priority_rank、members（supported 主关系）、secondary_members（supported 次关系）、reviews（含全部判定）、eligible。两个成员数组都保留 article_id、anchor、reason 和绑定信息。

一个来源组中的转载只算一份来源支持，一篇文章在同主题只算一次。正式主题默认需至少 3 个组，阈值最低 2。排序键是 `(-source_group_count,-primary_source_group_count,-article_count,theme_id)`。candidate_pool 含同样证据与 pool_reason，没有数量截断。

来源去重使用显式组/相同规范文章 URL/相同规范文本的连通关系，不是域名分组；保留 URL 的文章身份片段，不把 #story-1 和 #story-2 合并。它只能识别已知重复，不代表统计上的真实独立来源。不同摘要的未知转载不能自动识别，应在人工可审计的来源映射中修正后重新冻结。

coverage 保留 article_count、reviewed_relation_count、supported_article_count、unassigned、uncertain、unsupported、without_supported_relation。result.json 不是旧版 H01 原生接口；适配时明确区分主次及支持统计规则。
