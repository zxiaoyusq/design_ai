请使用 `multimodal-design-dna-extractor` 分析随本请求提供的单张图片。

要求：
- 只选择并分析一个主物品；
- 根据可见对象依据记录 active_profiles，只启用匹配 profile 且满足视角的 DNA 字段；
- 先提取可观察的规范 DNA，再判定一级导航标签、二级稳定风格 ID 与候选；
- 对易混候选执行异混淆特征与决定性边界核对；
- 输出证据、置信度、不确定字段和知识库外新 DNA；
- 严格输出符合 Skill 内置 JSON Schema 的 JSON，不要输出其他文字。

可选业务备注：
{{business_notes_or_category_hint}}
