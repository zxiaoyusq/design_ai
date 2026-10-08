# 本地 H01 契约 v1

## 输入适配

配置含 `research_final`、`trend_final`、`trend_images_file`、`brief`、`mode`（consensus / extension / exploration）、`min_trend_source_groups`（默认 2，至少 1）。路径相对 `--root`，也可绝对路径；`trend_images_file` 默认 `data/trend_data/trend_info_0930/trends.jsonl`。

用研要求：

- `handshake.json.schema_version = user_research_design_handshake.v1`、`ready_for_handshake = true`、`coverage_status = complete`。
- 按 `sources_file`、`observations_file`、`full_result_file` 相对入口目录解析；四文件的 `input_sha256` 相同，完整结果 `status = completed` 且 directions 与握手文件一致。
- 来源 `records[].source_id` 与 `users[].id` 唯一；每条观察 `id/source_id/user_id/evidence_kind/quote/stance/object/context/conditions` 均保留，quote 必须出现在对应 source.text。
- 每个方向 features 的 observation_ids 定义支持成员；context_observation_ids 只提供上下文。所有 avoid / conditional / conditions 非空项进入全局约束表，包括未入簇者。

趋势要求：

- `trend-clusters.json.schema_version = prism.trends.semantic_clusters.v0.1`。
- `trend-catalogue.json.schema_version = prism.trends.text_catalogue.v1`，articles 与 evidence 为 ID 唯一的列表。
- 每簇 evidence_refs 指向 catalogue；引用 source_id 在本簇 source_ids 内；evidence 与 article 的 source_group_id 一致。
- 保存 cluster 的 boundaries、variations、unknowns、lineage 成员。`proposal.json.point_scope_limits` 和 `execution.json` 如存在则冻结；不存在则记录缺口。
- `evidence-pool.json` 中未入选线索不能自动成为正式趋势支持，不能仅凭同 ID 外挂到已选簇。

冻结副本保存在 `frozen/`，`snapshot.json` 为完整适配数据，**不作为整包模型输入**。模型阅读 `overview.json` 与 `packet` 输出；分页 `next_offset=null` 表示该范围已读完。图片及 DNA 不进入语义取证投影。

### 图片清单与路径

图片输入为 JSONL，每行具有唯一原文章 `id`、可选 title/title_zh/source_row 和 `images` 列表。图片记录沿用工程图片下载索引：image_id、trend_id、index、url、status、local_path、format、width、height、size_bytes、sha256、error 等。`trend_id` 如存在必须与所在文章 id 一致。

- `prepare` 将此清单投影冻结为 `frozen/trend-image-inventory.json`，记录原清单路径和 SHA-256；不冻结或分析图片像素。
- 每篇关联文章用 catalogue 的 original_id 匹配图片清单 id；旧文字契约没有 original_id 时兼容去掉 source_id 的 `T:` 前缀。
- `local_path` 按**输入图片清单所在目录**解析，允许指向其他文章目录中的共用原图。输出同时保留项目相对路径（工程外为绝对路径）及 absolute_local_path，不能以目录名代替真实关联。
- 图片元数据位于独立冻结文件，不进入 snapshot 的语义数据、overview 或模型 packet。
- 图片清单不存在、ID 重复或关联文章未登记是契约错误；images 为空是合法的无原图记录。下载失败或路径文件缺失可交付，但必须在索引及报告保留状态、来源 URL 和未补齐数量。

## 提案格式

下面为结构示例，所有 ID 和引文均为占位，不能直接用于真实结果。`snapshot_sha256` 与 `prompt_sha256` 从 manifest 复制。

```json
{
  "schema_version": "prism.local.h01.proposal.v1",
  "snapshot_sha256": "manifest.snapshot_sha256",
  "execution": {
    "model_id": "实际宿主模型标识",
    "model_version": null,
    "started_at": "2026-10-01T10:00:00+08:00",
    "completed_at": "2026-10-01T10:10:00+08:00",
    "prompt_sha256": "manifest.prompt_sha256",
    "traceability_gaps": ["model_version"]
  },
  "directions": [{
    "direction_id": "H001",
    "title": "跨品类的单一设计主轴",
    "design_question": "围绕共同形式关系、可进一步验证的具体问题",
    "decision": "high_potential",
    "relation_basis": "direct_support",
    "research_cluster_ids": ["D001"],
    "trend_cluster_ids": ["GT-16"],
    "shared_design_principle": "双方共同支持的具体形式关系",
    "why_high_potential": "当前样本中值得推进的原因；降级项写明不足或冲突，不强称高潜",
    "research_citations": [{
      "observation_id": "S000022.F06",
      "quote": "与 observation.quote 完全相同",
      "role": "support",
      "reason": "它如何支持当前方向，而非仅名字相似"
    }],
    "trend_citations": [{
      "evidence_id": "T:10053:summary_zh",
      "quote": "来源 text 中连续的非空原文片段",
      "text_kind": "source_paraphrase",
      "reason": "它如何支持当前主张",
      "scope_note": "此条的局部部位、对象、条件；不得扩展到全部簇成员"
    }],
    "extension_explanation": "",
    "conditions_and_limits": ["适用对象、局部范围、情境及限制"],
    "user_differences": ["具体用户的偏好差异与条件；不以多数票取消少数"],
    "unresolved_questions": ["后续设计或视觉验证需要回答的问题"],
    "validation_next_step": "下一步可执行的设计验证建议",
    "constraint_audit": [{
      "observation_ids": ["某个约束观察ID"],
      "state": "applicable",
      "reason": "为何适用；分组时理由必须同时适用于组内每条",
      "implication": "具体如何限定方向或处置冲突；不适用时解释无需调整的范围"
    }]
  }],
  "research_cluster_coverage": [{"cluster_id": "D001", "disposition": "used", "reason": "支撑 H001"}],
  "trend_cluster_coverage": [{"cluster_id": "GT-16", "disposition": "used", "reason": "支撑 H001"}],
  "overall_evidence_gaps": ["本次仅做文本语义判断，视觉效果尚未核验"]
}
```

