# 用户调研数据整理

脚本 `backend/scripts/prepare_user_research_data.py` 只读提取 MySQL 用户调研数据，输出用户信息和图片信息两份 JSON，并下载图片。输出目录使用需求指定的拼写 `data/userreseach_data/`。整理过程不调用模型，不修改源数据库。

## 运行

在项目根目录使用 conda `base`（Python 3.14）环境：

```bash
conda run -n base python -m pip install -r backend/requirements.txt
conda run -n base python backend/scripts/prepare_user_research_data.py --dry-run
conda run -n base python backend/scripts/prepare_user_research_data.py
```

若仅需给已有快照补齐或刷新用户名，而源库的其他调研数据已变化，可执行：

```bash
conda run -n base python backend/scripts/prepare_user_research_data.py \
  --input-snapshot data/userreseach_data/source_snapshot.json \
  --refresh-user-names
```

该模式先要求源库有效用户的 ID/BID 与快照完全一致，再只取 `name` 更新旧快照；问答、需求、关系和图片反馈仍保留旧快照版本。图片使用现有文件缓存，不需要模型调用。姓名单独记录同步时间，不能把它解读为整批研究资料已刷新。

默认连接 `10.205.244.130:3306/tim_configcenter_pro`，用户名和密码分别读取 `backend/.env` 的 `USRDB_NAME`、`USRDB_PASS`。凭据不写入结果文件或日志。`--dry-run` 读取并检查数据，不写输出文件、不下载图片；实际运行整理命令表示确认写入本地结果。

| 参数 | 默认值 / 用途 |
| --- | --- |
| `--env-file` | `backend/.env`，凭据文件 |
| `--host`、`--port`、`--database` | 上述 MySQL 地址、端口和库名 |
| `--input-snapshot` | 从已有 `source_snapshot.json` 重建；单独使用时不连接数据库 |
| `--refresh-user-names` | 配合旧快照从数据库只更新同一批用户的姓名 |
| `--output` | `data/userreseach_data` |
| `--workers` | 12，图片下载并发数 |
| `--timeout` | 30 秒，单次网络操作超时 |
| `--retries` | 2，瞬时下载失败后的额外重试次数 |
| `--max-image-mb` | 50，单张图片下载大小上限 |
| `--resolve HOST=IP` | 可重复传入，仅本次下载使用已核实的 DNS 地址，保留原 URL、Host、SNI 和证书验证 |
| `--dry-run` | 只检查数据 |

离线重放示例：

```bash
conda run -n base python backend/scripts/prepare_user_research_data.py \
  --input-snapshot data/userreseach_data/source_snapshot.json \
  --output data/userreseach_data/replay
```

数据库读取使用 `REPEATABLE READ` 只读一致性快照。业务数据读取完成后结束事务、关闭连接，再执行本地整理和图片下载，避免下载过程长期占用数据库事务。

## 输出结构

| 路径 | 内容 |
| --- | --- |
| `users.json` | 用户信息完整包，包含用户数组及未关联的问答、需求 |
| `users.jsonl` | 每行一名用户，适合逐名或分批输入 LLM |
| `images.json` | 图片信息完整包，按实际 URL 聚合 |
| `images.jsonl` | 每行一张图片，适合分批处理 |
| `source_snapshot.json` | 白名单原始业务字段及关系数据，支持回查与离线重放 |
| `export_report.json` | 统计、关联异常、重复反馈提示及图片下载结果 |
| `images/` | 图片文件，JSON 的 `local_path` 关联到此目录 |
| `README.md` | 本次输出的简要使用说明 |

用户与业务记录的 `id`、`bid` 以字符串保存，避免大整数在下游系统中丢失精度。源字段的空值保留为 `null`，可解析的 JSON 内容转为结构化值，普通文本保留原文；脚本不推测枚举编码含义，不生成新的 AI 结论。

每名用户包含：

- `id`、`bid`、`name`：源用户的数据库 ID、业务 BID 和原始用户名。`name` 取自 `transcend_model_id_user_data.name`，空值保留为 `null`，不拆分或推断姓名。
- `profile`：`country`、`profession`、`age`、`using_mobile_phone_prices`、`using_mobile_phone_brand`、`academic_qualification`、`purchase_drivers`、`user_group_tags`、`gender`、`mobile_function_usage_preferences`。需求中重复列出的 `academic_qualification` 仅输出一次。
- `aesthetic_research`：问答数组，每条保留源 `id`、`bid`，以及 `answer_type`、`scenario_type`、`question_type`、`question`、`ai_analysis`。
- `demand_research`：需求数组，每条保留源 `id`、`bid`，以及 `ai_index`、`scenario`、`ref_pic`；`ref_pic_links` 记录图片编码匹配结果。
- `image_preferences`：该用户的图片反馈，记录 `image_id`、源反馈 `source_id` / `source_bid`、`emotion_tag` 和 `ref_pic_code`。

