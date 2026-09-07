# 已知问题

## 2026-09-05：一张趋势来源图片暂时无法下载

- 影响范围：趋势 `11730` 的第 34 张图片，`image_id=11730_034`，来自 `media.gucci.com` 的 `salone_KV_4000x2250.jpg`。
- 表现：图片 GET 请求持续读取超时；将单次超时从 30 秒延长至 60 秒、每轮额外重试 2 次后仍失败，另一个 HTTP 客户端也出现 HTTP/2 传输错误或超时。
- 当前处理：其余 4,080 个图片引用已全部下载。完整趋势描述和失败图片原始 URL 均保留在 `data/trend_data/trends.json`，失败项 `local_path=null`；明细见 `data/trend_data/download_report.json`。
- 后续处理：外部图源恢复后重新运行 `backend/scripts/prepare_trend_data.py`，脚本会复用有效本地图片并补下载失败项。未猜测或替换成其他图片。
