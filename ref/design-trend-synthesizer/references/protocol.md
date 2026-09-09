> 本页仅用于2.x历史流程；新任务使用 [3.0轻量流程](lean-workflow.md)。

# 跨 Agent 执行协议

版本 2.3.0。流水线仅需 Python 3.10+ 标准库，生成的 messages 全部为文本。宿主直接执行任务包，或提供显式适配器给 runner；不读取图片、不访问输入 URL。

## 输入与参数

--trends 指向含 trends 数组的 JSON，--users 指向含 users 数组的 JSON，记录必须有唯一 id。原始字段规则见 [evidence-rules.md](evidence-rules.md)。

| 参数 | 含义 |
| --- | --- |
| --start-date / --end-date | YYYY-MM-DD 闭区间，可只设一端，仅筛趋势 release_time |
| --undated exclude/include | 默认排除未知日期；纳入也不计近期信号 |
| --as-of | 近期判断基准日，默认运行日，续跑保持不变 |
| --project-root | 默认当前目录，决定输出位置与图片项目相对路径 |
| --output | 省略时生成 data/result/high_trend/<UTC时间及随机后缀>/；显式路径作为本轮目录 |
| --batch-records | 提取每批最多记录数，默认 32；同一用户内按完整请求和预计输出量合批 |
| --batch-chars | 默认 16000；提取包含完整 system+user 消息正文、提示词和模板，其他阶段计 payload 及去重后的源上下文；不是 token 限额 |
| --extraction-observations | 单批提取观察上限，默认 64，可设 1–128；与记录数、字符数共同约束批次 |
| --max-trends | 最终最多方向数，默认 8，可设 1–12，不强行补足 |
| --include-vl-text | 纳入已有视觉分析文字，默认关闭 |
| --model | 声明本轮请求模型；不提供时关闭提取缓存，可手动执行 |
| --model-parameters | 影响输出的模型参数 JSON 对象，默认 {}，禁止把密钥放进参数 |
| --cache-dir / --no-cache | 默认缓存位于项目 data/result/high_trend/_cache；可改目录或完全关闭 |
| --dry-run | 核对范围、预计任务数、逐批记录/字符/观察预算与缓存命中，不创建任何目录或文件 |

release_time 接受 ISO 日期或以 YYYY-MM-DD 开头的时间字符串，按源日历日截取，不跨时区换日。空值为未知，其余非法值报错；起点晚于终点报错。manifest 保存日期、输入 SHA-256、配置、模型配置和版本；records 保存文本投影及来源、图片索引。

正式 prepare 返回 run_dir。预览不预留目录，不可拿预览路径续跑。非空目录拒绝覆盖；status/next/accept/split 必须使用正式运行路径。旧版本任务必须由旧 Skill 执行，2.1 不修改或转换 1.0/2.0 的运行记录。

## 提取缓存

缓存仅包含用户问答、用户需求及无归属需求的逐记录 extract 结果，不缓存趋势、候选或结论。记录键覆盖完整文本投影、用户身份和画像、模型配置、Skill/提取指令/紧凑回复契约版本；不包含源文件路径、数组下标、趋势日期范围或全局批次编号。

accept 只有在 execution.model_profile 与 manifest 完全相同，且存在有效 messages_sha256 时才写入缓存。缺少元信息时照常接收合法回复，但不缓存。宿主应声明完整实际参数；不能只声明一个“默认模型”名称来混用其他参数或模型。标准 runner 自动传这些字段，手动宿主可使用 --execution 元信息文件。

逐记录补齐后编译的回复可能来自多次模型调用，execution.mode 为 `compiled_record_repair`。它保留每条记录的实际调用来源，不提供虚构的单次 messages_sha256，因此不写入上述缓存；真实调用用量仍只在 attempts 中逐次统计。

```json
{
  "model_profile": {"model": "实际请求模型", "parameters": {"temperature": 0}},
  "messages_sha256": "实际发送的 messages 按本包 core.digest 计算的 SHA-256",
  "attempt_file": "本轮内的原始调用记录路径"
}
```

缓存命中重新校验摘要、完整原文引用、字段、立场和覆盖，再以当前任务 ID 接收，input_tokens/output_tokens=0 表示本次复用未调用模型；原始调用用量保留在原运行。execution.cache_sources 记录原始运行、任务、模型、Prompt、执行时间、请求和回复摘要。内容或画像改变只使对应记录失效；模型、参数或提取规则改变使对应配置的缓存不匹配。损坏缓存列入 cache_report 并回退正常提取，不自动补造内容。

图片不进缓存。即使用户源文件重新排序或移动，输出 json_pointer、source_file、源哈希和本地图片路径也从当前输入计算。2.3 的用户提取语义契约、规则和模板未变，保留 2.1 提取缓存内容键，并用当前契约重新校验、保留原调用来源。旧 1.0/2.0 缓存不兼容；已接收任务不能直接改成新版本或手改迁移。

## 八阶段与任务预算

