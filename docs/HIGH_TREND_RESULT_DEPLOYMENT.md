# 通过 Git 同步最新高潜趋势结果

本次直接把已完成任务 `web_85176208a42140fd85b577116795cbba` 的展示数据加入 Git，另一台机器无需运行导入脚本、下载 Release 或重跑模型。

在目标服务器工程目录执行 `git pull --ff-only origin main`，若同时更新了前端或后端代码，按原部署方式重新构建前端并重启服务。然后打开：

```text
/high-trends?task=web_85176208a42140fd85b577116795cbba
```

也可以在高潜趋势页面刷新历史任务后选择最新任务。

## 已随 Git 提交的范围

- 任务目录 `data/result/high_trend/web_85176208a42140fd85b577116795cbba/` 中的 `web_task.json`、`state.json`、`high_potential_trends.json`、`sources.json`、`performance_report.json`、`report.md`、`image_paths.md`、`manifest.json`、`completion.json` 和 `agent_skill.md`。
- 14 个方向及底部用研图库实际引用的 1,122 个图片文件，共 400,881,613 字节：趋势图片 329 个、用研 PPT 图片 593 个、其他用研图片 200 个。方向卡片包含 410 处图片引用，底部图库包含 793 条图片记录，部分路径重复。
- 图片保留原相对目录，分布在 `data/trend_data/images`、`data/userreseach_data/ppt_images` 和 `data/userreseach_data/images`。只纳入这份结果所引用的文件，研究目录的其他数据继续被 `.gitignore` 排除。

## 路径与后续使用

结果中 `image_refs[].absolute_path` 沿用既有字段名，值统一为项目相对路径；`image_refs[].path` 和 `user_images[].path` 同样使用项目相对路径。现有后端会以当前工程根目录解析，无需在不同机器上替换用户名或安装目录。报告中的图片路径也已转换。

来源索引、输入清单仍保留运行当时的来源记录与路径，用于追溯，不作为本次结果页面的图片读取地址。归档结果的浏览不依赖原始调研 JSON；重新发起研究时仍需另行准备原始资料。页面上方创建新研究所需的数据源预估，若缺少原始资料，仍可能提示资料目录读取失败，不影响历史结果显示。

图片筛选页的两份独立图库、筛选状态和未进入结果的其他图片，仍按 `IMAGE_REVIEW_DEPLOYMENT.md` 中的 Release 恢复方式部署。本次 Git 数据用于高潜趋势正文与底部用研图库。
