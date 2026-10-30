# 趋势提案与独立复核的字段格式

`trend_text.py prepare --input articles.json --out prepared`会生成`corpus.json`及空的`proposal-template.json`。空数组是尚未进行语义分析；下面示意字段形状，不是已审阅答案。

## proposal.json

```json
{
  "corpus_digest": "复制本次proposal-template.json里的实际digest",
  "analyst": {"actor_id": "实际分析者", "model": "实际模型或unknown"},
  "themes": [
    {"theme_id": "G001", "title": "当前归纳的主题", "definition": "共同含义", "boundary": "排除什么", "design_question": "可继续探索的设计问题"}
  ],
  "assignments": [
    {"article_id": "本次真实article_id", "theme_id": "G001", "anchor": "该文text中的准确子串", "reason": "该文为何支持此含义"},
    {"article_id": "另一条真实article_id", "theme_id": null, "reason": "尚不能归入主题的具体原因"}
  ]
}
```

themes内五个字段都是非空文本。每篇原文恰好有一个主归属去向；多义关联可另记，不可复制主归属行重复计算。theme_id不为null时必须指向本次themes之一，anchor必须来自该文章的`text`（prepare把标题和摘要以换行连接）。全部文章都要保留，不能把未归类文章删除。

## review.json

```json
{
  "proposal_sha256": "本次未修改proposal.json文件的实际SHA256",
  "reviewer": {"actor_id": "实际独立审阅者", "review_kind": "ai_independent_context"},
  "reviews": [
    {"article_id": "本次真实article_id", "theme_id": "G001", "status": "uncertain", "anchor": "该文text中的准确子串", "reason": "实际审阅依据与不确定处"}
  ]
}
```

对每条非null的主归属必须恰好有一条独立复核，theme_id须对应原提案。status只能是supported、uncertain或unsupported；示例的uncertain不是默认事实，真实结论由实际语义审阅产生。未归类的null条目不用额外伪造复核行。

编译：

```text
python -B -X utf8 trend_text.py compile --corpus prepared/corpus.json --proposal proposal.json --review review.json --out compiled
```

仅supported进入主成员排名与H01簇接口；uncertain、unsupported和unassigned全部保留在coverage。改过proposal后旧review哈希失效，应按受影响内容重新审阅，不更新哈希掩盖旧审阅未看过新内容。

完整可执行合成例子在`tools/checks/test_helpers.py`的`make_trends`及相关反例中；它们只验证编译/身份规则，不当作新文章的语义答案。
