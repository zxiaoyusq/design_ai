---
name: prism-moodboard-delivery
description: 整合ID/CMF图板、真实审阅状态、原图与取景，输出内嵌图片的离线HTML和可追溯交接包。用于结果交付和工作量说明；不生成新设计图或把包装成功当算法合格。
metadata:
  version: "1.1.0-local"
---

# 图板审阅与离线交付

先读 [组合输入输出合同](../prism_skill_support/references/contracts.md) 的“交付”。接收各方向当前grouping、真实整板审阅、原图/视窗和用户反馈，不从缩略图或summary缓存重建合格状态。

分别列示语义、视觉、数量、证据、用户反馈。用户认为某8图板有效可记录为正面视觉反馈，不能反写历史native PASS；历史严格数量门未过也不抹掉真实审美反馈。未展示板不宣称用户认可。

```text
python -B -X utf8 ../prism_skill_support/scripts/render_board.py --native-group grouping.json --out board.html
```
或用board-manifest导出。工具内嵌原始图片并可逆显示ROI，不授予视觉PASS；可点击查看原图/范围/来源。校准截图不混成新候选；无原图不得伪造空白图来凑数量。

用可用浏览器实际检查所有图片加载、方向切换/弹窗、原图范围、桌面和窄屏布局；确认无需本机绝对图片路径或联网取图。Root实际看整板和取景，不能只数img标签。若交付显示增强版，同时保留原图入口与标记，增强不回灌证据。

交接包含离线HTML、原图/视窗或对应明确索引、来源/范围/哈希、必要算法版本、实际输入输出回执和未解决问题。大原始证据可分包，减少重复字节。不要带auth、密钥、个人配置、私有SQLite、后台任务或额度卡权限。

采用 [省额度选图政策](../prism_skill_support/references/budgeted-visual-selection.md) 时，交付累计原图档位、详细ROI入围、每板审阅已用/预留/剩余以及到限原因。不同原图、每次图片重复提交、真实供应商请求和tokens独立记账；本地预组不能冒充已看图，预算到限也不能冒充候选耗尽。明确区分可展示成果、待核板、未成板缺口和最终签收。

工作量按实际CLI请求/回执统计，模型调用、协议重放、图片复用、独立输入和版本迭代分开。未知usage不是0，缓存输入不重复相加，token不能冒充美元账单。给真实结论和下一接续点；未经用户要求不发送、发布或安装到他人的环境。
