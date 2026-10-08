# 输入输出契约

## Excel

要求字段 `id`、`title`、`title_zh`、`summary_zh`；至少一个标题/摘要非空才能形成证据。多工作表用 `--sheet` 选择。重复或空 ID 报错；原有 ID 不改写。source_id 为 `T:<原ID>`，证据 ID 添加 `:<字段名>`。

`source_url`、`detail_url`、`release_time`、`primary_category`、`subcategory`、`tags` 仅存档；模型请求中的 article 只有 source_id 和文本 evidence。`image_url` 存在 `source-links.json`，不进入 catalogue 或请求；其余列一律忽略并记录列名。

同一详情 URL（仅移除 utm_* 参数，保留片段和业务 query）或相同非空完整摘要用并查集合并来源组。WGSN 的 `#story-...` 是文章身份，不能丢弃。来源组不是发布网站：同一网站可以有不同文章。未知转载关系不会自动解决，也不能把来源组数解释为独立验证数。publisher_group 单独保存来源域名；source_url 缺失时从 detail_url 提取。

## 批提案

`request.json` 包含 batch_id、messages 和请求哈希。`proposal-template.json` 自动填入绑定，以下示例中的候选需要按证据实际填写；覆盖模板默认文本不足，必须逐篇判断并填写理由。

```json
{
  "batch_id": "B0001",
  "request_sha256": "使用本包请求的实际哈希",
  "analysis": {"actor": "实际分析者", "model_id": null, "model_version": null, "completed_at": "2026-09-30T12:00:00+00:00"},
  "clusters": [{
    "cluster_id": "B0001-C01",
    "title": "低光泽主体与明亮细节的对比",
    "definition": "主体保持克制，细节承担光泽对比。",
    "design_question": "如何用局部光泽变化明确视觉重点？",
    "dimensions": ["surface", "composition"],
    "boundaries": {"shared_design_mechanism": "主体与细节承担不同反射角色", "includes": ["局部明暗反差"], "excludes": ["整面同等镜面反射"]},
    "hypotheses": [], "unknowns": ["实际反射率未知"],
    "members": [{"point_id": "B0001-P001", "subject": "产品主体与边缘", "feature": "低光泽主体对比明亮边缘", "dimension": "surface", "condition": "亮面仅限边缘", "evidence_id": "T:1:summary_zh", "quote": "精确复制源表中的连续文字", "reason": "该对象的主次表面关系支持上述机制"}]
  }],
  "coverage": [{"source_id": "T:1", "status": "clustered", "reason": "保留表面反差机制", "residuals": []}]
}
```

每个候选必须有非空 members；所有证据仅来自该包，引用要精确匹配。coverage 三种 status：clustered / non_aesthetic / insufficient_text；入簇状态必须与成员引用一致。candidate ID 以 batch_id 加 `-` 开头，全运行唯一。

候选及最终主趋势的 title、definition、design_question 使用跨品类的共同审美机制，不以服饰、手机、家具等品类或其专属部位限定主题。member.subject、quote、condition 和 variations 继续保留源对象与具体实现。归并按形式关系，不能用品类作为主题边界；通用表述不扩大证据范围。此项是模型语义交付规则，不由 ID/引文结构校验代替。

member 是轻量审美要点，point_id 以批号加 `-P` 开头，全批唯一；subject、feature、reason 非空；dimension 为一个合法维度；condition 必填，确无条件为 null。不要按维度机械复制同一机制；一个文章有多个机制则多点。引文子串校验不理解语义，选择引文时应带足否定与条件；归并代表样本和复核请求由代码附加整个 evidence.text，避免短引文掩盖原句。

check-batch 将原提案逐字保存到按内容哈希命名的 history 文件，accepted.json 保存同样字节。再次接受是显式修订；旧提案仍在 history。collect/finalize 重新校验 accepted；批提案变化后旧 collection/plan 失效，需重新 collect。

## 全局归并 plan

3.x 使用 select_trends.py 的筛选运行。不要把 2.1 collection_sha256/candidate_ids 旧方案直接作为新 plan。prepare 从旧 final 或已验收首轮运行冻结 catalogue、points、seeds、初轮覆盖、旧执行信息及可选 corrections；selection-packets 展示有界摘要，完整证据在旁表。阅读所有种子，不能先按支持数删掉单篇。

