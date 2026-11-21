# AI 审美洞察平台

## 域名一键启停（推荐入口）

访问地址：[https://gamedevcenter.ahagamecenter.com/](https://gamedevcenter.ahagamecenter.com/)。

平台现需用户名和密码登录，页面、业务接口、图片下载与静态交付均受保护。账号库初始化、创建管理员、修改密码和会话配置见 [登录与账号维护](docs/AUTHENTICATION.md)。首次启动前需配置并启动 PostgreSQL 账号库；正常重启保留账号和有效会话。

使用根目录 `site.sh` 同时管理前后端：前端默认提供 `frontend/dist/` 的固定构建产物，监听 `0.0.0.0:80`；Python 后端监听 `127.0.0.1:8000`，`/api/` 由前端代理。域名 HTTPS 由现有负载均衡处理。默认不启动开发态 HMR，也不会因依赖优化或源码变化让浏览中的页面自动重载。

为兼容切换前缓存的主页与旧标签页，Vite 同时提供现有 `frontend/dist/assets/` 下的旧构建资源；切换部署方式时不要删除此目录。资源缺失返回 404，不再用主页 HTML 冒充 JavaScript／CSS。若浏览器仍显示旧页面，可按 `Ctrl+Shift+R` 强制刷新。

应用入口包含独立加载提示。资源加载失败时显示“页面加载失败”和手动重载按钮，保留当前页面，不自动刷新或清空浏览器保存的用户数据。

在服务器执行：

```bash
cd /root/dev/work/design_ai

# 首次部署或前端代码更新后先构建；正常重启可复用已有构建。
conda run --no-capture-output -n 314 pnpm --dir frontend build

./site.sh start     # 自动处理端口占用，再启动前后端；前台运行
./site.sh stop      # 在另一个终端停止本脚本管理的前后端
./site.sh restart   # 停止旧实例，等待清理完成后重新前台启动
./site.sh status    # 查看本脚本管理的前后端状态
```

`start` / `restart` 的行为：

- 先检查运行依赖，再接管配置的两个 TCP 端口（默认 80、8000）。原占用者即使属于其他项目也会被停止，请注意影响范围。
- Docker 占用时停止对应容器（包括本工程旧的 `design-ai-static-site`），系统服务占用时停止对应服务，避免只杀 worker 后被自动拉起；普通监听进程先正常终止，超时后再次核对进程身份并强制终止。
- 只处理目标端口，不停止整个 Docker 守护进程、SSH 基础服务或无关端口。权限不足、无法确认归属或仍被外部管理器反复拉起时，会明确报错，不盲目扩大停止范围。
- 重复 `start` 若已有实例运行或启动中，会提示无需重复启动，不误停现有实例。
- `Ctrl+C` 或 `stop` 会清理本脚本创建的前后端进程组，避免遗留 Vite 子进程；不会自动恢复先前因端口冲突而停止的服务，也不删除发布页面或数据库。

运行前需准备 conda `314` 环境、后端依赖、`backend/.env`、已启动的 PostgreSQL 账号库、前端 `pnpm` 依赖与构建产物，以及 `lsof`、`flock`、`setsid`、`curl`。启动脚本先执行账号数据库迁移。默认监听 80 端口需要 root 权限；停止容器或系统服务也需要相应权限。

可通过 `DESIGN_AI_DOMAIN`、`DESIGN_AI_FRONTEND_PORT`、`DESIGN_AI_BACKEND_PORT` 覆盖域名和端口；前后端端口必须不同且处于 1–65535。域名解析及负载均衡回源端口仍需与实际配置一致。

`site.sh` 和 `start.sh` 的 `DESIGN_AI_FRONTEND_MODE` 默认均为 `preview`，提供固定构建资源。只有需要源码热更新的开发调试才显式设置 `DESIGN_AI_FRONTEND_MODE=dev`；该模式会启用 Vite 的开发态重载行为。

日志查看（`Ctrl+C` 仅退出日志查看）：

```bash
tail -n 100 -f .runtime/logs/frontend.log .runtime/logs/backend.log
```

## 备用：Docker Nginx 静态部署

如只需要 `frontend/dist/` 中的构建产物和静态交付页，也可使用旧的静态容器方式。先执行 `./site.sh stop`，再启动容器，避免同时争用 80 端口：

```bash
docker compose -p design-ai-static -f deploy/visual-static-compose.yml up -d
docker compose -p design-ai-static -f deploy/visual-static-compose.yml stop
docker compose -p design-ai-static -f deploy/visual-static-compose.yml restart
docker compose -p design-ai-static -f deploy/visual-static-compose.yml ps -a
docker compose -p design-ai-static -f deploy/visual-static-compose.yml logs --tail 100 -f
```

此方式要求 `frontend/dist/index.html` 已存在，只管理静态 Nginx，不管理后端或数据库；API 仍依赖另行启动的 `127.0.0.1:8000` 后端。`./site.sh status` 不代表该容器状态；改回 `./site.sh start` 时会自动停止占用端口的该容器。

各交付页面的发布说明见 [部署文档](docs/VISUAL_WORKFLOW_DELIVERY_DEPLOYMENT.md)。
