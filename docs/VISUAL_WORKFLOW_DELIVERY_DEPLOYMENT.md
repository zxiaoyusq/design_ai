# 域名启停入口更新（2026-10-21）

现在推荐在根目录执行 `./site.sh start|stop|restart|status` 管理前后端。启动会按用户授权自动停止占用配置端口的进程、容器或系统服务；默认接管 80／8000，包括旧的 `design-ai-static-site` 容器，退出后不会自动恢复该容器。Vite 继续提供 `frontend/public/visual-workflow/` 的既有交付文件，HTTPS 仍由原负载均衡处理。完整命令与接管边界见 [根目录 README](../README.md)。

下文各日期的 Nginx 容器运行状态是历史记录；Docker 静态方案仍可备用，但不应与 `site.sh` 同时占用 80 端口。

# 三处来源的情绪板汇总与逐图标注（2026-10-12）

访问地址：<https://gamedevcenter.ahagamecenter.com/visual-workflow/moodboard-image-review-20261012/index.html>。

汇总老师PPT五页、`dna-cluster-sample1600-reference-20261010/index.html` 按实际显示顺序的前四板和 `dna-cluster-sample1600-bounded-three-20261012/index.html` 三板，共12板／82个图片位置。点击图片切换不通过，放大按钮查看完整原图；同图不同板分别标注。记录保存于当前浏览器localStorage，可导出JSON，换浏览器可导入同一集合记录；不是服务端共享标注。可选原因在原图弹窗内输入，导入替换／清空需用户确认。

生成全新的发布目录（目标目录须不存在）：

```bash
/root/miniconda3/envs/314/bin/python backend/scripts/publish_moodboard_review_collection.py \
  --ppt 'ref/老师对接/情绪板_5版_可编辑复建.pptx' \
  --output frontend/public/visual-workflow/moodboard-image-review-20261012
cp -a frontend/public/visual-workflow/moodboard-image-review-20261012 \
  frontend/dist/visual-workflow/
```

模板位于 `deploy/moodboard-review/`。PPT图片按原字节提取并沿用原裁切与绝对位置，网页图片沿用实际展示裁片／视窗；发布仅包含所选图板，不复制1600样本整库。`deployment-manifest.json` 保存来源文件／URL、源SHA、逐板图数、81份不同图片资源及文件SHA。现有Nginx挂载立即提供新路径，无需重启或新模型调用。PPT原构图在窄屏板内横向滑动。

## 同页相对匹配排名（2026-10-12）

当前网页已按现行图片聚类/整板判断与四张参考板的通用成版原则，从高到低排列。原顺序对应的新次序为 **5、1、4、2、3、9、11、12、8、7、10、6**；每板显示名次、比较理由和原来源编号，来源筛选保留全局名次。排名不是全板通过或人工批准，旧素材、取景、历史状态和已有浏览器反馈身份不变，Skill未改。

需要重复生成同一排名时，在上述发布命令追加：

```bash
--ranking deploy/moodboard-review/ranking-20261012.json
```

输出目录仍须是不存在的新目录，先生成、核对集合身份及全部成员/ROI与原集合一致，再发布。当前排名绑定集合 `0a822b67c1365becfc3b20d19e45749e01839a6084c9442470b5237c604b3f3c`；来源变化不得直接复用。模板无排名仍保持原顺序，非法排名会拒绝生成；浏览器收到不完整或身份不符的排名时回退原顺序，不丢标注。

本次先在 `.runtime/moodboard-ranking-20261012/release/` 生成校验，再仅复制本页HTML/JS/CSS、`ranking.json` 和发布清单到public/dist；81份原图资源未重压缩或替换。修改前文件与12板实际截图留在同runtime目录，桌面/手机本地及实际域名测试均通过。发布无需重新构建全站、服务重启、DNA提取或聚类。

# 统一设计情绪优先结果预览（2026-10-11）

访问地址：<https://gamedevcenter.ahagamecenter.com/visual-workflow/dna-cluster-sample1600-priority-three-20261011/start-here.html>。

