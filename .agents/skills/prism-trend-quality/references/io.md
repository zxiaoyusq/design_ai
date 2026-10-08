# 棱镜 · 趋势图片入库判标：输入输出与实现

Skill 1.2.0 新图默认使用 `cmf-reference-curation-v0.8.0`；保留 v0.7 的参考就绪度语义，省去模型生成的结构化解释。小样本验证不证明全图库精确率。

## v0.8 极简入口（当前默认）

从工程根目录使用 Python 314 环境运行 `backend/scripts/run_trend_quality_compact.py --out <新批次目录> --images <图片路径...>`，只做离线准备；随后对同目录执行 `--out <批次目录> --execute` 才调用模型。日常默认仅 `gemini-3.8-flash`；显式 `--models` 可选择工程模型。本次小样本中 GPT 的两张用户反例均误判为通过，不作为默认替代模型，也不默认双模型复核。现阶段该入口是候选判标工具，未接管网页或生产图库写入。

- 调用前仍由上游核实来源；非趋势绕过，校准图只作 calibration。不能根据图片外观猜来源。预处理、模型调用位于 `backend/app/agents/trend_quality.py`，规则与解析位于本 Skill；二者配套使用。
- 只发送当前图与 [v0.8 提示词](prompts/curation-v0.8.0.txt)。模型输出 `PASS` 或 `FAIL`；`REVIEW` 是保留旧 uncertain 语义的内部待复核状态，不是第三种筛选结论。不要附带正反样图、DNA、文章、标签或历史结论。
- `compact.evaluate(raw, truncated=False)` 只接受完整单词；拒绝附加解释、JSON、空回复与截断。输出中的 `decision` 仅 PASS／FAIL／null；另有 `status=complete/needs_review/invalid_output`。网络或超时为 execution_error，不能按不通过统计。没有模型生成的 reason/evidence，不伪造理由；适配器仅对 v0.8 允许缺少 reason，标记 reason_source=not_requested。
- 默认最长边1600、质量92、4:4:4 JPEG，不裁切或放大；处理 EXIF 方向；透明图保留 PNG 透明通道。小图且不超过512000字节不重新编码，大文件才压缩。保留原文件、原图／发送图SHA256与尺寸；原图细节待人工按需复核。缩图仍有细节损失风险，当前验证规模不能证明所有材料纹理图效果不变。
- 每图一次调用；网络 max_retries=0，DeepAgents 工具循环也被请求计数器阻止；60秒全流期限。格式错、截断、超时和未决均不自动追加模型。输出预算4096包含隐藏推理，不能因只显示一个词就把预算压到几 Token；目前保留 GPT low 与 Gemini 原有推理设置，未声称关闭 Gemini thinking。
- submitted 账本在请求前独占创建；已有提交（含未知／失败）拒绝整批重发。冻结提示、图片与代码哈希，记录模型参数、时间、原回复及供应方用量；检查来源和人工确认后才由上游决定入库。本入口始终 production_admission=false。
- `report.html` 只列图片、判定和耗时；完整追溯在 manifest.json、results.json、calls/。批次不附加第二模型复核；比较模型仅限用户明确要求或本次小样本优化验证。

离线验证：在 backend 目录执行 `conda run --no-capture-output -n 314 python -B -m unittest tests.test_trend_quality_compact tests.test_trend_quality_benchmark -v`。下面的 v0.7 字段、格式补查与 curation.resolve 契约仅用于历史回放或明确要求详细解释的旧版本，不用于 v0.8 默认调用。

## v0.7 历史契约（冻结）

Skill 1.1.0 使用 `cmf-reference-curation-v0.7.0`，基于用户提供的 5 正例、5 反例调整参考就绪度。历史版本分开记录。

## 新图调用与输出

1. 调用前由上游核实 `image_id/source_kind/provenance`。research/generated/unknown/synthetic 绕过；用户校准集只作 calibration。渲染或绘画是视觉表现方式，不能据此外观把真实文章图片的来源改成 generated。
2. 只发送当前原图（或有哈希的固定预处理图）和 [curation-v0.7.0.txt](prompts/curation-v0.7.0.txt)。不得附正反标签、历史样图、文章或旧结论。首次与补查共用该提示词。
3. 模型输出交给 `prism_runtime.quality.curation.evaluate(features)`。结构有效后，`ready` 且设计信号具体、可读、无 veto、有证据才 PASS；`weak` 为 FAIL；`uncertain` 为 `decision=null/status=needs_review`，不能作为审美淘汰。
4. 由 `curation.resolve(primary, confirmation=None)` 保留原记录并组合状态。有效 PASS/FAIL 不自动复核；uncertain 交人工。仅 HTTP 200 且模型结构无效可独立补查一次，不把首次回答放入补查上下文。元数据／身份错误先本地修正，网络／授权／限流错误停止自动请求。
5. 结果是入库候选，`production_admission=false`；调用方保留人工确认入口。模块不提供网络调用器、任务调度器或生产写入。

