---
name: design-trend-synthesizer
description: 将已选用研聚合与趋势洞察结果轻量握手为跨品类高潜方向，保留支持分级、原对象条件、反向与未决及文章图片追溯；也兼容按日期输入原始资料。用于网页高潜趋势生成，不代替完整 H01 语义审计或视觉核验。
metadata:
  version: "3.4.0"
---

# 高潜趋势轻量握手

把两侧已形成的语义发现转换成有来源、边界与支持程度的设计方向。采用共享用研笔记和一次综合，避免每个趋势重复处理全部用研；小资料一次出稿。支持分级是模型判断，格式编译完成不代表独立语义审核或 H01 通过。

## 输入与冻结

网页优先选择一份“用研聚合”输出和一份“趋势洞察”输出，可限制趋势主题。沿用选定主题的身份、定义与边界，原文章用于支撑和查证，不绕过选择重新发现全部趋势。只将选定范围传入；没有双侧有效资料时输出空范围说明，不调用模型。

应用调用 `lean.prepare(args, source_data=bundle)`；独立执行使用：

```bash
python SKILL_DIR/scripts/pipeline.py prepare \
  --source-bundle /absolute/path/source-bundle.json \
  --project-root PROJECT --model ACTUAL_MODEL --dry-run
```

bundle 沿用 `lean_input.build_sources` 结构，含 `sources`、`inputs`、`counts`、`trend_categories`、`upstream_selection`，可带 `input_snapshots`。原始引用、父簇、原话角色、对象、正负态度、条件、未知和原文件 SHA 必须保留。模块输入以现成主题定义及代表锚点握手，`model_source_ids` 指定进入模型的摘要与用研来源；全体成员原文仍冻结并可追溯，`model_input_scope` 明确本轮未复读所有成员原文。纯摘要不构成已验证外观偏好，分级应保守。完整契约与模型运行方法见 [轻量执行说明](references/lean-workflow.md)。上游文件的 UTF-8 快照核对 SHA 后写入新运行的 `inputs/`，所有来源写入 `sources.json`；不覆盖旧结果。预览只统计范围与预算，不创建任务。

兼容原始资料模式：`--trends` / `--users` 可指定 JSON，默认新版趋势与五用户文件；`--start-date` / `--end-date` 仅筛趋势，包含两端，用研文本不按趋势日期筛选；`--user-limit N` 取原 users 数组前 N 个完整对象。相对日期以当前日历解释，不能按资料最大日期推算。

## 方法与命名

- 已有主题摘要可跨主题合包，逐条保留父主题身份；原始文章按已有 `clustering_label` 分包；同一主题的所有笔记共同考虑。已有聚合结果保留原定义与边界；仅原始资料模式才归纳类内共同表现。空标签使用“未分类”。
- 用研仅归纳一次，各趋势共享；每包默认完整消息最多 48,000 字符，单条原文不截断。默认最多 24 次调用（含失败重试），超计划预算在调用前报错，不暗中缩小输入。默认不设置模型输出 token 上限。
- 一条笔记/方向只回答一个具体设计问题。宽泛的“个性、情绪价值、生活方式”不是不同机制合并的依据。同一来源可支撑多个方向，不强制排他，不凑方向数量。
- 保留关键短原话及其编号、原角色和条件。上游分析、摘要、翻译与题干不能冒充用户原话；缺少逐字原文就明确转述，不编造引文。保留已提供的相关反对意见与范围，不要求全量否定×方向矩阵；“未发现”不能写成“没有”。
- **标题、设计问题和共同原则写跨品类设计关系**，例如“连续轮廓与克制分割”“减量留白与清晰主次”，不以外衣、运动衫、手机、家具等单一品类命名。证据的实际品类、人物和场景必须保留在边界里，不能为了跨品类命名扩大支持范围。已有父簇名称不改。
- 主卡先说明双侧实际交集，再用“可探索”给出建议。用研只谈几何时，不能因趋势有文化背景就声称用户认可该文化；个人观点不变成市场共识，原型不变成量产能力。

