# 3.4 聚合结果轻量握手执行

默认入口`scripts/pipeline.py`，也可直接使用`scripts/lean.py`。仅依赖Python标准库，复用日期、文件保存与图片定位工具；2.x严格契约不参与新模型回复接收。

## 分类与图片

聚合结果模式沿用用户选定的父主题定义与边界，仅整理握手依据；原始资料模式在日期筛选后按 clustering_label 汇合同类文章，类内超出字符预算才分包。原始文章趋势包只含一个大类；已有主题摘要可跨主题合包，逐条保留所属主题；用研独立合包并只归纳一次。最终请求包含 trend_categories（类别、文章数、笔记 ID）、带类别归属的方向笔记及共享用研笔记；模型在每类下提炼新方向。小数据直接传按类别组织的文章和一份用研。

clustering_label 空缺进入“未分类”。结果卡的类别由真实引用来源恢复，不能由标题猜测；无结果的类别仍留在分类索引中。用户 local_paths/local_path 元数据只用于图片关联与图库展示，不进入模型文本，不读取图像像素。用户侧仅保留明确标记 `LIKE` / `ENJOY` 的图片；`DISLIKE`、`REFERENCE` 和未标注图片不会写入最终图片引用或图库。趋势文章图片不受该用户偏好过滤影响。

## 主题与来源边界

归纳与综合均在原调用内保持一个具体设计问题对应一条笔记/卡片。资料大类只是组织方式，宽泛的身份、情感或生活方式不能作为不同设计做法的合并理由。两三句内区分已有表现、用户交集和可探索做法，不增加独立审核任务。

中间与最终标题共用 scripts/lean.py 的 TITLE_STYLE，采用概念型、名词性趋势名称，具体命名示例见 SKILL.md。该规则直接参与现有归纳/综合请求及缓存键，不新增改名调用、格式校验或关键词自动改名步骤。

正文引用是核心来源。可选的单行 `背景参考：说明 [N0008]`（也兼容加粗标签）由代码提取为 `background_text`、`background_source_ids`、`background_source_records`，不进入核心 `source_ids/source_records`、双侧判断、类别、人数或 `image_refs`。同一原始来源同时出现在两者时以核心为准。未知编号只提示，不追加模型调用。无此标记的历史正文沿用原语义。

背景仍可通过 sources.json 查看；趋势配图按核心来源文章分组，不能把文章关联当作视觉匹配。正向用户图片总库存独立保留，背景关联的喜欢图片可留在总图库，但不标成当前方向的图片。格式解析只处理显式标记，不声称代码能判断主题是否应合并。

## 自动推进

准备时声明实际模型，例如：

```bash
python SKILL_DIR/scripts/pipeline.py prepare \
  --trends PROJECT/data/trend_data/article_table_2/trends.json \
  --users PROJECT/data/userreseach_data/users_selected_5.json \
  --project-root PROJECT --start-date YYYY-MM-DD --end-date YYYY-MM-DD \
  --model ACTUAL_MODEL --model-parameters '{"temperature":0}'

python SKILL_DIR/scripts/pipeline.py run --run RUN \
  --adapter-command-json '["python","/absolute/path/to/adapter.py"]'
```

本项目可直接用backend/scripts/design_trend_model_adapter.py；命令数组中的python换成实际 314 环境 Python 绝对路径。适配器管理连接配置，不把密钥写进Skill或Prompt。默认不向model_profile注入max_tokens，输出预算预估为null（未设置），由模型服务或SDK默认行为决定。仅显式提供阶段输出预算或模型参数max_tokens时保留相应限制。

适配器接收`--request FILE --result FILE`，请求含纯文本messages和model_profile。成功结果如下，模型正文无需JSON：

```json
{"status":"ok","raw_response":"## 柔和触感\n设计归纳。[T00001 U000001]","model":"实际模型","input_tokens":1200,"output_tokens":300}
```

用量可为null。服务错误用status=error及category：overload/rate_limit/timeout/transport/authentication/permanent，可附retry_after_seconds。适配器内部关闭自动重试。

脚本自动串行推进。服务错误最多重试一次，失败计入max-calls；额度跨续跑保留。较长Retry-After保存到期时间并退出，认证或永久错误停止派发。格式不齐、未知引用和空正文不触发模型纠错。总预算为最终成稿保留一次名额，未处理包标明缺口；无可用笔记不继续成稿。SIGTERM/SIGINT停止新派发并保存当前调用。

## 文件与统计

