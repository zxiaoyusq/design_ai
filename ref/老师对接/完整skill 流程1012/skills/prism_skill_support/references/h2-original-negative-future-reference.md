# 原负向未来核对义务：显式引用兼容

`H2-ORIGINAL-NEGATIVE-FUTURE-REF-001`，版本 `h2-original-negative-future-ref-v1.0.0`。这是一个 opt-in 私有消费者补丁：为模型**已经判为** `future_product_obligation`、但没有匹配既有义务索引的行，补充指向完整原负向记录的未解决核对义务。

不新增研究证据、视觉条件或问题，不把负向硬配到无关 H01 假设，不改模型状态/理由/scope，不修改原 `negative_audit` 与 `deferred_obligations` 两个数组。quality、target、H01、R5、视图、数量与视觉条件继续走原生校验。

## 最小 API

```python
from prism_runtime.clustering.h2_original_negative_future_ref_v1 import (
    derive_future_references, validate_future_references, consumer,
)

# prepared 与 proposal_ref 均为已经存在的原输入；此函数只返回新 sidecar。
document = derive_future_references(prepared, proposal_ref)
# Root 将 document 存入自己的新文件，取得本地绝对路径+SHA256 FileRef。
api = consumer("CMF", future_reference_ref=reference_ref)  # 或 "ID"
grouping = api.accept_grouping(prepared, proposal_ref)
# 后续仍通过此 api 调用 prepare_board_review / board_review_template /
# accept_board_review，确保对同一 sidecar 进行当前性回放。
```

`consumer("CMF")` / `consumer("ID")` 不提供 `future_reference_ref` 时保持原行为：空的未来义务索引仍会被拒绝。其它调用签名沿用 CMF v4 / ID v5。

新 sidecar schema 是 `prism.h2.original_negative_future_references.v1`，绑定 branch、prepared digest、**原 proposal FileRef 和内容摘要**、两个原审计数组摘要。`references[]` 只包含已经是 future 且 `deferred_obligation_indices == []` 的行。

每项包含：

- `negative_alias`、`negative_id`、`original_negative_digest`；
- `original_negative`：完整原记录，包含原文、人、对象、nullable scope、原证据及 H01 影响；
- `original_disposition` 及其摘要：完整原模型处置，reason、scope_basis、关联成员和空索引都原样保留；
- `follow_up_kind:"future_target_product_check_of_original_negative"`、`status:"unresolved"`、`resolved:false`；
- 原 reason/scope_basis 的逐字副本，以及 `adds_research_evidence:false`、`adds_visual_constraint:false`。

校验会重新从原 prepared/proposal 推导期待文档，再做带类型的 canonical SHA 比较。错 alias/ID/hash、改人、换对象、丢原文或证据、改变未知 scope、删 H01 影响、漏项、重复项、换 proposal、缺 reason/scope、改 resolved 都拒绝。原话“rough dove”等保持原样，没有代为解释。

## 保留的两条路径

已有非空 `deferred_obligation_indices` 使用原核心的整数/范围条件，不新增引用、不改索引。非法非空索引、boolean/string 索引或缺字段不会被新通路救回。

仅明确为空的 future 行可以走精确原负向引用。`current_conflict/current_uncertain` 仍产生原 blocker，不能附一个 future 引用将其放行。补充关系只是另一条可审计的保留路径，不等于义务已解决。

原 `prepared` 和 proposal 文件完全不动。新 grouping 增加单独的、被摘要绑定的 `original_negative_future_reference` 字段，保存 sidecar FileRef 和完整文档。原有两套数组及所有原处置保持原样；后续 request 绑定 grouping digest，board acceptance 保留该 grouping snapshot。不要切回未启用 sidecar 的 API 回放这份 grouping。

## 实现边界

在新的私有命名空间中加载哈希固定的 CMF v4 / ID v5 源码，并只将 `accept_grouping` 内唯一的 `future_negative_must_retain_original_obligation` guard 替换为“双路径精确验证”。AST 必须找到且只找到这一处；所有其它代码不变。原模块、现有 alias consumer 命名空间和全局函数均不改。R5 导入沿用既有精确字节 alias loader；同 ID 仍原样委托 native loader。

只读原文件、本地验证和返回对象，不执行模型、联网、获取图片、渲染或自动化。代码没有修改 Root 的实际结果或补填索引。

## 本轮真实回放

证据卡中的 U02/U03 原 prepared/proposal 均只读回放，sidecar 和审计结果保存到本 owner 新交付目录：

- U02：10 条无匹配旧索引的 future 行使用原负向引用；仍只有 6 个成员，且原 V3 变化未解决项仍阻断。
- U03：18 条 future 行使用原负向引用；仍只有 8 个成员，数量门继续阻断。
- 两份结果均保留原 18 条负向、原 6 条 deferred obligations、原模型处置、quality/target/R5/brief 身份；没有得到新视觉 PASS。

`build_delivery.py` 使用已有本地 Python/jsonschema vendor，运行精确负例和旧合成通路回归，并输出 `handoff.json`、依赖哈希、冻结旧文件前后比对、两份真实回放结果。自评范围仅为审计引用兼容及防篡改；不证明板图合格或未来产品得到用户认可。Root 负责独立复验。