没有对应问答、需求或图片反馈的用户仍保留，对应数组为 `[]`。完整 `users.json` 根节点另有 `unlinked_aesthetic_research` 和 `unlinked_demand_research`；这些记录未归属某个用户，因此不混入逐用户的 JSONL。

每张图片包含稳定 `id`、实际 `url`、`emotion_tag` 集合、`enjoy_count`、`dislike_count`、其他情绪的 `other_emotion_counts`、`survey_pic_bids`、`reference_codes` 和 `responses`。`responses` 保留每条源反馈的 ID、BID 及用户 ID、BID，计数可以回溯到源行。用户侧通过 `image_id` 关联图片表。

下载记录包含 `status`、`local_path`；成功后补充实际宽高、格式、字节数和 SHA-256 等信息。`local_path` 相对于输出目录；失败时保留图片记录与源 URL，使用 `status=failed`、`local_path=null` 并记录原因。向多模态模型输入时，应读取图片文件并附加图片内容，仅传路径文本不能让远程模型访问本地文件。

## 关联与计数口径

用户取 `transcend_model_id_user_data.delete_flag=0`；问答、需求和关联记录同样只取未删除记录。问答通过 `transcend_model_a3v`，需求通过 `transcend_model_a3w`：两表的 `source_bid` 都关联用户 `bid`，`target_bid` 分别关联问答或需求 `bid`。同一用户与同一业务记录的重复关系只挂载一次。`parent_bid` 不是本数据源的用户关联键，不用它推测归属。

问答的 `ai_analysis` 包含“未提及”时，整条问答不进入用户信息或未关联问答列表；仅问题文本包含该词不会被排除。规则在整理阶段执行，数据库提取和快照重放保持一致，源快照保留原始记录供追溯。报告的 `diagnostics.excluded_unmentioned_aesthetic_research_count` 记录按源行去重后的排除数量。

图片反馈来自 `transcend_model_iduserrefpic`，要求反馈记录未删除、`id_user_bid` 对应未删除用户、`emotion_tag` 去除空白后非空。情绪标签转大写后统计 `ENJOY` 和 `DISLIKE`，其他非空标签单独保留。

图片按附件中的实际 URL 聚合，同一 URL 只下载一份。计票按源反馈记录：同一源行重复列出相同 URL 只计一次；不同源行即使用户、URL、情绪全部相同，仍分别计票，并在报告中提示重复组合。因而计数表示反馈行数，不等同于去重用户数。若一条反馈关联多个不同 URL，每个 URL 各计一次。

需求 `ref_pic` 中的 `P20`、`M2` 等编码，只与同一用户图片反馈的 `name` 精确匹配：唯一匹配为 `matched`，无匹配为 `unmatched`，对应多个图片为 `ambiguous`，同时保留候选 `image_ids`。图片表仅含符合上述条件的反馈，因此无情绪标签图片的引用可能未匹配；不跨用户寻找同名编码，不猜测替代图片。

## 源数据异常与恢复

2026-09-07 首次核实：70 名有效用户中，39 人关联 3,554 条问答，37 人关联 621 条需求。需求表另外有 44 条有效记录（数据库 ID 904–947）没有用户关系；原始字段保留在完整 `users.json` 的 `unlinked_demand_research`，标记 `link_status=no_active_user_relation`，供人工补充关系后重新整理。另有 18 条未删除需求关系同时引用不存在的用户和已删除需求，排除并计入异常报告。实际数量以本次 `export_report.json` 为准。

下载器复用趋势模块的图片校验与缓存能力：图片通过格式和像素解码检查后才保存；重跑会校验并复用完整缓存，失败或损坏图片重新下载。旧文件不会自动删除；不要向同一输出目录同时运行多个整理进程。离线重放以保存的源快照为准，需要获取新增或修订源数据时重新执行数据库提取。

本次下载发现系统 DNS 所选 OSS 加速节点间歇性 TLS 握手超时，使用另一 DNS 返回且已验证可下载的地址恢复连接。`--resolve` 只改变单个下载连接的 TCP 目标，不改系统 DNS、代理、VPN 或全局网络函数，不关闭 HTTPS 证书校验。运行使用的映射记录在结果的 `source.download_dns_overrides` 中；地址不写成代码默认值，再次使用前应重新核实 DNS 结果。

每完成 100 张图片保存一次索引，每个文件原子替换；最终以 `pending=0` 的报告为准。退出码 `0` 表示所有图片完成，`2` 表示有下载失败或无效附件 URL，数据库连接/读取失败返回 `1`。未关联的有效需求会明确保留，不作为下载失败。
