# 趋势调研数据整理

脚本入口为 `backend/scripts/prepare_trend_data.py`。它把文章信息表的每一行视为独立趋势，下载 `image_url` 的全部关联图片，并输出供后续 LLM 分批处理的数据。当前只做确定性整理，不调用模型或写入业务数据库。

## 运行

在项目根目录、conda `314`（Python 3.14）环境执行：

```bash
conda run -n 314 python -m pip install -r backend/requirements.txt
conda run -n 314 python backend/scripts/prepare_trend_data.py --dry-run
conda run -n 314 python backend/scripts/prepare_trend_data.py
```

默认读取 `ref/文章信息表.xlsx`，输出到 `data/trend_data/`；默认路径以脚本位置定位，运行时不依赖当前目录。`--dry-run` 仅检查字段、ID 和数据规模，实际执行整理命令表示确认本地数据写入。

参数包括 `--input`、`--output`、`--sheet`、`--workers`（默认 12）、`--timeout`（每次网络操作默认 30 秒）、`--retries`（瞬时失败额外重试 2 次）、`--max-image-mb`（默认 50 MB）和 `--limit`。多工作表必须用 `--sheet` 明确选择；原有必填字段缺失、重复表头、空 ID 和重复 ID 都会在下载前报错。

试跑时请指定独立输出目录：

```bash
conda run -n 314 python backend/scripts/prepare_trend_data.py --limit 5 --output data/trend_data/sample
```

## 数据结构

完整包 `trends.json` 包含 `schema_version`、整理时间、源表副本路径/工作表/SHA-256、统计信息和 `trends` 数组。`trends.jsonl` 每行一条同样的趋势，适合逐条或分批输入 LLM。

每条趋势包含源 `id`（字符串）、`source_row`（Excel 行号），以及用户指定的全部 14 个描述字段：

| 字段 | 整理规则 |
| --- | --- |
| `title_zh`、`summary_zh` | 保留原文及换行 |
| `image_url` | 保留原始 `||` 多图字符串 |
| `image_width`、`image_height` | 保留源值/空值，可无损解析的单一整数转为数值 |
| `primary_category` | 保留原值 |
| `subcategory`、`tags` | 按中英文逗号拆成数组，忽略空项 |
| `confidence` | 可解析的数值文本转为数字 |
| `language_original` | 保留原值 |
| `release_time` | 日期单元格或日期时间字符串统一为 `YYYY-MM-DD`，截去时间和时区后缀，不转换时区；空值保留 `null`，无效日期报错并指出源行 |
| `clustering_label` | 保留源值，不按逗号拆分、不重新聚类；旧表缺列或空单元格输出 `null` |
| `clust_status` | 可解析的整数文本转为整数 |
| `local_vl_info` | JSON 对象/数组转为结构化值；无效 JSON 保留原文并记录提醒 |

空标签输出 `[]`，其余空单元格保留 `null`。不修改源文件；`source/` 保留原始 Excel 副本，因此转换后的值可回查。

`images` 数组按 `image_url` 分隔后的原顺序记录图片。每个元素有 `image_id`、`trend_id`、从 1 开始的 `index`、原始 `url`、下载状态和 `local_path`。即使 URL 重复也保留各自位置，避免丢失来源对应关系。

下载成功后补充实际 `width` / `height`、`format`、`size_bytes`、`sha256`、`downloaded_at`。源行宽高不会被单张图片的尺寸覆盖。`local_path` 相对于 `data/trend_data/`，命名为 `images/<趋势ID>/<序号>_<URL哈希>.<实际格式>`。非普通字符 ID 使用哈希目录，原 ID 保留在 JSON 中。

MaterialDistrict 的 `/_next/image/` 缩放接口会限流。仅当其 `url` 参数明确指向 `https://media.materialdistrict.com/` 时，直接下载该参数指定的同一原图。原始 `url` 始终保留；本次网络请求的地址和最终响应地址分别记入 `download_url`、`resolved_url`。缓存复用时没有网络请求，这两个字段为 `null`，不推测历史重定向。

## 下载与恢复

图片以 Pillow 校验格式和像素解码，不能把扩展名为图片的 HTML 错误页当作成功。下载先写临时文件，校验通过后原子替换；尺寸使用实际图片读取结果。503、429、超时等瞬时问题允许有限重试，明确的 403/404 不立即反复请求。

每完成 100 张图片保存一次 JSON、JSONL 和报告，每个文件单独原子替换；运行结束后再统一输出最终统计。再次运行会重建索引，校验并复用相同 ID/序号/URL 的完整本地图片，失败或损坏缓存重新下载。旧 URL 对应的图片不自动删除；不要对同一输出目录同时运行多个整理进程。

失败记录仍属于原趋势，`status=failed`、`local_path=null`，保留 URL、错误、尝试次数及已知 HTTP 状态码。`download_report.json` 集中列出失败与字段解析提醒。退出码 `0` 表示图片全部完成，`2` 表示仍有图片失败，其他执行错误退出 `1`。空图片行依然输出完整趋势和 `images=[]`。

向远程多模态模型输入时，应用应读取 `local_path` 并以所选模型的图片接口附加内容；只把路径写进文本不会让模型读取本地图片。输入表已有的 `local_vl_info` 和 `confidence` 属于源数据，不表示本脚本重新验证过这些结论。

## 验证

```bash
cd backend
conda run -n 314 python -m unittest tests.test_trend_data_preparation -v
```

测试使用临时工作簿及本地 HTTP 服务，覆盖字段保真、来源顺序、ID 校验、多图关联、真实图片校验、失败重试与缓存恢复，无需外部图片站点。

## 新版文章表

`ref/文章信息表 2.xlsx` 的原有 13 个描述字段与脚本一致，额外的 `clustering_label` 会输出到 JSON 和 JSONL。未指定的其他表列继续忽略；旧版工作簿无需补列即可运行。

新版表当前含 184 条趋势，ID 与原表 500 条均不重合。若需独立整理并下载图片，可执行：

```bash
conda run -n 314 python backend/scripts/prepare_trend_data.py --input "ref/文章信息表 2.xlsx" --output data/trend_data/article_table_2
```

该命令会下载新表的关联图片；只检查字段对应关系请追加 `--dry-run`。

已有 JSON 补下载到公共图片目录（保留文章文字，不重新读取 Excel）：

```bash
conda run -n 314 python backend/scripts/download_trend_images.py \
  --json data/trend_data/article_table_2/trends.json \
  --images-dir data/trend_data/images
```

此时图片写入 `data/trend_data/images/<趋势ID>/`，新版 JSON 中的 `local_path` 为相对其所在目录的 `../images/<趋势ID>/...`。图片编号、顺序与原始 URL 保持原样，同时更新 JSONL 和下载报告；运行前将旧索引备份到该数据集的 `backups/<时间戳>/`。重复运行复用有效图片，下载成功后清除旧失败信息。不凭其他目录中的相似文件名猜测 URL 对应关系。