## 输出与审阅状态

使用普通 Markdown：`# 大趋势分类：原标签`、`## 方向标题` 与有效引用 `[T00001 U000001]`，分包综合使用 `[N0001 N0015]`。每卡补充：

```text
依据类型：anchored_extension
共同原则：通过减少分割形成清晰连续的视觉主次。
适用边界：原意见针对具体对象；迁移到其他对象仍需保留其使用条件。
反向与未决：保留已给反对意见；未提供的用户范围未核对。
```

`relation_basis` 取四者之一：

- `direct_support`：两侧明确支持共同原则且原适用范围兼容。
- `anchored_extension`：有双侧依据，但涉及对象/场景迁移或额外推断。
- `exploratory_hypothesis`：连接较弱，作为探索假设。
- `unknown`：依据不足或没有明确给出分级。

编译为 `shared_design_principle`、`conditions_and_limits`、`unresolved_questions`。字段缺少或未知编号只提示，保留正文，不追加格式修复调用。`evidence_review_status=not_reviewed`，`human_review_status=pending`；不能凭标签完整标记审核通过。人工审阅前保留 pending，不据编译成功自动通过。

正文引用是核心来源；额外背景写单独一行 `背景参考：说明 [N0008]`，不参与双侧成立、人数、分类和直接引用图库。人数由代码统计实际引用的去重用户，是包含不同态度的提及下限，不是支持率。`# 用研补充` 可保留趋势未覆盖的需求，只有引用人数严格超过分母一半才称“多数提及”；覆盖是所读摘要判断，不是市场空白。

## 文章、图片与下游交付

- 来源关系明确区分：`direct_reference` 正文引用来源；`same_cluster_association` 同父簇未直接引用文章；`visual_extension` 后续新增视觉素材。后两者不能补成双侧语义证据。
- 原图不进入模型，仅在代码旁表匹配原 URL、本地路径、文件存在状态和 SHA。同路径每次发布只哈希一次；缺图保留声明路径和缺失状态。文章配图关联不等于视觉吻合，不表示用户认可。
- 用户图只关联明确 `LIKE` / `ENJOY`：图号偏好须在原回答中实际提及；显式问答/需求正向 `ref_pic_links` 可直接关联。`DISLIKE`、`REFERENCE` 和未标注图不进图库，但相关回答文字保留用于边界。
- `source_records` / `image_refs` 保留正文引用；`associated_source_records` / `associated_image_refs` 单列同簇材料；`visual_extension_image_refs` 初始为空。原文和完整原角色见 `sources.json` / 冻结 `inputs/`，不制造新原文。
- `handoff.json` 携带上游选择、文件 SHA、来源索引、每个方向的分级/限制/未决/来源关系与实际模型执行身份。下游增加图片不能覆盖原语义、原人物、原对象或原条件。
- 交付 `report.md`、`image_paths.md`、`high_potential_trends.json`、`handoff.json`、`performance_report.json` 的真实路径。结果延续 `design_trend_insights_v3`，旧字段兼容，新增字段不冒充已经核验的事实。用量只来自日志，未知保持未知。

## 执行与验证

有适配器用脚本自动推进；没有适配器用 `next` 获取请求、将普通文本保存后 `accept --model 实际模型`。独立 CLI 的既有服务错误重试至多一次；网页执行失败不自动重试，需用户显式发起。格式不全不重试；截断保留现有内容并标明，不自动续写。无正文标空。具体命令、输出文件和旧运行兼容见 [轻量执行说明](references/lean-workflow.md)。

验证默认少量离线样本或假适配器，不未经授权全量调用模型：

```bash
python -m unittest discover -s SKILL_DIR/tests -p 'test_lean_*.py'
```

3.3 未完成运行沿用冻结旧提示词和版本缓存键；2.x 历史入口仍按 manifest 分派，新任务默认 3.4。仅需要处理历史任务时阅读 [旧版说明](references/legacy-v2.md)。