1. **extract**：默认最多 32 条来源、64 条观察，短正文按 160 字约一个观察位置估计；完整请求超过字符预算或预计观察超限时自动减小批次。这个估计只用于容量规划，不决定保留哪些语义。`observations` 中每项仅必填 record_id/dimensions/stance；同一事实的相关维度共用一个 ID，不同态度、对象和条件按需拆分。无观察的记录必须在 `skipped` 恰好出现一次，解释 not_design/unclear；不让模型重复声明已提取记录的 coverage。
2. **theme**：对本轮可配对设计维度内的用户观察按完整证据和问答源上下文分批，最多 32 条输入、8 个主题。所有输入证据恰好归入一个主题或 deferred。主题保留立场和条件，不为压缩而合并相反要求；无法配对的维度留在证据索引和召回报告中。
3. **propose**：读取用户主题摘要及分立场代表，与维度相交的趋势组合；每任务最多 8 个主题（仍受完整源上下文预算限制）、4 个候选，每候选最多 8 条证据。trend_basis/user_basis 分别解释双侧依据，共同覆盖引用；shared_principle 写双方共同支持的最小命题，application_hypothesis 单独列延伸。允许零候选，所有未使用代表证据必须 deferred。
4. **screen**：独立核对至多 8 个候选及原文，逐候选 accept/reject 并解释；只有双方确实支持共同原则才通过。拒绝理由进入最终校验报告，不能因两个引用 ID 都存在就通过。
5. **merge**：按短命题与来源数量分轮归并，同机制才合并；每个候选恰好归组或暂缓。多批每轮有界缩减至 max_trends，不把暂缓当作无价值。
6. **audit**：对每个候选维度的全部已提取证据分批审核，每任务最多 24 条。support/counter/conditional/unrelated 全覆盖；不同维度标签不会重复计同一证据或用户。
7. **draft**：依据程序统计与分立场代表，单次写一张卡；字符预算内固定保留双侧支持和已有反证。全部代表反证必须被 boundaries 引用。
8. **review**：独立审核一张卡，approve/revise/reject；revise 给完整替代卡，其他情况 card=null。模型审核与人工确认状态分开。

主题、候选、依据核对、反证、撰写及审核使用任务级 source_records[record_id] 回查完整字段，通过 source_records 中的 user_id 读取 profiles[user_id]；同一长回答与同一用户画像分别去重。所有必要上下文仍超过预算时明确报错并要求新运行调大预算，不截断原文。

retrieval_report 保存每个主题的全部成员、代表 ID、未成为代表的成员、未配对证据、双方维度数量和实际候选任务数。配对维度取主题成员已有维度的并集，不能因为摘要漏写某维度而失去召回。代表按不同立场、不同用户选取；摘要与代表不足以证明全部成员支持，最后仍逐证据 audit 再计算人数。此策略不能声称已证明召回率达到 100%；未配对及暂缓清单保留供复核。

## 紧凑提取输入与回复

extract 发送 [紧凑输入](compact-input.md)中的表格结构；文中的 records/fields 是还原后的逻辑视图。不要手写或改动请求来压缩，代码统一生成实际消息并计算预算。回复的 record_id 使用当前输入行的短 ID，代码按冻结映射恢复后再执行原契约校验。

每条观察仅必填 `record_id`、`dimensions`、`stance`。默认字段为趋势 `summary_zh`（字段不存在才回退 `title_zh`）、问答 `ai_analysis`、需求 `ai_index`。省略 `quote` 表示使用所选字段的**完整原文**，只允许原文不超过 600 字；长文本、分立场或分对象观察必须显式给连续引文，程序不截断、不补写解释。

```json
{
  "job_id": "当前实际作业ID",
  "observations": [
    {"record_id": "当前输入记录ID", "dimensions": ["touch"], "stance": "support"}
  ],
  "skipped": []
}
```

`field`、`quote` 和 `image_roles` 按需提供；图片角色仍须模型依据实际语义判断，未知保持 unclear。skipped 每项为 record_id/status/reason，仅允许 not_design/unclear；其记录不能同时有观察。观察记录集合与 skipped 必须完整覆盖全部来源。

extract 模型侧 `job.payload.profiles` 是每用户只出现一次的画像列表，context 中的 meta.profile 以零基下标关联，并核对该项 user_id；还原后的 records 保留 user_id 和全部文本字段。后续阶段的 profiles 仍按 user_id 索引。磁盘 jobs 保留完整逐记录画像及冻结短 ID 映射，供校验和缓存使用。接收凭证保存通过校验的紧凑回复，代码随后恢复 quote、field、coverage 和图片路径；兼容输出的 claim 等于原文 quote，不是生成的观点，空 category/context/user_value 不表示原文没有条件。后续模型输入省略这些重复字段，完整来源仍在 source_records 中用于深入归纳与审核。

接收前由代码执行保守 JSON 语法整理和 `extract_metadata_v5` 元数据整理，再严格校验全部证据及覆盖。语法操作只处理完整 JSON 围栏、外围 BOM/空白及字符串外尾逗号，不能补全截断、提取散文中的局部对象或接受重复键、非有限数值。元数据只按可机械核实的来源关系整理，不猜测引文、立场或图片编码。详细允许条件与留痕见 [code-repair.md](code-repair.md)。