源目录为 `data/result/dna_cluster_moodboard/sample1600_full_rebuild_20261011/delivery-priority-three-preview/`。整个目录逐字节发布至public／dist，包含start-here总览、index、3个图板页面、17张原图和下载记录。保留1个7图候选与2个5图小组的原状态和说明；反馈继续由浏览器保存／导出。

首次复制命令（目标目录须不存在）：

```bash
cp -a data/result/dna_cluster_moodboard/sample1600_full_rebuild_20261011/delivery-priority-three-preview \
  frontend/public/visual-workflow/dna-cluster-sample1600-priority-three-20261011
cp -a frontend/public/visual-workflow/dna-cluster-sample1600-priority-three-20261011 \
  frontend/dist/visual-workflow/
```

现有 `design-ai-static-site` 仍提供域名静态服务，无需重启；本机5174容器保持停止。HTTPS证书已更新，2026-10-11正常证书校验请求返回200，实际证书有效期至2027-03-24 23:59:59 GMT。下面的到期／等待复测描述为历史排查记录。

# 历史状态：恢复域名服务复测（2026-10-10）

按用户要求，`design-ai-local-site` 已停止（5174无监听），`design-ai-static-site` 已启动（80监听）。服务器侧HTTP首页、两个交付页面和API均200，图板正文标题匹配；HTTPS证书仍过期，之前用户侧备案拦截是否解除尚未确认。HTTP复测入口：

- <http://gamedevcenter.ahagamecenter.com/visual-workflow/dna-cluster-sample500-20261009/index.html>
- <http://gamedevcenter.ahagamecenter.com/visual-workflow/sol61-high-20261007-count8/index.html>

这次恢复使用 `docker compose -p design-ai-static -f deploy/visual-static-compose.yml up -d`，先执行 `./local-site.sh stop`；原图、发布页面及后端进程均沿用。

# 历史访问方式：服务器回环站点与SSH端口转发（2026-10-09，现已停止）

域名对应的 `design-ai-static-site` 容器已停止，80端口不再由本工程监听。当前 `design-ai-local-site` 容器仅监听服务器 `127.0.0.1:5174`，复用现有dist交付目录与 `127.0.0.1:8000` 的Design AI后端；配置为 `deploy/visual-local-compose.yml` 和 `deploy/visual-local.nginx.conf`。

服务器5173已经被Bubble AI开发服务占用，因此保留该进程，本工程使用5174；用户电脑的访问端口仍是5173。在用户自己的电脑执行并保持SSH进程运行：

```bash
ssh -p 22 -N -o ExitOnForwardFailure=yes \
  -L 5173:127.0.0.1:5174 root@106.15.43.230
```

随后访问：

- 50图快速试跑（复用＋必要补查，未做模型板审）：<http://127.0.0.1:5173/visual-workflow/dna-cluster-sample50-v5-20261010/index.html>
- 500图设计情绪版：<http://127.0.0.1:5173/visual-workflow/dna-cluster-sample500-design-emotion-20261009/index.html>
- 500图聚类页面：<http://127.0.0.1:5173/visual-workflow/dna-cluster-sample500-20261009/index.html>
- 七方向／作者切换页面：<http://127.0.0.1:5173/visual-workflow/sol61-high-20261007-count8/index.html>
- 工程首页：<http://127.0.0.1:5173/>

根目录 `./local-site.sh start|stop|restart|status` 管理本机静态容器；容器自动重启策略为unless-stopped，API沿用既有后端进程。关闭客户端SSH即可结束当前端口转发，不会停止服务器的本机站点。若今后恢复域名服务，需明确选择公网部署并先解决下述备案和证书问题。

50图快速试跑源为 `data/result/dna_cluster_moodboard/sample50_reuse_v5_20261010/preview/`，独立发布副本不覆盖旧500图。展示3张未审阅候选和18个小组，以及全部50图的实际处理状态；缺少模型板审不能解读为视觉通过。原图保持原始字节，页面筛选／取景放大／反馈导出正常；仅访问静态页面不会触发模型。完整补查与冻结记录留在源运行目录，页面只带交付数据和图片。

# 500 图 DNA 聚类情绪板独立页面（2026-10-09）

