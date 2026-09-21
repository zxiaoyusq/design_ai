请使用 `multimodal-design-dna-multitag-extractor` 分析随本请求提供的单张图片。

要求：
- 只选择并分析一个主物品；
- 根据可见对象依据启用 profile，先提取规范 DNA；
- 独立判断每个扁平风格标签，不强求多个标签；
- 对返回标签完成成对关系与混淆边界仲裁；
- 身份、Logo、角色或联名信息只记录到 IDG-05/07/09，不生成身份风格标签；
- 输出标签强度、证据、组合摘要和知识库外新 DNA；低置信但有值的字段用自身 `confidence` 表达；
- 严格返回符合 Skill 内置 JSON Schema 的 JSON，不输出其他文字。

可选业务备注：
{{business_notes_or_category_hint}}
