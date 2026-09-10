> 本页仅用于2.x历史流程；新任务使用 [3.0轻量流程](lean-workflow.md)。

# 显式宿主适配器

`scripts/runner.py` 只依赖 Python 标准库，不绑定 Agent 框架、仓库、环境变量文件、模型服务或凭据。宿主显式提供一个可执行适配器；实际模型、网络与认证配置都由该适配器负责。Skill 不推断凭据，也不默认发起模型调用。

## 启动与续跑

先用 2.3.0 的 `prepare` 建立运行，并明确 `--model` 和 `--model-parameters`，使 `manifest.model_profile` 为：

```json
{"model": "宿主请求的模型标识", "parameters": {"temperature": 0}}
```

无模型配置的运行仍可由 Agent 手动执行任务，但不能交给 runner。旧 1.0.1/2.0.0/2.1.0/2.2.0 运行不能混入 2.3.0 宿主。

```bash
python SKILL_DIR/scripts/runner.py \
  --run /path/to/run \
  --adapter-command-json '["python", "/path/to/adapter.py"]' \
  --concurrency 2 --max-jobs 3
```

正式执行去掉 `--max-jobs`；续跑使用同一 `--run`，已有接受记录和有效回复会复用。`--max-jobs` 限制本次进程选择的不同任务数，任务内部重试仍遵守各自额度。

`--record-repair-rounds` 默认 2，可设 0–2，控制提取任务在复用合法记录组后，最多追加多少轮缺口补齐。设为 0 关闭这些追加调用，仍允许代码直接恢复历史完整结果；它不清零既有失败次数，也不增加传输失败额度。

默认并发为 2，建议不超过 4；宿主明确传参时最大允许 16。过载只会降低并发，之后不会自动加回。并发上限不是模型服务的容量保证。

runner 在 `run/runner/runner.lock` 获取非阻塞独占锁。其他宿主写入口必须使用同一锁，或确保此 runner 已结束；不要同时执行 CLI `next`、`accept`、`split`。模型调用在线程中并行，阶段推进、接收和运行状态写入均在唯一协调线程中串行进行。本版不自动拆分任务。

## 适配器输入

runner 用 `subprocess.run(..., shell=False)` 执行参数数组，并在末尾追加：

```text
--request /absolute/path/request.json --result /absolute/path/result.raw.json
```

适配器必须读取请求文件并将完整 JSON envelope 写入结果文件，以退出码 0 表示已正确交付 envelope。源文本始终位于请求文件中，绝不插入可执行命令。参数数组支持含空格的文件路径，不要使用 shell 命令字符串。

请求包含：

```json
{
  "job_id": "当前作业ID",
  "messages": [{"role": "system", "content": "任务规则"}, {"role": "user", "content": "任务数据"}],
  "model_profile": {"model": "请求模型", "parameters": {}},
  "job_sha256": "作业哈希",
  "request_sha256": "原始Skill请求哈希",
  "messages_sha256": "此次实际消息哈希",
  "prompt_version": "2.3.0:extract",
  "runner_prompt_version": "2.3.0:code-repair-3",
  "started_at": "UTC时间"
}
```

宿主应原样传递 `messages`，按 `model_profile` 选择模型及参数；不要追加改变研究任务的隐藏语义规则。可以采用流式网络传输，但必须等完整文本结束才交付 envelope。适配器内部应关闭隐式重试，由 runner 统一记录每次调用；单次适配器进程最多执行 180 秒。

提取缺口补齐请求另外带 `record_repair`，记录补齐轮次、有效子请求和保留组计划的摘要。它保留原任务 ID，但 messages 中只包含尚未解决的完整原记录及剩余观察预算；正式 jobs/requests 文件不变。适配器无需拼接旧结果或处理记录选择，仍只发送收到的 messages 并交回原始回复。每次实际 messages 都单独计算哈希，不能拿原始整批消息哈希替代子请求哈希。

## 成功、内容失败与服务失败

成功 envelope：

