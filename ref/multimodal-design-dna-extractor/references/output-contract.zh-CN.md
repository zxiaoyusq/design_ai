# 输出协议与字段语义

完整结果文件必须是一个合法 JSON 对象，并通过 `schemas/design-dna-output.schema.json`。保存路径和对话回执不属于结果 JSON。

## 1. 顶层结构

必须包含：

- `schema_version`
- `knowledge_base_version`
- `target_object`
- `image_quality`
- `module_applicability`
- `style_result`
- `design_elements`
- `uncertain_fields`
- `novel_dna_elements`
- `evidence`
- `quality_summary`

禁止添加未定义的顶层字段。没有内容的数组使用 `[]`，单值不可得使用 `null`。

## 2. 单主体约束

`target_object` 是单个对象，不是数组。`bbox_norm` 为 `[x_min,y_min,x_max,y_max]`，取值范围 0–1，且必须满足 `x_min < x_max`、`y_min < y_max`。

## 3. 适用性与可观察性

字段层面使用：

- `applicability="applicable"`：字段适用于当前品类；只有这种字段能进入 `design_elements`。
- `observability="observed"`：图片中可直接观察。
- `observability="inferred"`：基于多个观察事实推断。
- `observability="not_observable"`：当前视角不可见。
- `observability="unknown"`：相关区域可见，但无法可靠判定。

`none` 不是可观察性状态。确认不存在某元素时：

```json
{
  "value": "none",
  "observability": "observed"
}
```

不适用品类的字段不进入 `design_elements`，只在 `module_applicability.excluded_modules` 中记录。

## 4. 证据要求

- 所有 `evidence_refs` 必须引用 `evidence` 数组中真实存在的 `evidence_id`。
- `observed` 字段至少引用 1 条证据。
- `inferred` 字段至少引用 2 条观察证据或由 2 个观察型字段形成的证据链。
- 证据描述只写可见事实，不写“高级、科技、时尚”等抽象结论。
- 证据框应位于主物品包围框内部；整体比例与整体风格可引用主物品整体框。

## 5. 置信度

置信度范围为 0–1，表示结论正确的概率，不是显眼程度：

- `0.90–1.00`：直接、清晰、定义唯一；
- `0.75–0.89`：证据较强，有轻微干扰；
- `0.55–0.74`：合理但存在明显竞争候选；
- `0.30–0.54`：弱推测，只能作为候选；
- `<0.30`：使用 `unknown` 或 `not_observable`，不要给确定值。

任何置信度低于 0.75 的已有 DNA 字段必须在 `uncertain_fields` 中有对应记录。

## 6. 不确定字段

`uncertain_fields` 不只是“低置信度列表”，还用于：

- 多候选；
- 遮挡、模糊、反射、透视或光照干扰；
- 字段适用但不可见；
- 知识库定义存在空隙。

候选值存在时，概率之和应约为 1。没有可靠候选时使用空数组，不得为了满足格式伪造候选。

## 7. 风格结果

- `classification_status="confirmed"`：主风格硬规则通过、颜色必要项通过、无排除命中、证据充分。
- `classification_status="provisional"`：最佳候选合理，但存在关键未知或图像质量限制。
- `classification_status="unclassified"`：没有风格通过适用的必要条件。

`primary_style` 最多一个；`secondary_styles` 最多两个。`candidate_ranking` 可保留未通过硬规则但相似的候选，必须写明冲突。

## 8. 新 DNA

`novel_dna_elements` 只容纳当前知识库不能充分表达的内容。每项必须：

- 有主物品内部视觉证据；
- 与已有字段说明差异；
- 给出可参数化的值类型或值域；
- 指明适用品类和设计价值；
- 标记 `new_module`、`new_field`、`new_enum_value` 或 `new_relation_rule`。

## 9. 颜色与材质

没有标准光源、色卡或可信元数据时，不得伪造高精度 NCS、CIELAB、OKLCH。材质结论是“视觉材质推断”，不能等同于真实材料成分。

## 10. 语法约束

- 结果文件只包含 JSON；
- 不使用 Markdown 代码围栏；
- 不输出注释、尾逗号、NaN 或 Infinity；
- 中文描述使用简体中文；
- 知识库英文风格名、字段 ID 和标准枚举保持原样。

## 11. 工程落盘约束

- 使用 `scripts/save_result.py` 在校验通过后写入 `data/result/`；
- 完整结果文件名为 `YYYYMMDD_HHMMSS_<图片名>_design_dna.json`；
- 时间戳使用 `Asia/Shanghai`，图片名去除扩展名并安全化；
- 同名文件不得覆盖，使用递增序号；
- 业务视图由工程根目录的 `extract_design_dna_business_view.py` 生成，并写入同目录的 `<完整结果名>_business_view.json`；
- 对话回执可以报告路径，但不得把路径添加为 Schema 外字段。