手动 accept 和 runner 都保留发生整理前的内容及摘要；元数据整理另存 original_response 和 execution.normalization，语法整理保留原始文本并记入 execution.json_syntax。通过校验的结果仍遵守 2.3.0 紧凑模型契约，宿主执行规则单独版本化为 `2.3.0:code-repair-3`。

extraction_batch_preview 列出逐批记录数、完整消息字符数、预计观察数和缓存状态，汇总待调用输入字符。该预览不调用模型，也不能估算实际输出 token、推理 token 或耗时。

## 接收与续跑

jobs/JOB_ID.json 与 requests/JOB_ID.json 是不可手改的分配记录。每个请求包含实际限额、当前任务模板和 messages。每个实际模型请求使用独立上下文，回复为 UTF-8 JSON 对象；禁止重复键、NaN 和无关字段。重试或缺口补齐可能使一个正式任务对应多次调用，不得把这些调用合记为一次。

- status 只读；next 只在当前阶段全部接受后推进。--limit 只限制显示条数，不改变工作量。
- accept --response FILE --model ACTUAL_MODEL 先校验再接收；可选 --execution FILE 传宿主元信息、--input-tokens/--output-tokens 传已知用量，未知留空。
- 相同任务和相同回复重复接收幂等；不同回复不覆盖。修订已接受分析需要新运行。
- split 可拆未接受的 extract/theme/propose/audit，保留原父任务与 superseded 关系；重建子任务源字典，原记录覆盖不重不漏。screen/merge/draft/review 不拆断单卡或单命题。
- 独立模型调用可以并行；同一运行的 accept/next/split 写操作串行。runner 使用进程锁，runner 活跃期间不要另起手动写入。
- 有效回复已落盘但未接收，续跑优先恢复接收。崩溃、失败及重试计数持久保存，不清零、不重做已接受任务。
- extract 失败时，代码可复用历史中每条来源最新的完整合法观察/跳过声明组；同一记录包含坏项时不能只挑合法项保留。仅对未解决的完整原记录形成有效子请求，原正式 job/request 和来源内容不变；全部组齐备后由代码编译，再严格检查原任务观察预算及全量覆盖。
- runner 默认最多追加 2 轮记录补齐，`--record-repair-rounds` 支持 0–2；传输重试保持同一子请求和轮次，任务传输失败仍累计最多 3 次。全批没有合法记录组时不另开整批重试，历史校验失败数不清零。设为 0 关闭追加补齐调用，仍可执行无调用的代码恢复。

自动宿主的分类、退避、暂停与适配器协议见 [host-adapter.md](host-adapter.md)，记录选择与编译追溯见 [code-repair.md](code-repair.md)。达到常规校验上限后，先在已有授权内执行代码恢复及有限缺口补齐；上限本身不构成再次审批的理由。仍未解决则保留问题，不能无限重试。输出截断可拆批；服务故障不能靠生成新子任务规避失败额度。

## 结果

本轮目录统一保存 manifest、records、cache_report、jobs、requests、accepted、evidence、themes、retrieval_report、assessments、state 及模型宿主记录。主卡由代码生成 high_potential_trends.json / jsonl、report.md 和 validation_report.json，completion.json 最后落盘。complete=true 仅表示主卡队列完成；继续按 [用研补充方向](user-research-gaps.md) 分包核对并执行 user_gaps.py publish，补充 user_research_gaps。status.deliverable_complete=true（主卡完成且补充状态 reviewed）才表示两部分都完成。部分预览单独标注自身范围，不能据此将暂停的原运行标为 complete。

JSON schema_version 为 design_trend_insights_v2。每张卡带 source_evidence、程序 support_statistics、image_refs 和 human_review_status=pending；不再输出 validation_questions。补充部分仅含多数用户提及且本轮趋势未覆盖的方向，不列未入选文章；人数和占比由代码按当前分母去重计算，不能解释成共同偏好。最终 execution 保留实际模型、Prompt、时间、输入输出摘要及宿主/缓存来源。图片只关联已有文件，不复制、不下载、不解码。

退出码 0 或 runner complete 不表示用研补充已经完成，交付仍须检查 user_research_gaps_status。暂停时报告阶段、待办数量、失败原因与 run_dir；没有候选通过时生成空结果并说明范围，不伪造完成或凑数量。

## 耗时观测

runner 停止或完成时自动保存 performance_report.json，也可通过 pipeline.py performance --run RUN 单独统计。兼容旧 host 和新 runner 的逐次调用记录；手动宿主没有调用计时日志时，报告明确无样本，不从接受时间猜耗时。

各阶段保留调用次数、成功/失败数、时长中位数、P95、最大值、平均值、总调用时间及失败调用占用。slowest_single_call_stage 按单次中位数排序，largest_total_call_stage 按总调用时间排序；两者可能不同。未结束调用、缺时长和缺用量分别记录；缓存命中不算模型调用，重试按实际次数计入。并发下调用耗时之和不能当作用户等待时间，首调用到末调用的墙钟跨度还包含人工暂停、退避和排队。