### 规则

- title、design_question、shared_design_principle 使用跨品类设计语言，按 [方向表达规则](direction-language.md) 提炼形式关系，不能用源品类或某品类专属部位限定方向。按机制归并，品类不成为主题划分或匹配排除条件；原对象与情境保留在原引用及条件中。此规则由语义执行者与交付复核判断，程序的 ID/引文校验不证明命名语义已满足。

- direction_id 唯一，directions 可空。每方向至少一用研簇、一趋势簇和双方引用；每个挂靠簇必须有真实成员引用。
- `decision`：high_potential / exploration / conflict / insufficient。后两者仍可保留尝试关系，簇状态 used 表示参与提案，不等于高潜。
- `relation_basis`：direct_support / anchored_extension / exploratory_hypothesis。模式限制见 SKILL；后两者必须填写 extension_explanation；探索不能标高潜。
- 用研 role：support / boundary / context。support 必须为所选簇的 prefer 或 conditional，不能是 profile_value。conditional 的实施条件仍必须在审查中保留。背景与品牌是否被偷换为偏好由语义复核检查。
- 高潜至少有一位正向支持用户，至少达到配置的去重趋势来源组数，且约束审查中没有 unresolved。没有最低用户人数比例。
- 每方向 constraint_audit 恰好覆盖 manifest 所指快照中的全部 constraint_ids，不重不漏。state 为 applicable / not_applicable / unresolved。组内 ID 可以来自不同簇，但不允许无实际依据的一揽子“不相关”。
- 两份 coverage 恰好覆盖上游全部簇；disposition 为 used / not_selected / insufficient / conflict。used 与 directions 的簇引用一致；其余必须有具体原因。
- unknown model_version 必须为 null，并在 traceability_gaps 标记；开始、完成时间含时区。不用产物数冒充模型调用数。
- 提案可附带真实中间步骤回执和原回复路径，禁止补造。更多 Token／服务端请求信息无法获知时记录缺口。

## 结果与人工确认

`accept` 验证后保存原提案、`result.json`（`prism.local.h01.result.v1`）、`report.md` 和哈希 receipt。结果增加每方向的去重支持用户 ID/人数、样本人数、趋势来源 ID/组数、完整引用来源信息；不允许模型自行填统计值冒充代码结果。

本地 Skill `1.1.0-local` 起，`accept` 还自动生成 `related-trend-articles.json`（`prism.h01.related_trend_articles.v1`），覆盖所有方向所关联趋势簇的**全部成员文章**及这些文章的**全部原图引用**；不会只保留直接引用的文章，也不会把关联簇成员都宣称为握手的直接支持证据。

- `result.related_trend_assets`：index_file 和全局 stats，含相关簇/文章/方向数、直接引用文章数、文本证据数、图片引用数、本地可用数、未补齐数及原始下载状态统计。
- `directions[].related_trend_assets`：index_file、article_source_ids、article_count、image_reference_count、local_image_count、unresolved_image_count。
- 索引 `articles[]`：source_id、original_id、文章标题/链接/来源定位、direction_membership、全部 text_evidence（直接引用以 cited_in_handshake 标记）与 images。
- `images[]`：原清单元数据、source_url、local_path、absolute_local_path、file_exists、availability；原始下载 status 不改写。下载成功但当前文件不在时 availability 为 missing_local_file；失败条目保留 error。
- 图片数量统计为**文章图片引用数**，共用原图可以对应多个引用；不会把复用引用误说成不同的唯一图文件。
- 图片索引只提供原文链接及已有标题/摘要，不能宣称本地拥有未采集的完整网页正文。
- `receipt.related_trend_articles_sha256` 与主结果共同封存；verify 校验索引哈希、完整关联重放及本地文件存在状态。旧冻结版本沿用原契约，不强制回填或改写历史结果。

结果始终 `review_status=pending_human_review`、`semantic_coverage=model_assessed`、`visual_analysis_performed=false`。已有结果不可覆盖，重新执行建新目录。旧目录里的 manifest、snapshot、冻结文件及结果都参与 verify。

`selection-template.json` 复制后填写：

- result_sha256：保持与本次候选结果一致；selected_direction_ids 可空（用户明确选择不采用任何方向）。
- actor：human 或 delegated_ai；actor_name：实际选择者；authorization：用户选择或委托的原文及消息定位；reason：选择原因；confirmed_at：实际确认时间，含时区。
- 只能选 high_potential；未解决／探索方向应先补充证据生成新候选，不能在选择阶段强制升级。

select 保存独立 selection.json 与哈希记录，不改写候选。代码能核验结构和版本，但不能证明 authorization 内容真伪；宿主必须实际收到用户选择或明确委托。