- manifest.json：来源、日期、用户范围、模型及计划预算。
- sources.json：原始文本与图片索引；requests/和accepted/保存请求与普通文字回复，notes.json保存方向编号映射。
- calls/：实际调用原始留痕；performance_report.json记录调用数、耗时、用量。缓存原调用不重复计入本轮，缺失值不当作零。
- high_potential_trends.json/jsonl和report.md：最终归纳；原文只通过sources.json定位。
- image_paths.md：第一部分汇总最终结果关联的趋势图片和正向用户图片，第二部分汇总其他明确 `LIKE` / `ENJOY`、且与第一部分去重后的用户图片；按规范化绝对路径去重；读取字节计算 SHA，不解析像素。另列同簇关联图片。
- completion.json：complete/partial/empty及has_content。partial可以交付但要说明缺口；empty不是完成研究。文件存在或退出码0不能替代状态检查。

status只返回简短状态；next最多生成一次综合任务。不要在宿主反复加载全部日志或扫描会话Token事件。常规运行在完成时读取性能摘要，用户另问宿主用量再单独核对。

3.3 未完成任务使用 `lean_prompts_v33.py` 中冻结提示；请求版本和缓存使用其 manifest 版本。

方向笔记缓存位于项目data/result/high_trend/_lean_cache/，按实际消息、模型配置和当前版本规则匹配。最后综合仍使用当前两侧笔记。未声明模型或指定--no-cache则关闭；不混用2.x观察缓存。

## 验证和兼容

验证只用1–2条趋势、2–3位用户的少量代表回答；直出、分包、缺图、预算和服务失败都用微型夹具/假适配器检查。不要为了证明效果重新跑前20用户或全量模型调用。

pipeline.py legacy显式调用旧实现；旧manifest的status/next/accept自动兼容。旧core.VERSION保持2.3，3.x单独记版本，不改变历史任务和缓存键。


## 聚合输入 bundle 契约

`lean.prepare(args, source_data=bundle)` 和 `prepare --source-bundle FILE` 使用相同结构，不再次读取默认库：

- `sources`: 短 T/U 编号 → 来源记录，沿用 `build_sources` 的 kind/id/source_id/user_id/fields/source_file/json_pointer/image_refs。
- `semantic_context` 位于每条来源内，包含父簇 memberships、原话角色、原对象、条件、态度与未决。打包时共同父簇定义在包内去重为 `semantic_catalog` + `definition_ref`，原始索引不改。图片旁表留在 `image_refs`，不进入模型。
- `inputs`: 来源键 → `{path, sha256}`。记录的 `source_file` 使用同一来源键，`json_pointer` 指向原 JSON。
- `input_snapshots`: 来源键 → `{path, sha256, content}`，content 是完整原 UTF-8 文本。校验 SHA 后存入 `inputs/0001.json` 等安全文件名；manifest.inputs 对应 path 改为冻结文件，original_path 保留原路径。预览和 manifest 不携带 content。
- `upstream_selection`: 两侧选择身份，原样保留；`counts` / `trend_categories` / `selection` 延续原结构。
- `model_source_ids` 可限定进入模型的已知来源子集；模块模式是已有趋势主题摘要及所选用研来源，完整成员文章仍在 sources，进入同簇关联旁表。`model_input_scope` 原样进入 manifest、结果与 handoff，明确模型只读主题定义与代表锚点，未复读全部成员。摘要 source_role=analysis_note，不冒充直接原话。
- 整个 `sources.json` 生成后记录 `source_index_sha256`。快照哈希不符时在派发模型前失败。

结果增加 `relation_basis` 四枚举、共同原则、适用边界、反向未决与 `evidence_review_status=not_reviewed`。没有标签仍可交付，缺失明确提示，不重试。3.4 分包笔记的支持类型、共同原则、边界和反向未决字段在最后请求中单独携带，不能随短摘要静默截掉；必要原角色、原对象语境、原文语言、翻译类型与摘要身份去重放在 source_contexts，并保留全局 model_input_scope。这里只传角色与语境，不重发全部回答。不可压缩的约束超过最终预算时明确停止，不自动增调用；3.3 最终请求沿用旧字段形状。

`handoff.json` 保存输入引用/原角色条件/来源关系/模型配置与实际执行信息。直接引用配图和同簇关联配图分数组，不扩增引用人数。每个图片项附 SHA、字节大小、身份状态和原 URL；缺失保留声明路径。视觉扩展初始为空，下游只可追加，不能改写原语义依据。
