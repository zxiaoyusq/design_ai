# 输入输出约定

版本：Skill 1.0.0；核心来源 `prism.research_semantic_clustering.v1`。工作边界是文字归纳，文档/OCR提取、独立真实性复核是上游动作。

## 简易文字入口

完整可运行示例为 [research-input.synthetic.json](../examples/research-input.synthetic.json)。它有 `schema_version`、`dataset_id`、`dataset_mode`、`people`、`sources`、`units`。

| 字段 | 内容 |
| --- | --- |
| dataset_mode | `real_or_public` 或 `synthetic_fixture`；后者不能冒充真实材料 |
| people | 唯一 person_id 和 display_name；允许匿名编号，重复表达仍使用同一个人ID |
| sources | 唯一 source_id、label、locator、evidence_kind |
| evidence_kind | synthetic_fixture、document_excerpt、transcript_excerpt、public_post、analyst_notes；准确标注出处，PPT摘要不等于逐字录音 |
| units | 唯一 unit_id、person_id、source_id、完整 text、kind、attitude、scope、locator；page 可空 |
| scope / target_entity | 对象、部位、条件、程度；无资料时 null，不能由分析者补填 |
| contrast_or_limit_markers | 已出现的转折/程度提示；空数组表示未标注，不代表原句没有限定 |

直接设计表达的 kind：`selected_board_reason`、`selected_style_word`、`phone_preference_reason`、`explicit_cmf_caption`。按真实提问方式选，不要把品牌、背景或分析笔记改名成直接表达。来源明确为手机之外的产品时，`explicit_cmf_caption` 用于有明确对象的CMF陈述，`selected_board_reason`用于选图理由；不要为了兼容而伪造手机场景。不适用上述通道的文字先用 `reference`，保留原文，单列方法扩展需求。

其他 kind：`brand_preference_or_impression`、`personal_identity_goal`、`character_association`、`elicited_concept_image_example`、`reference`。原算法中以 `Brand :` 开头的纯品牌名被识别为实体引用；新格式若只是品牌名，使用 reference 并保留原因，不借助字符串伪造品牌印象。

attitude：`like`、`preferred_word_selection`、`document_recorded_favorite_context`、`dislike`、`neutral`、`unknown`、`association`、`aspiration`。条件性偏好保留在完整 text/scope/limits 中；不要丢掉条件后只剩 like。最小单位若同时有正反态度，应从原文拆成可准确回引的分量并保留完整上下文。程序校验的是导入文字，不自动证明这些文字与未读取的录音或原始文档一致。

简易入口不接受图片链接、像素、DNA、质量评分。既有图片回链请用原生入口；它们仍只作来源关系。

## 原生目录入口

必须包含以下八个文件：semantic-units.jsonl、people.json、raw-evidence.jsonl、picture-contexts.jsonl、image-display-views.jsonl、selection-groups.jsonl、concept-example-links.jsonl、data-contract.json。prepare 只复制数据，不执行资料中携带的代码。无图文回链时对应四个 JSONL 可为空。

原生字段可从 `demo.py` 生成的 `dataset` 学习；保留语义单元和原始证据的同一 person_id/source_id、全文、准确 quote、页码、来源角色和态度。已有导入结果中的辅助字段完整保留，不能将旧图片聚类直接改标签作为语义簇。

## 提案

`schema_version` 为 `prism.research_semantic_clustering.v1`；`input_binding` 必须逐字复制当前 reading-packet 的绑定。`analyst` 记录真实分析者。`clusters` 包含 cluster_id、title、kind、definition、common_meaning、boundaries、handshake_question、members；members 包含 unit_id、quote、relation、facet、rationale、limits。

relation 是 support、boundary、alternative、context、illustration、mention。coverage 为每条 unit 指定 cluster_ids、disposition、reason；多义/未归纳部分可加 residual_note。不得拿未经阅读的模板默认项当语义结果。

字段类型必须准确：cluster_id/title/kind/definition/common_meaning/handshake_question 是非空字符串；boundaries 是非空字符串数组；members 是非空数组。member 的 unit_id/quote/relation/facet/rationale/limits 全是非空字符串（**limits 不是数组**）。coverage.cluster_ids 是字符串数组，disposition/reason 是字符串；analyst 是带真实身份记录的对象。

簇类型的人数由原始证据通道、relation 和 person_id 计算，**不检查 definition 是否出现“单人”字样**。shared_theme 需要至少两位直接设计支持者；exploratory_signal 恰好一位。品牌印象即使 relation=support，也只计 brand_impression_count，不计直接设计人数。只有品牌印象的簇不能标作 exploratory_signal/shared_theme：可在有明确设计问题的 design_issue 中保留品牌关联，或保留为参考，不能把来源改成直接设计表达。background_theme 的成员仅允许 context；个人目标不是直接设计支持。

## 输出

| 文件 | 用途 |
| --- | --- |
| reading-packet.json / run-manifest.json | 完整阅读材料、输入及代码身份 |
| analyst-proposal.json | 实际语义提案，独立保存 |
| clusters.json | 含完整成员、原句、限定、去重人数的语义簇 |
| coverage-ledger.jsonl | 每条原记录的归属或保留理由，包括未聚类否定 |
| memberships.jsonl | 逐个归属和依据 |
| handshake-input.json | 摘要索引，不可单独作为下一环节可信输入 |
| handoff.json / acceptance.json | 同步输入身份、完整否定账和校验结果 |
| 聚类报告.md | 便于阅读的结果 |

搬动已经运行过的目录后，研究结果的绑定使用相对文件名与字节哈希，可执行 verify；修改代码或数据则必须新建运行。簇类型和引用正确不等于语义真实准确。样本人数、簇数、通过率都不是人群比例。
