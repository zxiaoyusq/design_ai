---
name: prism-direction-selection
description: 把第一次语义握手候选转成有明确选择依据和ID/CMF路线的设计决策。用于设计师选向或当次授权AI代选；不制造高潜分数。
metadata:
  version: "2.0.0"
---

# 棱镜｜候选方向选择

输入已通过原生引用/覆盖核验的H01候选、双侧语义依据、完整负向与未决项；输出原H01 select生成的selection及decision-log。读取 [H01与选择合同](../prism_skill_support/references/contracts.md) 和 [选择操作](../prism-h01-semantic-handshake/references/contracts.md)。

给设计师呈现：方向讲什么、对应哪些用户语义、直接支持/延展/探索的程度、涉及的原对象、矛盾与未知、独立文章来源容量、拟走ID或CMF。库内文章多不能直接等同高潜；可以说明选择判断，但没有标定体系时不编0–100分。

数量和分支按本项目要求决定；6方向、3ID+3CMF仅是历史配置。可选尚未做过DNA的方向，不能因没有缓存而排除。用研语义可以较宽泛，仍须有来源；不能自行把印度、黄金、宗教写成所有人的明确偏好。

选择由真实设计师完成，或由本次已明确授权的AI代选。记录actor、选择依据、候选ID、branch、授权证据及未选理由。历史Root授权不转移；AI代选标user_delegated_ai，不写human_confirmed。

调用原H01的select与verify，保持candidate引用、digest、negative_audit和deferred_obligations。pending模板不是批准，不用新JSON伪造一个confirmed来源。选择只是进入图像探索的资格。

把selection交 `$prism-visual-family`。若容量明显不足，提出合并上游粒度或更换候选的明确决策，留下理由；不在后台悄悄换主题或无限寻找。
