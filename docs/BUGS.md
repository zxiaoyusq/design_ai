# 已知问题

## 2026-09-07：44 条用户需求缺少用户关联

- 影响范围：`transcend_model_iduserdemands` 中数据库 ID 904–947 的 44 条未删除需求，在当前 `transcend_model_a3w` 中没有关联记录，无法确定归属用户。
- 当前处理：原字段和源 ID/BID 保留在 `data/userreseach_data/users.json` 根节点的 `unlinked_demand_research`，标记 `link_status=no_active_user_relation`。不删除记录、不推测用户，也不改写数据库。
- 后续处理：由业务侧确认归属并补充源关系后重新提取。源关系中另有 18 条指向不存在用户和已删除需求的记录，已过滤并记入 `export_report.json` 的 `ignored_relation_count`。

## 2026-09-05：一张趋势来源图片暂时无法下载

- 影响范围：趋势 `11730` 的第 34 张图片，`image_id=11730_034`，来自 `media.gucci.com` 的 `salone_KV_4000x2250.jpg`。
- 表现：图片 GET 请求持续读取超时；将单次超时从 30 秒延长至 60 秒、每轮额外重试 2 次后仍失败，另一个 HTTP 客户端也出现 HTTP/2 传输错误或超时。
- 当前处理：其余 4,080 个图片引用已全部下载。完整趋势描述和失败图片原始 URL 均保留在 `data/trend_data/trends.json`，失败项 `local_path=null`；明细见 `data/trend_data/download_report.json`。
- 后续处理：外部图源恢复后重新运行 `backend/scripts/prepare_trend_data.py`，脚本会复用有效本地图片并补下载失败项。未猜测或替换成其他图片。
