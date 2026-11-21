# 用户登录与账号维护

所有业务模块、接口、图片、下载、API 文档和 `visual-workflow` 静态交付页均要求登录。访问受保护页面时会跳转 `/login`，登录后返回原页面；Vue 页面右下角显示用户名和退出入口。账号由管理员在服务器创建，没有公开注册接口。

## 首次配置

在 `backend/.env` 配置 `backend/.env.example` 中的 `AUTH_*` 项。数据库密码应随机生成，连接串中的密码与 `AUTH_POSTGRES_PASSWORD` 保持一致；这些值不提交到 Git。

本机提供独立的 PostgreSQL 账号库，监听 `127.0.0.1:55434`，使用 Docker 持久卷保存账号与会话：

```bash
docker compose -p design-ai-auth --env-file backend/.env -f deploy/auth-compose.yml up -d --wait
conda run --no-capture-output -n 314 python -m alembic -c backend/alembic.ini upgrade head
cd backend
conda run --no-capture-output -n 314 python -m app.manage_auth create-admin admin
```

创建命令会隐藏输入密码，并要求再次输入。已有用户名会报错，不会覆盖密码。自动化可使用 `--password-stdin` 从标准输入读取密码，避免把密码作为进程参数。

`site.sh` 和 `start.sh` 启动前会执行数据库迁移；账号库连接或迁移失败时，启动流程明确报错。Docker 账号库需先启动，也可把 `AUTH_DATABASE_URL` 指向已有的专用 PostgreSQL 数据库。启动探活使用只返回状态的 `/health`，API 文档继续受保护。

## 密码与会话

```bash
cd backend
conda run --no-capture-output -n 314 python -m app.manage_auth set-password admin
```

改密会撤销该账号全部登录会话。退出登录只撤销当前浏览器会话。账号、密码摘要和会话均保存在 PostgreSQL，正常重启服务不会重置账号或丢失有效登录。

密码使用带独立随机盐的 PBKDF2-SHA256 摘要，当前迭代 600,000 次。连续五次密码错误后，账号暂停登录一分钟，错误提示不区分账号不存在、密码不正确或账号禁用。

登录令牌是随机值，通过 `HttpOnly; SameSite=Lax; Path=/` Cookie 发送，数据库只保存令牌 SHA-256 摘要。会话默认 12 小时，可通过 `AUTH_SESSION_SECONDS` 调整；过期会话在下次成功登录时清理。HTTPS 请求自动设置 `Secure`，TLS 终止代理未透传协议时也接受经来源校验的 HTTPS Origin；纯 HTTPS 部署可用 `AUTH_COOKIE_SECURE=true` 强制启用。令牌不写入 localStorage 或前端状态。

Cookie 认证的写请求会校验浏览器 Origin 和跨站请求标记。Vite 与 Nginx 保留原始站点 Host，常规同源访问直接可用；额外可信前端域名可通过逗号分隔的 `AUTH_ALLOWED_ORIGINS` 配置。

## 部署与校验

推荐继续使用 `./site.sh start`，默认以 preview 提供已构建资源，首次启动或前端更新后先执行 `pnpm --dir frontend build`。该模式不启用 HMR 或依赖优化重载。构建产物服务与显式开启的开发服务均在提供文件之前调用 `/api/v1/auth/me` 验证会话，覆盖历史构建、图片及静态交付；开发模式还保护源码与 HMR 连接。备用 Nginx 配置使用 `auth_request` 做相同检查。登录页是后端提供的独立 HTML，不依赖受保护的 JS、CSS 或图片，避免登录循环。

后端故障时静态服务拒绝提供文件。已登录资料响应设置 `no-store`，不允许作为公共内容缓存。不要把 `frontend/dist` 或 `frontend/public` 另外挂到未经登录保护的 HTTP 静态服务。

接口约定：

| 接口 | 用途 |
| --- | --- |
| `GET /login` | 独立登录页，支持安全的本站 `next` 路径 |
| `POST /api/v1/auth/login` | JSON 请求体为 `username`、`password`；成功时设置会话 Cookie |
| `GET /api/v1/auth/me` | 返回 `username`、`role`，未登录返回 401 |
| `POST /api/v1/auth/logout` | 撤销当前会话并清除 Cookie |
| `GET /health` | 公开进程探活，只返回 `{"status":"ok"}` |

离线验证命令：

```bash
cd backend
conda run --no-capture-output -n 314 python -m pytest -q tests/test_auth.py tests/test_site_script.py
```

登录测试使用临时数据库；业务测试通过独立应用实例替换身份依赖，不修改生产登录策略，不访问真实账号库。