```json
{
  "status": "ok",
  "response": {"job_id": "当前作业ID", "observations": [], "skipped": []},
  "raw_response": "模型原始回复全文，建议提供",
  "model": "实际返回的模型标识",
  "model_profile": {"model": "请求模型", "parameters": {}},
  "input_tokens": 123,
  "output_tokens": 456
}
```

上面的 `response` 仅演示 envelope 结构；真实任务仍必须按阶段契约填写完整证据与覆盖。`raw_response` 可省略，此时 runner 保存并回传 `response` 对象的 JSON 序列化。提供原文时，经允许的语法整理后的解析值必须与非 null 的 `response` 相同；不允许适配器借 response 改写模型内容。

模型返回不合法 JSON 时，应提供 `status="ok"`、`response=null` 和完整 `raw_response`，仍附真实模型与匹配的 `model_profile`。这表示模型调用已经结束，内容需要校验；不得将其误报为网络故障。若既无对象也无原文，runner 视为适配器协议错误，不会虚构回复进行修复。

`input_tokens`、`output_tokens` 可以省略或为 `null`，未知用量不会被伪称为零。非空值必须是非负整数。返回的 `model_profile` 必须与 manifest 完全一致；`model` 记录服务实际报告的模型标识，可与请求别名不同。

服务失败 envelope：

```json
{
  "status": "error",
  "category": "rate_limit",
  "message": "不含凭据的明确错误描述",
  "retry_after_seconds": 20
}
```

类别只有 `overload`、`rate_limit`、`timeout`、`transport`、`authentication`、`permanent`。适配器应主动清除错误消息中的凭据和敏感连接信息。普通异常、非零进程退出、缺结果、无效 envelope 和未知类别均视为永久故障，不猜测重试。

## 有限重试与暂停

- JSON、证据和覆盖一直由代码校验。在计为内容失败之前，代码先整理完整 JSON 围栏、外围 BOM/空白、字符串外尾逗号，再执行 `extract_metadata_v5` 元数据整理和严格校验。不能补全截断响应、从散文抽取对象或猜改引文与立场。完整规则及逐项追溯见 [code-repair.md](code-repair.md)。
- 传输类（过载、限流、超时、连接失败）累计失败最多 3 次；延迟为指数退避加随机扰动，并且不早于 `retry_after_seconds`。过载/限流从至少 10 秒起步，普通传输故障从 2 秒起步；模型内容错误不占传输额度。
- 常规内容失败上限为 2 次；未进入记录补齐的重试附上一份原始失败回复及具体错误。提取的附加诊断由同一校验器产生，最多 8 处、4000 字符，不替模型选择引文或补造观点。原始首个错误保留在 outcome.error，附加提示保存为 repair_feedback。
- extract 一旦已有完整合法记录组，就优先复用最新有效整组，仅为未解决的原记录生成有效子请求；代码不把同一记录内的坏项删除后拼出“合法”片段。默认最多追加 2 轮缺口补齐，轮次独立记录，不清零累计 validation_failures；全批没有合法组时不开额外整批重试。旧尝试已经足够覆盖全部记录时直接零调用编译。
- 传输重试复用同一补齐子请求、messages 和轮次，不占新补齐轮次；传输失败仍在原任务累计最多 3 次。常规失败数、补齐轮次和尝试记录跨重启保存，不能通过重启、拆批或重置状态扩充额度。
- 过载或限流令当前并发减半，最低为 1。连续 3 次触发后停止新派发，收齐已经发出的调用并保存冷却状态；冷却至少 30 秒且尊重服务的等待建议。runner 随即退出，不自动等待并重新开启无限循环。冷却未结束时再次启动会返回暂停状态。
- 某个任务达到常规校验上限时，先执行代码恢复及尚有额度的缺口补齐；在既有任务授权内继续这些步骤，无需仅因次数上限再次申请批准。仍未解决或遇到一般永久错误时保留问题，并允许其他独立任务完成；认证错误会停止新派发并收齐在途结果。任务未完成时阶段不会继续，不能无限重试。runner 不自动拆分正式任务或重写已接受结果。
- SIGINT/SIGTERM 停止派发新任务，保存在途调用结果后退出。强制终止留下的完整适配器结果可以恢复；没有完整结果的已开始尝试会计为一次传输失败，不能清空计数重试。
- 续跑时，旧失败原文若经代码整理即可通过，直接恢复接收；历史合法记录组若已覆盖全批，也直接编译并再次严格验收。保留原尝试 outcome 和累计失败数，另外记录恢复时间、原始来源及摘要；零调用恢复不重复统计原调用 token。需要模型补齐时只按真实新增 attempt 计用量。

