# 趋势调研数据整理

## 在趋势洞察中导入增量文章

打开 **趋势洞察 → 文章资料 → 导入 Excel**。选择文章导出表，点击「预览增量」查看待新增、重复、异常行和文章示例，选好主题地区分析模型后点击「导入并分析」。入库后可立即浏览文章。系统在后台逐批分析本次新增文章，结果可在列表、详情和「主题地区」筛选项中查看。

支持与本次导出一致的 `.xlsx`，单个文件最大 32 MB、最多 50,000 行。优先读取「导出结果」工作表，其余文件读取活动表。首行需要 `id` 和 `title_zh` 或 `title`。可选字段包括 `summary_zh`、`release_time`、`detail_url`、`source_url`、`primary_category` 和 `image_url`。空行略过，缺 ID、标题或填写无效日期的文章会列为异常。留空日期仍可入库。

去重依据为文章 ID 和原文链接，覆盖现有库与当前表内的重复。每次确认只写入新增行。预览后如果同批文章已由其他操作导入，重新预览即可看到当前范围。图片支持单竖线和双竖线分隔，原站链接用于浏览，能否显示取决于原站访问条件。历史文章和历史趋势结果继续使用已有本地图片索引。

本次 11 月 18 日导出表共 9,128 篇，新增 **295 篇**、跳过 8,833 篇重复、异常 0 行，新增文章有 644 个配图链接，最新文章发布日期为 2026-11-16。首批增量随仓库保存在 `ref/trend_article_imports/2026-11-18.json`。之后在网页确认的批次保存在运行目录 `data/trend_data/article_imports/`，迁移时与应用数据一起复制。每批保留来源文件名、工作表、文件 SHA-256、原表行号和入库时间。

接口使用 multipart 表单。向 `POST /api/v1/article-trends/imports/preview` 提交 `file` 获取预览。确认时向 `POST /api/v1/article-trends/imports` 提交同一 `file`、预览返回的 `selection_digest`、选定的 `region_model_id`。兼容只需要整理与写入文章的调用方，省略模型字段即可只导入。预览只整理表格与查重，模型分析从用户明确确认后开始。

### 主题地区

- 每篇读取标题和摘要，结合项目发生地、主题的文化来源与目标市场，最多保存 3 个地区标签并按相关性排序。支持国家和区域，例如印度、美国、拉美与中亚。详情可查看所选标签的原文依据、模型和日期。
- 仅有网站来源或文章未提供足够地域依据时，显示「无明确地区」。尚未取得有效模型结果的文章显示「待分析」。地区字段用来浏览和筛选，聚类文本仍使用原来的标题与摘要。
- 导入弹窗使用服务端模型目录，实际可调用范围取决于部署环境的 `LLM_KEY`、`LLM_URL` 与授权。后台通过 DeepAgents 每批最多处理 20 篇。失败或中断后可在文章资料页点击「继续分析」，已校验的结果可直接复用。再次上传同一份表仍按新增范围计算。
- 首批 295 篇使用本次 Codex 会话的 6.2 Sol 分析。190 篇有明确地区，其中 39 篇有多标签，覆盖 36 种国家或区域。105 篇分析完成且无明确地区。结果在 `ref/trend_article_regions/2026-11-18.json`，以文章 ID 和实际输入文字 SHA 关联原记录。
- 旧库 8,833 篇的分析结果在 `ref/trend_article_regions/2026-11-21-baseline-8833.json`，与首批增量结果一起加载，并保留每篇的模型、Prompt 版本、输入文字 SHA、分析时间和原文引句。
- 网页分析结果保存在 `data/trend_data/article_regions/`。迁移时与文章导入批次目录一起复制。进度可从 `GET /api/v1/article-trends/region-jobs/latest` 或 `GET /api/v1/article-trends/region-jobs/{id}` 查询。

## 旧资料的离线整理和图片下载

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

## 趋势信息 0930 全量图片

`ref/趋势信息0930.xlsx` 使用独立脚本 `backend/scripts/download_trend_excel_images.py`。它只读取文章 `id`、标题及 `image_url`，按完整 URL 去重后创建一个下载任务，再把结果关联回每篇文章的全部原始图片位置；网络瞬时错误按 `--retries` 限次重试。不解析图片以外字段，也不调用模型。

```bash
conda run -n 314 python -B backend/scripts/download_trend_excel_images.py --dry-run
conda run -n 314 python -B backend/scripts/download_trend_excel_images.py
```

图片仍存于共享 `data/trend_data/images/<文章ID>/`，新索引在 `data/trend_data/trend_info_0930/`。旧索引链接先按 URL 查找并校验 SHA-256 与可解码性；下载器还会复用共享目录中相同 ID、序号和 URL 哈希且通过图片校验的文件。每 100 个新 URL 写一次 `download-checkpoint.jsonl` 和进度；中断后用 `--resume` 续跑。`--retry-transient-failures` 仅与 `--resume` 一起使用，会重试超时、连接故障和 408/429/5xx，不重试明确的 404 或超大小限制。

本轮 8,833 篇文章共 45,531 个图片引用、44,825 个去重 URL。复用旧索引 3,194 个 URL、复用共享图片目录中另 329 个有效文件；最终 44,800 个唯一 URL 成功，25 个失败，45,506 个文章图片引用具有本地文件。详情及错误原因见 `data/trend_data/trend_info_0930/download_report.json`，中断/完成状态见 `completion.json`。
