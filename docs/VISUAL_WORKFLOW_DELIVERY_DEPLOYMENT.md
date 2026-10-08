# 七方向8图交付页（2026-10-08）

访问地址：<https://gamedevcenter.ahagamecenter.com/visual-workflow/sol61-high-20261007-count8/index.html>。

源目录为 `data/result/visual_completion/sol61_high_20261007/count8/delivery-final/`。该页保留7方向、每板8张／8独立项目、6方向通过及H01-03未通过的真实结果。发布副本将原图与预览图按SHA256去重外置；8个页面及56张唯一图片资源无需模型调用。首页图片外置后约6 KB；新增主页逐图弹窗后约48 KB（仅包含必要图片索引及交互），7张板页合计约61 KB，原图不压缩、不重绘。

主页可点击预览中任意一格查看对应原图，并使用上一张／下一张或左右方向键翻图，Esc、关闭按钮、点击遮罩关闭；无需进入单独图板页。交互由 `backend/scripts/visual_completion_home_viewer.py` 在发布时注入。

生成发布副本：

```bash
/root/miniconda3/envs/314/bin/python backend/scripts/publish_visual_completion.py \
  data/result/visual_completion/sol61_high_20261007/count8/delivery-final \
  frontend/public/visual-workflow/sol61-high-20261007-count8
```

输出目录须不存在，避免覆盖已发布版本。同步这个生成目录至 `frontend/dist/visual-workflow/`；后续正常前端构建也会自动从public复制。仅公开页面、图片、脱除本机路径的结果／来源清单及简明报告；原始访谈、模型调用状态、原生审计文件和SQLite不在公开目录内。完整本机审计继续保存在源交付与其父目录。

现有域名的80端口Vite服务已停止，独立Nginx静态容器接管80端口回源，HTTPS由既有负载均衡终止。它同时提供已有dist前端和代理至当前Design AI后端127.0.0.1:8000，保留其他项目81端口服务。无需重启后端或运行模型。

```bash
docker compose -p design-ai-static -f deploy/visual-static-compose.yml up -d
docker compose -p design-ai-static -f deploy/visual-static-compose.yml ps
```

服务名 `design-ai-static-site`，Docker自动重启策略unless-stopped，目录只读挂载；配置见 `deploy/visual-static.nginx.conf`。停止时使用上述Compose配置执行 `down`，只移除此静态容器。不要同时启动旧 `design-ai-site.service`，两者争用80端口。

---

# 13 个高潜方向交付页部署

访问地址：<https://gamedevcenter.ahagamecenter.com/visual-workflow/h01_all13_20261005/index.html>。

页面由现有站点的 Vite 静态目录提供，无需独立端口或新增后端接口。原始离线交付页保持封存，网页发布版仅将内嵌图片改成同目录的图片地址，继续按方向加载原图；原图字节、取景范围、13 个方向的结果和审阅记录保持不变。

在工程根目录执行以下命令可重新发布：

```bash
/root/miniconda3/envs/314/bin/python backend/scripts/publish_visual_delivery.py \
  data/result/visual_workflow/h01_all13_20261005/delivery/index.html \
  frontend/public/visual-workflow/h01_all13_20261005
```

发布前校验全部内嵌原图 SHA256，写入 57 张原图后最后更新 `index.html`，并生成 `deployment-manifest.json` 记录源页面和发布页哈希。页面从约 81 MiB 减至约 1.45 MiB，图片由当前方向按需读取，未压缩或重绘。

生成目录不纳入 Git。迁移服务器时需同步原始交付页并重新执行发布命令，或同步整个生成目录。执行前端 `pnpm build` 时，Vite 会将 public 中的生成目录一并复制至 dist。

页面的“有用/待调整”等人工反馈仍保存在当前浏览器的 localStorage，可通过页面按钮导出；这些反馈不会自动写入服务端或修改原始模型结果。

## 扩大全库召回的进度入口

新版运行目录为 `data/result/visual_workflow/h01_all13_20261005_expanded/`。当前初轮页面带运行中提示，进度页为 <https://gamedevcenter.ahagamecenter.com/visual-workflow/h01_all13_20261005/progress.html>；旧离线页及其中的成板判断保持封存。

重新发布初轮页时追加 `--status-url progress.html` 可保留进度入口。只读刷新进度可执行：

```bash
/root/miniconda3/envs/314/bin/python \
  data/result/visual_workflow/h01_all13_20261005_expanded/preparation/refresh_expansion_web.py
```

该命令只编译已存在的真实回执和逐图覆盖台账，不发送模型请求。模型运行时可加 `--watch`，每 45 秒刷新一次网页快照；网页浏览及刷新也不触发付费调用。

本轮当前图板位于 <https://gamedevcenter.ahagamecenter.com/visual-workflow/h01_all13_20261005_expanded/index.html>，进度页提供入口。当前图板保留真实模型状态，并明确标记最终审阅尚未完成；不替换初轮封存页。

已启动 `preparation/continue_expansion.py` 阶段续跑器：等待 308 批原语义执行器全部终态，再串行执行仅失败图片的一次结构补查、原图候选扩展与整板审阅。续跑器与视觉执行器均使用独占锁，模型池上限为 5；缺项、进程中断和未知结果不会被隐式重新发送。阶段在 `continuation-status.json` 可查，错误会保存现场并停止，模型阶段结束仍保留最终审阅和未决处理，不伪造签收。

单独发布已有本轮图板而不请求模型：

```bash
/root/miniconda3/envs/314/bin/python \
  data/result/visual_workflow/h01_all13_20261005_expanded/preparation/continue_expansion.py \
  --publish-snapshot
```