```json
{
  "selection_manifest_sha256": "selection-run/manifest.json 的实际文件哈希",
  "analysis": {"actor": "实际分析者", "model_id": null, "model_version": null, "completed_at": "2026-10-01T12:00:00+00:00"},
  "clusters": [{
    "cluster_id": "TC01", "title": "孔隙构成的通透层次",
    "definition": "借助有孔或间隔结构形成文本明确描述的视觉通透与轻盈。",
    "design_question": "如何以实体与空隙的关系减轻视觉体量？",
    "dimensions": ["form", "composition"],
    "boundaries": {"shared_design_mechanism": "实体与空隙交替形成通透层次", "includes": ["文字明确支持通透关系的格栅或网孔"], "excludes": ["仅谈散热而无审美依据的孔洞"]},
    "hypotheses": [], "unknowns": ["不同材料实际透明率未知"],
    "variations": ["木格栅与金属网孔是不同实现，不代表所有文章同时包含两者"],
    "point_ids": ["B0001-P001", "B0002-P002", "B0003-P003"]
  }],
  "deferred_points": [{
    "point_ids": ["B0004-P001"],
    "reason_code": "single_source",
    "reason": "仅有一篇支持这一独特装饰，尚无相同审美表达的其他来源。"
  }]
}
```

示例 ID 仅示意，不保证实际满足门槛，支持数由脚本从输入推导。analysis 与主题基础字段沿用批提案契约；variations 是字符串数组；point_ids 必须真实、唯一。deferred_points 可为空；无主趋势也合法，但必须解释全部要点去向。

每点在 clusters 与 deferred_points 的并集中恰好出现一次。重复、遗漏、未知 ID 均报错；同一文章可用不同点支持多个趋势，但同一趋势中的文章和来源组各去重计数。每类必须同时达到冻结的 min_source_groups 篇文章和来源组（默认 3，最低 2），最终类数不得超过冻结 max_trends（1–100）。不得通过多点、原候选数、长文或重复文章提高权重。

deferred_points.reason_code 仅允许 single_source / weak_support / outside_top_trends / redundant_detail / ambiguous，reason 非空且解释具体原因。未入选不等于信息无价值；不得将证据池另包装成数千条“最终趋势”。

若有既有 point_interpretation_limits，应通过 --corrections 导入，保留 original_feature、effective_feature 与 rejected_inference，并将规范 feature 同步为有效特征，避免下游继续使用旧错误；后续判断以有效特征及原文为准。种子的定义、边界与未知同样是需继承的修订限制。未发现的旧错误仍可能存在，结构校验不背书语义。

## 最终产物

- `trend-clusters.json`：`prism.trends.semantic_clusters.v0.1`，仅主趋势，最多 100 条；含共同定义、边界、变体、假设、未知、精确引文及实际所选成员 lineage。引用、文章和来源组由代码汇总，按去重来源组数、文章数降序；不生成市场热度或虚构置信分。
- `trend-catalogue.json`：全量原始文本、源表定位；文本标记 source_paraphrase，original_text_excerpt=null，未核验源网站。
- `evidence-pool.json`：所有未入选要点及理由，不作为主趋势列表。
- `point-dispositions.json`：每点主趋势归属或证据池去向，保障全量留档。
- `coverage.json`：逐篇 extraction_status 保留首轮判定，最终 status 为 clustered / evidence_only / non_aesthetic / insufficient_text，含所选趋势与未入选要点，区分“已分析”与“入选”。
- `report.md`：仅展示主趋势、去重支持数、边界与代表引文，摘要说明证据池和覆盖；不逐条展开所有单篇细类。
- `execution.json`、`proposal.json`：绑定输入/引擎/Prompt/提案哈希，保留继承的执行记录、真实分析者与模型信息及人工确认状态。

不会回写输入或覆盖既有 final。语义覆盖为 model_assessed，visual_analysis_performed=false，review_status=pending_human_review；不能把所有点有去向称为语义准确率 100%。

## 成本与兼容性

初轮 request 默认最多 28000 字符，按完整文章分包；选择器按种子摘要分包，超长单条报错而非截断。字符不等于 tokens。摘要省略的完整成员必须可定点回查；全局必须跨包归并。没有内置模型 API，也没有自动生成语义归类的关键词规则。

pipeline.py 保留 2.1 引擎用于提取兼容，其 collect/finalize 是旧细类档案工具，不承担 3.x 主趋势筛选。已有旧档案通过 --from-final 复用；新提取通过 --from-run 直接进入选择阶段。旧运行/快照/计划不修改。3.x 的硬上限、门槛和完整去向由 select_trends.py 验收。

额外定点模型复核默认总预算至多 3 次，继承既有额度和实际用量；修订计划不刷新预算。预算外疑点转人工，不能将复核包生成算作执行。不得仅为验证 Skill 启动全表模型回放。
