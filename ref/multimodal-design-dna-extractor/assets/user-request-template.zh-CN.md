请使用 `multimodal-design-dna-extractor` 分析随本请求提供的单张图片。

要求：
- 只选择并分析一个主物品；
- 根据品类只启用适用 DNA 字段；
- 提取一级风格、二级风格、设计元素、扩展 DNA；
- 输出证据、置信度、不确定字段和知识库外新 DNA；
- 严格输出符合 Skill 内置 JSON Schema 的 JSON，不要输出其他文字。

可选业务备注：
{{business_notes_or_category_hint}}