可访问地址：<http://gamedevcenter.ahagamecenter.com/visual-workflow/dna-cluster-sample500-20261009/index.html>。

源目录为 `data/result/dna_cluster_moodboard/sample500_20261009/delivery/`，逐字节复制到同名发布目录，保留当前46张图板、245份原图、500图记录下载、历史页及浏览器反馈功能。已有 `delivery-manifest.json` 继续记录图板与原图SHA；只复制交付目录，不公开父级运行目录。

首次部署命令（目标目录须不存在）：

```bash
cp -a data/result/dna_cluster_moodboard/sample500_20261009/delivery \
  frontend/public/visual-workflow/dna-cluster-sample500-20261009
cp -a frontend/public/visual-workflow/dna-cluster-sample500-20261009 \
  frontend/dist/visual-workflow/
```

现有Nginx静态站点立即提供该路径，后续前端构建继续从public复制。反馈仅写入访问者浏览器，并可由页面导出，不修改本机审阅记录。

当前域名的阿里云ALB HTTPS证书已于北京时间2026-10-09 07:59:59到期（证书 `notAfter=2026-10-08 23:59:59 GMT`）。HTTP正常；HTTPS证书需在现有负载均衡续期后才能恢复可信访问。没有绕过浏览器证书校验作为交付方案。

# 七方向8图交付页（2026-10-08）

访问地址：<https://gamedevcenter.ahagamecenter.com/visual-workflow/sol61-high-20261007-count8/index.html>。

入口顶部支持点击 `guojianfei` 与 `zhangxiaoyu` 切换页面，默认选中 `zhangxiaoyu`。老师页是 `ref/老师对接/最新完整流程1006/棱镜工作流_v2-project/cases/linear-relief/实际试板与取景.html` 的发布副本；原七方向主页保存在同目录 `zhangxiaoyu.html`，图片放大、筛选和板页链接均沿用。两个子页面首次选中时加载，再次切换保留滚动及筛选状态；作者锚点支持刷新和分享，顶部“单独打开”可打开当前页。

首次生成七方向发布目录后，或更新现有作者切换页时，执行：

```bash
/root/miniconda3/envs/314/bin/python backend/scripts/publish_visual_comparison.py \
  'ref/老师对接/最新完整流程1006/棱镜工作流_v2-project/cases/linear-relief/实际试板与取景.html' \
  frontend/public/visual-workflow/sol61-high-20261007-count8
```

老师的30处内嵌图片按原字节SHA去重为10个 `guojianfei-assets/` 文件，页面仅替换图片地址，取景样式与原文保持原样。`comparison-manifest.json` 记录两个来源及发布副本哈希；当前 `deployment-manifest.json` 的公开文件列表包含切换入口和新增资源。同步新增子页及资源到dist后最后替换index即可生效，无需重启Nginx；后续前端构建会自动从public复制。

源目录为 `data/result/visual_completion/sol61_high_20261007/count8/delivery-final/`。该页保留7方向、每板8张／8独立项目、6方向通过及H01-03未通过的真实结果。发布副本将原图与预览图按SHA256去重外置；8个页面及56张唯一图片资源无需模型调用。首页图片外置后约6 KB；新增主页逐图弹窗后约48 KB（仅包含必要图片索引及交互），7张板页合计约61 KB，原图不压缩、不重绘。

`zhangxiaoyu` 主页已改为逐张完整原图展示：每个方向占一行，桌面每行4张、900px及以下每行2张，更大图片框使用 `object-fit:contain`，不会裁掉照片边缘。点击后可放大原图，并使用上一张／下一张或左右方向键翻图，Esc、关闭按钮、点击遮罩关闭；取景和审阅结论仍在图板页保留。照片按浏览位置懒加载。交互由 `backend/scripts/visual_completion_home_viewer.py` 在发布时注入。

更新已有作者子页可执行以下命令，再同步 `zhangxiaoyu.html`、`comparison-manifest.json` 与 `deployment-manifest.json` 到相应dist目录：

```bash
/root/miniconda3/envs/314/bin/python backend/scripts/visual_completion_home_viewer.py \
  frontend/public/visual-workflow/sol61-high-20261007-count8/zhangxiaoyu.html
```

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
