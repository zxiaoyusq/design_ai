> 本页仅用于2.x历史流程；新任务使用 [3.0轻量流程](lean-workflow.md)。

# 用研补充方向

主卡表达趋势与用研的交集；补充部分以用户回答为主体，写“多数人明确提到，但本轮选中趋势文本没有提及”的设计议题。不要列未入选的趋势文章，也不要把该部分包装成已经验证的新趋势。成卡和补充方向都不输出“下一轮验证”或 `validation_questions`。

## 分步处理

1. `python SKILL_DIR/scripts/user_gaps.py prepare --run RUN` 读取当前 evidence/records，生成 `user_gap_context.json`：宽维度去重人数、全体统计分母、输入摘要、用户及趋势小包路径。用户包最多 32 条观察且按完整问答字符预算分批，默认 16,000 字符；`--batch-chars` 可调整。它只组织现有证据，不调用模型。
2. 宿主先用已有主题和宽维度人数召回候选，再分包核对**全部已提取用户观察**，包括未配对、未成为代表和未进入主卡的观察。包是阅读单元，不要求每个文件新增一次付费模型调用；复用已完成的语义归纳，只有仍需判断的内容才分小步调用宿主模型。可用代码关键词筛选辅助阅读，但命中不是语义结论。每次只归纳少量方向、补充已有 evidence_id，不重写原文或计数；必要时保留各包判断文件。不同颜色、对象、条件和相反态度保留在总结和边界，不强合成统一偏好。不要只统计主卡引用的人。
3. 将同一具体设计议题的用户 evidence_id 合并去重。逐包阅读本轮**全部选中趋势的完整文本字段**，对每个方向逐趋势记录 `unmentioned/mentioned/uncertain` 与简短理由。大类同为材料不代表出现同一具体设计议题；缺关键词、缺维度、未进入主卡都不能单独证明未提及。输出语义核对 findings 文件，结构见下。
4. `python SKILL_DIR/scripts/user_gaps.py publish --run RUN --findings RUN/user_gap_findings.json` 校验输入摘要、用户归属、回答原文引用、全趋势覆盖清单，代码统计并筛选，再更新 JSON/JSONL、Markdown、校验和完成标记。无符合条件方向可以交付空清单和如实说明；不得降低门槛凑数。

`prepare`/`publish` 不驱动原模型队列。部分数据预览由其编译器调用同一 `compile_findings` 和 `markdown` 函数，并明确传入 scope 中的已处理用户 ID；自定义 HTML 同步渲染返回的 `user_research_gaps`。原运行继续暂停。

## 统计与范围

- 正式完整运行分母为 records 中全部有文本、可归属的用户；部分预览分母为 scope.accepted_user_ids，不取命中方向的人作为分母。未处理用户不能被当成未提及。
- 同一用户有多条问答、多条需求或多条观察，只计一人。只有 user_qa.ai_analysis / user_demand.ai_index 的有效回答算证据；问题、孤立需求和趋势文本不计用户人数。
- 发布门槛为 `unique_mentioned_users * 2 > population_count`，恰好一半不叫多数。人数是已核对提及人数的保守下限；拒绝、支持、条件表达都可以说明用户谈到该议题，因此不是共同偏好率。正文不得据此宣称多数人接受某个具体方案。
- 有任何趋势为 mentioned 或 uncertain，该方向不进入此部分。代码验证核对清单的完整性，语义判断仍来自宿主，不声称代码证明了市场空白。
- 用户已有图片路径按具体引文内的明确编码关联，未关联就留空。每个方向完整证据、人数、占比及趋势核对清单保留在 JSON，文字报告以用户诉求和差异为主体，不逐项介绍趋势文章来源。

## Findings 文件

模型/宿主负责 title、summary、boundaries、evidence_ids 与 trend_coverage；snapshot 直接复制 prepare 的值，不让模型编造摘要。`review` 记录真实宿主模型标识、Prompt 版本及时间；精确模型标识不可得时用 null，不冒充后端 API 快照。

```json
{
  "snapshot": {"evidence_sha256": "复制 prepare 值", "records_sha256": "复制 prepare 值"},
  "review": {"model": null, "prompt_version": "2.2.0:user-research-gaps", "reviewed_at": "实际时间"},
  "directions": [{
    "id": "user-direction-01",
    "title": "来自用户回答的具体设计议题",
    "summary": "保留接受、拒绝、条件和来源品类的归纳，不将提及写成共同偏好。",
    "boundaries": ["实际反例或适用限制"],
    "evidence_ids": ["当前用户证据 ID"],
    "trend_coverage": [{"record_id": "当前趋势记录 ID", "status": "unmentioned", "reason": "核对全文后的理由；须覆盖全部选中趋势"}]
  }]
}
```

最终 `user_research_gaps.status=reviewed` 表示这部分已核对并编译，`directions` 仅含符合门槛的方向；被人数或覆盖门槛排除者只在结构化诊断中保留。主卡队列的 complete 不代表该补充步骤已经完成；交付时同时核对 completion.user_research_gaps_status。