`evaluate` 只校验结构和逻辑一致性，不证明模型描述确实对应像素；视觉证据的质量仍依赖模型及人工校准。

## 执行记录

`primary`/`confirmation` 都是调用方保存的字典：

```python
from hashlib import sha256
from prism_runtime.quality import curation

primary = {
    "image_id": "上游稳定身份",
    "version": curation.PRIMARY_VERSION,
    "image_sha256": "原图字节的64位小写SHA256",
    "input_image_sha256": "实际发送图字节的64位小写SHA256",
    "prompt_sha256": sha256(curation.PROMPT_PATH.read_bytes()).hexdigest(),
    "model": "实际模型版本",
    "parameters": {},  # 写入真实参数，不能把历史发布参数当作本次参数。
    "started_at": "实际开始时间（ISO 8601，含时区）",
    "finished_at": "实际结束时间（ISO 8601，含时区）",
    "http_status": 200,
    "model_features": {},  # 模型输出的完整JSON；解析失败保留None并存raw_response。
    "raw_response": "原始响应",
    "usage": None,  # 有供应方用量就保存；不可知则null。
}
result = curation.resolve(primary)
```

补查阶段用 `curation.CONFIRMATION_VERSION`，两阶段图片 ID、原图和发送图哈希必须相同。模型可更换但须各自记录；提示词哈希必须匹配本地 v0.7 冻结文件。`source_results` 原样保留两次记录。`decision` 由程序计算；若调用方已提供，则核对一致性。错误原文、完整请求和时间由执行宿主保存；不得把普通宿主视觉试用伪造为 HTTP 200 API 回执。

## 低消耗约定

- 日常调用只读本页接口和当前提示词，不加载校准图片／分析文档、旧发布记录和其他 Skill。证据默认 1 条，最多 2 条，limits 最多 1 条；不要求长篇推理。
- 同图同配置的完整有效结果可复用；记录原图／发送图哈希、模型与参数、提示词哈希和输出字段版本。来源资格按每条引用单独判断。旧规则结果只按旧版本导出，不能冒充新判标。
- 调用方保存尝试账本，首次最多一次，格式补查最多一次；并发相同请求合并，断点恢复不重发已完成或状态未知的请求。当前离线模块本身不实现缓存、并发锁或跨恢复次数控制，接入方必须履行这个边界。
- 不因 `basic`、弱参考或已明确 FAIL 自动追加模型；不为了省量默认大幅缩图、拼多图或裁掉上下文。输出上限依据实际有效回复调整，不能把降低上限当作已实现的节省。

## 历史导出与离线验证

已有 `route_quality(image, result_loader, source_ref=...)`、`adapt_file(...)` 继续保留原判定、原版本和证据。`source_sha256` 是结果文件哈希，不是输入图片哈希。`needs_review`、`needs_confirmation`、错误与 FAIL 分开；正式准入还须上游已核实的 provenance。使用 `provenance={"verified": true, "source_ref": "可追溯来源"}` 声明核实结果；存在 `source_kind` 时须与外层一致。缺失声明仍可导出历史判定，但不标记可正式入库。

历史首次提示词为 [v0.5.2](prompts/primary-v0.5.2.txt)，复核为 [v0.6.0](prompts/confirmation-v0.6.0.txt)，组合入口仍是 `quality.policy.resolve`；不将旧结果套入新版重新计算。子图聚合继续用 `quality.policy.aggregate_children`，有未决项则 incomplete。

在工程根目录执行（均无模型调用）：

```bash
PYTHONPATH=.agents/skills/prism-trend-quality/runtime conda run --no-capture-output -n 314 python -B -m unittest prism_runtime.quality.test_quality prism_runtime.quality.test_curation -v
PYTHONPATH=.agents/skills/prism-trend-quality/runtime conda run --no-capture-output -n 314 python -B -m prism_runtime.quality --help
```

旧回放测试缺少完整历史模型回执时跳过。`export_examples/verify/build_handoff` 和 [旧源码说明](../runtime/prism_runtime/quality/README.md)、[旧共享契约](../runtime/prism_runtime/CONTRACT.md)、[历史发布](original-release-v0.6.0.json) 是历史交接资料，其模型参数、Windows 路径及验证数字不代表本次执行。

[校准分析](calibration-20261002.md) 与 [校准清单](calibration-20261002.json) 记录本次标签、图片哈希、观察和边界；[manifest.json](../manifest.json) 保留原 ZIP 来源哈希并记录本地修改后的哈希。校准图不会自动添加到正常请求。
