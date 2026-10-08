# 输出与趋势握手契约 v1

## 运行文件

| 文件 | 用途 |
| --- | --- |
| manifest.json | 输入文件哈希、用户范围、源记录数、批次和 Prompt 版本 |
| sources.json | 全部文本及原值、JSON Pointer、原记录 ID、来源性质；不含图片数据 |
| prompts/、requests/ | 冻结的 Skill/阶段指令、逐包模型输入和消息哈希 |
| extractions/B*.json | 逐包原始模型回复、模型标识/版本、时间和消息哈希 |
| observations.json | 全部原子观点、完整引文、保留片段、逐包执行追溯 |
| coverage.json | 每个源文本的片段数/观点数/保留数及结构覆盖状态 |
| cluster-request.json | 全部原子观点的紧凑表；不缩短 statement、条件或场景 |
| clusters.json | 语义聚类回复，由宿主保存 |
| final/result.json | 方向、全部用户定位、未聚类背景、全部观点去向和源索引链接 |
| final/handshake.json | 稳定的用研侧设计方向接口，供趋势匹配消费 |
| final/report.md | 方向说明、分歧、建议、样本人数和完整原文入口 |

重复 PPT 源 ID 可能跨用户出现，不能只用 `ppt-s03-personal-image` 关联；程序在冻结输入内分配 S 编号，同时保存用户 ID 和 JSON Pointer。原子观点 ID 为 `Sxxxxxx.Fnn`。这些 ID 只在本次 `input_sha256` / `run` 范围内唯一，跨运行匹配需同时携带输入哈希。

extract 和 cluster 回复中的 execution 使用真实值；未提供的模型标识/版本是 null 并输出 traceability_gaps。executed_at 必须有时区。prompt_sha256 是完整 messages 的哈希，不能填成 Skill 文件哈希。现有文字提到的图片不构成本轮视觉输入；最终固定 `image_analysis_performed=false`。

## 全面性的判定

prepare 不抽样、不筛“未提及”、不丢空行、不缩短字符串；所有 profile 叶值和问答/需求正文进入清单。图片、关联表和 PPT 导入元信息的排除数量明确记录。新出现的未知用户/问答字段拒绝静默跳过，提示扩展文本映射。

collect 要求各批次 source_id 集合与输入完全一致，片段拼接等于完整原文，引文在片段中实际存在。finalize 要求全部观点均有合法去向、审美设计观点进入方向特征、全部用户有定位记录。任何缺项拒绝完成，已有提取文件继续保留。

`coverage_status=complete` 表示上述结构条件满足，`semantic_coverage=model_assessed` 表示含义由模型按协议逐项整理，未进行独立全量语义审计。不要用这两个字段宣称数学意义上“所有隐含信息零遗漏”。原文和保留片段始终可回查。

## 用研侧 handshake.json

顶层 `schema_version=user_research_design_handshake.v1`，包含 input 的哈希、全部用户定位、directions 和 coverage。每个方向包含：

- `id/name/design_question/summary`：具体设计主题，名称不直接作为命中依据。
- `features`：dimension、stance、statement，以及编译展开的 observations。每个观点都带用户、来源、对象、场景、conditions 和原文 quote。
- `context_observation_ids/differences`：适用人群/场景语境与分歧。
- `design_implications`：明确标为 proposal 的建议，不是用户原文事实。
- `users_by_stance`：仅从 features 引用计算 prefer/avoid/conditional/neutral 的去重用户集合，同一用户可出现在多个态度中。
- `source_ids`：真实核心来源；上下文引用另列，不把背景人数计为支持人数。

分母是本次全部用户数，统计是样本内不同用户的提及，不是市场份额或统计显著结论。只有 avoid 证据的方向可以用于后续否定或限制匹配，不能被解释为支持趋势。

后续匹配方接收现有趋势的 `clustering_label` 和类内具体趋势方向，再与上述 design_question/features/context 对比：

1. 先找可解释的设计表现或审美意图交集，可多对多；同标签、同品牌不等于同机制。
2. 正向交集引用 prefer；conditional 必须携带满足条件；avoid 作为冲突/限制。neutral 背景不替代正向支持。
3. 保留产品/部位/场景差异；跨品类应用写为建议，不推定用户已认可趋势材料、文化或工艺。
4. 结果保存研究方向 ID、趋势方向/文章 ID、双方依据和限制，不将本文直接包装为高潜评分。

下游使用 `prism-h01-semantic-handshake`：其 prepare 直接读取本契约的 handshake.json，按 sources_file、observations_file、full_result_file 加载来源、观察项和完整结果，再与趋势聚类做语义握手。新 Skill 不重做用研聚类，也不修改本结果。现有网页后端的旧 design-trend-synthesizer 运行库仍接收原 users JSON，不可把 handshake.json 当作 users.json 传给旧接口。