退出码：`0` 仅表示流水线 `complete=true`；`2` 表示阻塞或宿主错误；`3` 表示试跑数量已达、冷却或中断。退出本身不等于研究已完成，应检查 `runner/summary.json`。

## 留痕文件

每次尝试写到 `runner/attempts/<job_id>/<序号>/`：

- `request.json`：实际消息、模型配置、Prompt 版本、开始时间与输入哈希。
- `result.raw.json`：适配器原始 envelope；适配器自身未完成时另存 `adapter_failure.json`。
- `model_response.raw.txt`：完整模型文本，含失败回复。
- `response.json`：经可选代码整理或记录编译后，通过正式任务契约校验的回复。
- `json_syntax.json`：仅语法整理发生时生成，记录原始文本摘要、解析值摘要与操作列表。
- `normalization.json`：仅发生代码整理时生成，记录规则版本、前后摘要、原文路径及逐项差异。
- `subset_response.json`：记录补齐调用通过有效子请求校验后的回复；编译结果另存 response.json，不替换模型原文。
- `outcome.json`：结束时间、分类、实际模型、用量与校验错误。

`runner/state.json` 保存失败次数、记录补齐轮次、可再次派发时间、当前并发和冷却状态；`runner/summary.json` 保存退出状态、接受总数 `accepted_jobs`（含缓存）、本 runner 接受数 `runner_accepted_jobs`、代码恢复数 `code_recovered_jobs`、记录编译接收数 `record_repaired_jobs`、阻塞任务与已知用量。缺少用量的尝试单独计数。

接收调用传入 `execution={model_profile, messages_sha256, attempt_file, runner_prompt_version, started_at, finished_at}`，其中 `attempt_file` 指向本轮尝试的 `request.json`。已获得合法结果但尚未接收时，先验证原始任务与请求哈希，再直接接收，不重新调用模型。缓存复用继续由 Skill 的准备与接收流程管理，runner 不建立另一套缓存。

上面的 execution 用于单次回复；多次调用编译采用 `execution.mode="compiled_record_repair"`，保留每条来源的原记录/回复/请求摘要、实际模型、消息哈希和执行时间，补齐计划放在 `runner/record_repairs/`。此类凭证没有虚构的单一 messages_sha256，不写入要求该哈希的提取缓存；用量仅在真实 attempts 中统计一次，不在编译凭证重复累加。计划与全部原始回复均保留供复核。

## 使用本项目已有模型服务

本仓库另提供 `backend/scripts/design_trend_model_adapter.py`，复用后端集中配置和模型目录。它不是 Skill 的运行依赖；复制 Skill 到其他项目时可使用宿主自己的适配器。项目适配器要求显式 max_tokens，保留原始模型文本，不修复 JSON，并关闭 SDK 自动重试。

在本项目用 `prepare --model 请求模型 --model-parameters '{"max_tokens":12000,"temperature":0}'` 建立新运行后，将适配器参数数组设置为：

```json
["/path/to/python", "-B", "/path/to/project/backend/scripts/design_trend_model_adapter.py"]
```

调用与日志中不写入密钥。若提供方未报告具体模型，结果保留请求模型并显式标注 model_reported_by_provider=false；不能将其描述为已核实的上游快照。

每次停止或完成还会生成运行根目录的 performance_report.json，summary.performance 给出报告路径及按单次中位数、累计调用时间排序的最慢阶段。统计包含实际失败尝试，不把缓存命中或未知时间作为零秒调用。
