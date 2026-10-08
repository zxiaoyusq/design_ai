---
name: prism-moodboard-delivery
description: 将当前情绪板、原图取景、真实审阅状态和工作量整理为图片内嵌HTML及可审计交接包。用于结果交付；不把包装完成当算法合格。
metadata:
  version: "2.0.0"
---

# 棱镜｜离线HTML与同事交接

输入当前分组、独立整板审阅、原图/视窗/展示增强记录、来源索引和实际调用账本。读取 [交付合同](../prism_skill_support/references/contracts.md) 与 [指标和评估边界](../prism_skill_support/references/evaluation-contract.md)。

展示当前板、每张为何选、原图→取景→处理的对照、离群替换及未解决问题。说明H01/原生H2是否实际跑过，分别显示视觉、数量、来源/证据和用户反馈；单板AI视觉PASS不重写此前六板原生失败。

内嵌图片字节，使用可逆ROI，保留原图入口和来源链接。relative原图引用先在当前机器核对并绑定；不得交给同事一个依赖作者D盘图片的HTML。增强展示另标，原证据可访问。

渲染入口：
```text
python -B -X utf8 ../prism_skill_support/scripts/render_board.py --manifest board.json --out board.html
```
实际CLI参数先看--help；也可--native-group接原分组。脚本只渲染和核哈希/排重，不替代视觉验收。

使用当前可用浏览器实查图片加载、原图与范围、弹窗/切换、桌面和窄屏，并亲自看整板。离线打开时图片不能依赖HTTP或作者绝对文件路径。校准截图不当新候选。

交接包含START-HERE、完整流程、每步skill及资源、安装/环境检查、版本哈希、模型设置、输入输出契约、实际案例和未完成边界。原始证据可分数据包；私人访谈、认证、SQLite、个人账号与自动化权限不随通用技能传播。

工作量区分唯一原图、方向候选位、复用、实际CLI请求、逻辑确认、程序重放、版本与问题轮次。可见token不是美元账单；没有使用量则写unknown。最后明确同事从哪一阶段接续；不自动外发、发布或安装到对方环境。
