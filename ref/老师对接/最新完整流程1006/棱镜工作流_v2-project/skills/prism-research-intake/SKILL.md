---
name: prism-research-intake
description: 从用研报告提取原话、角色、对象和图片出现关系，建立可回查的来源。用于原始材料整理；不从同页图片猜偏好。
metadata:
  version: "2.0.0"
---

# 棱镜｜用研证据入库

输入原报告及人物对应关系，输出可复查 raw-evidence、媒体出现表、来源哈希、reviewed研究输入。先读 [用研原始材料合同](../prism_skill_support/references/contracts.md)。

保留匿名person_id、source_id、页码/shape位置、原文全文、源文件SHA和图片字节。相同图片在不同人物报告出现时，字节去重不删除人物关系。PPT整理不是逐字访谈，摘要不是原话。

实际查看原页，分别标注模板问题、选项、被访者回答、品牌印象、个人愿望、举例和分析者笔记。不能把附近图片、报告作者判断或品牌印象转成“这个人喜欢该图所有属性”。否定、转折、程度和对象完整保留。

PPTX辅助器只提取文字、媒体和裁剪/旋转元数据：
```text
python -B -X utf8 ../prism_skill_support/scripts/intake_pptx.py --config intake.json --out intake-run
```
PDF/其他格式用当前可用文档工具，核对原页布局。无渲染能力时保留缺口，不将未核对草稿转为reviewed。新报告不能套旧五人的页码表。

按 `$prism-research-semantic-clustering` 的 [输入契约](../prism-research-semantic-clustering/references/contracts.md)交接。每条必须回指完整话语和对象；原始私人访谈不随通用技能包传播。
