---
name: prism-research-intake
description: 从受访者报告提取文字、图片出现位置和原始来源，区分问题、选项、回答与分析笔记。用于用研报告入库；不替代语义聚类或从图片猜偏好。
metadata:
  version: "1.0.0"
---

# 用研原始证据入库

把原始报告转为可回查的证据，不预先编造主题。先读 [组合输入输出合同](../prism_skill_support/references/contracts.md) 的“用研原始材料”。

接受用户提供的PPTX、PDF或其它报告及人物对应关系。保留匿名person_id、source_id、源文件SHA、页/shape位置、原文和原图字节。同一图片可被多个受访者使用，去重图片字节不能抹掉人物出现关系。

随包PPTX辅助工具仅提取文字、媒体和裁剪/旋转元数据：
```text
python -B -X utf8 ../prism_skill_support/scripts/intake_pptx.py --config intake.json --out intake-run
```
它不渲染完整原页，不判断哪段是答案。实际查看原页或可靠页面渲染，区分模板问题、选项、已填回答、品牌印象、人物背景和作者笔记。换新报告模板不得套用旧五人的页码表。没有Office可用当前文档/PDF工具；若无法渲染，明确留下视觉布局核对缺口。

检查否定、转折、程度和对象。PPT整理不冒充逐字访谈；不由文件名猜访谈年份。不用靠近的图片或同页图组推断喜欢其全部视觉属性；只记来源候选关联。

输出raw-evidence、图片出现记录、媒体哈希、来源清单，再基于实际原页将research-input.draft.json整理为reviewed输入；草稿全部reference/unknown是待分类状态，不能视为偏好数据已完成。

按 `$prism-research-semantic-clustering` 的 [简易输入契约](../prism-research-semantic-clustering/references/contracts.md)交接。每条语义单位需能回指完整原话和对象；原始材料不随通用Skill传播。
