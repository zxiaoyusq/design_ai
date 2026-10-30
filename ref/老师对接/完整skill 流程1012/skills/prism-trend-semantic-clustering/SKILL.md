---
name: prism-trend-semantic-clustering
description: 从趋势图文库的文字归纳可供设计选向的语义簇并按受支持主成员规模排名。用于一级趋势聚类；不把图片像素或旧DNA作为入簇门槛。
metadata:
  version: "4.3.0"
---

# 棱镜｜趋势纯语义聚类

输入文章目录与文字，输出 trend-clusters.json、text-catalogue.json、ranking.json、coverage.json。先读 [趋势文字合同](../prism_skill_support/references/contracts.md)。JSON/JSONL/CSV的具体导入格式由随包 trend_text.py --help 查看。

每条保留article_id、标题、全文或摘要、text_kind、来源、日期、原类别和图片关联旁表。若只有模型摘要，标source_paraphrase；不能升级为已读网页原文。图片旁表只用于后续追溯，不在本步分析像素。

模型按设计语义归纳，逐篇给主归属、原文锚点、理由、边界；多义关联与主归属分开，未知/不支持另留覆盖去向。独立语义审阅后只以受支持的主成员计算库内规模；排名不是市场热度、增长率、商业潜力或受欢迎程度。

粒度应能容纳多个独立项目及多种视觉实现。一个簇若只剩一篇四张图，要检查是否把一个具体纹样/物件错当一级趋势；不能等设计师选后无限回库补救，也不能把不相干材料合并凑容量。语义完整性仍先于数量。

先编译整个目录，再让H01从完整候选空间选择；代表例句不是整个可用素材池。不局限于已解析图或上一轮六个方向。可以分批归纳后作全局同义合并和边界复核，分批之间保持稳定文章身份。

工具仅冻结/编译，不替你判断语义：
```text
python -B -X utf8 ../prism_skill_support/scripts/trend_text.py --help
```
将完整接口文件交 `$prism-h01-semantic-handshake`。召回不足、原文缺失、未归类比例必须在方向选择前可见。

编写提案和独立复核前，读取 [字段格式及命令](../prism_skill_support/references/trend-proposal-format.md)。themes、assignments和reviews的具体字段已列明，无需读源码猜格式；示例不是实际判断。

## 4.3风格层交接

上游语义方法与原脚本保持原版本。把原文/完整话语、受访者与对象、正负/条件、趋势父簇、来源类型和未知传至下游；新图片不能改写原语义。用研与趋势提供探索依据，不凭语义推断具体材质/外观偏好。当前后续依[4.3总合同](../prism_skill_support/references/contracts.md)做视觉与解析联合风格判断。
