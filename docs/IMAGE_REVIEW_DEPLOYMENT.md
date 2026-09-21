# 图片筛选界面部署

功能代码随 Git 仓库发布；图片和来源索引放在仓库 `image-review-20260921` 版本附件中，避免把约 2.12 GB 图片及不断变化的选择状态写进 Git 历史。

## 在另一台服务器恢复

服务器需具备 Python 3.14、Node.js 22.13 或以上版本及 pnpm 11.19。当前 pnpm 不支持 Node.js 20。

在项目根目录执行，使用项目的 Python 3.14 环境：

```bash
git pull --ff-only origin main
conda run -n 314 python -m pip install -r backend/requirements.txt
conda run --no-capture-output -n 314 python backend/scripts/image_review_bundle.py restore
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
```

如果附件加密，恢复命令会提示输入单独交付的密码，服务器需要安装 OpenSSL。不要将密码写入 Git、命令行参数或公共文档。公开附件则无需密码。

下载可重试，已经通过 SHA-256 校验的分卷会复用。下载缓存位于 `.runtime/image-review-bundles/image-review-20260921`。解包完成前需要约 5 GB 空闲空间（压缩分卷、图片和临时解密文件）。已存在同名任务时脚本拒绝覆盖，避免覆盖服务器上的人工选择。使用原有方式重启站点，例如由 systemd 托管时重启 `design-ai-site.service`；直接运行时使用 `./site.sh restart`。

打开以下地址（替换为实际服务器域名）：

```text
https://你的域名/high-trends/image-review?task=web_85176208a42140fd85b577116795cbba&collection=result
https://你的域名/high-trends/image-review?task=web_85176208a42140fd85b577116795cbba&collection=remaining
```

前端反向代理应将 `/api` 转发到 FastAPI，并对页面路径使用 SPA 回退；现有 `site.sh` 的 Vite 代理已支持。图库功能沿用单后端进程部署。需要允许服务账号写入 `data/result/high_trend`，用于保存选择、生成缩略图和导出 ZIP。图库查看与筛选不会调用大模型，也不需要重新连接用户调研数据库。

## 数据范围与迁移边界

- 结果图片：396 张；其他图片：6,592 张，已经排除任一用户 DISLIKE 的 1,235 张图片。打包时的选择版本和保留数见 `deploy/image-review/manifest.json`。
- 包含当前两份图库的可选原图副本、来源、指纹、原选择状态、选择历史，以及对应任务的已完成结果资料。图片按 `copy_path` 从部署目录读取；原始电脑路径作为历史来源信息保留。
- 不包含环境密钥、原始数据库、其他任务、缩略图、旧导出、被 DISLIKE 过滤的图片文件。负向图片的来源和指纹仍在索引中，便于后续去重比对。
- 本包用于独立图片筛选页。研究原始资料目录不随包迁移；要重新生成趋势或浏览高潜趋势正文中的原始图片接口，需要另行迁移原始资料。选图页的查看、保留、排除、筛选及导出不受影响。
- 服务器上的后续选择不会自动同步回本机或 GitHub。请定期备份两份图库的 `review.json`，或下载页面的保留图片 ZIP 与来源清单。

## 离线恢复与重新打包

如果服务器无法连接 GitHub，把版本附件下载到服务器同一目录，再执行：

```bash
conda run --no-capture-output -n 314 python backend/scripts/image_review_bundle.py restore --bundle-dir /path/to/assets --local-only
```

重新打包时使用新的版本号及空输出目录，不要覆盖已发布版本：

```bash
conda run --no-capture-output -n 314 python backend/scripts/image_review_bundle.py pack \
  --task web_85176208a42140fd85b577116795cbba \
  --tag image-review-YYYYMMDD-v2 --bundle-dir .runtime/new-image-review-assets --encrypt
```

更新受 Git 管理的部署清单并上传同名版本附件。分卷与每个解包文件均校验哈希，只允许清单声明的普通文件，拒绝路径穿越、链接与重复文件；完整校验后才落盘。
