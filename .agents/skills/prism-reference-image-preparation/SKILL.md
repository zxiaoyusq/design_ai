---
name: prism-reference-image-preparation
description: 将已有R5观察绑定到当前ID对象或CMF表面，完成原生品质验收及真实裁片复核，输出可入组的单图参考。用于选组前准备；不重新定义视觉条件，不用展示增强补证据。
metadata:
  version: "1.0.0"
---

# 棱镜｜单图参考准备

这是对象绑定、当前目标品质和裁切处理的统一入口。继承同事 v2 的原生算法与证据边界，不把三个原提示拼成一次判断，不以本地字段代替品质主判、目标归属复核或真实裁片阅读。

## 输入与输出

输入冻结的 `material_brief`、单张 `material_plan`、原图身份与来源、R5 原结果和已知观察，已有品质包可选。输入不完整先输出缺口，见 [输入和输出合同](references/input-output.md)。

输出单图参考包：`target_binding`、原生 `quality_bundle`、真实 `comparison_view`、独立 `crop_review`、来源及处理台账，外加 `candidate_eligibility` 与缺口。它表示可否进入后续 ID/CMF 选组，不表示已通过整板。原生 H2 所需的投影字段保持原样。

## 执行

按真实依赖闭合这一张图片，可迭代局部取景；不机械要求所有任务采用同一种顺序：

1. 复验原图/R5 身份，实际看图，预绑定当前目标及其已有观察。读 [绑定规范](references/binding.md)。平面 `at` 不是对象树或准确 bbox；缺少当前范围观察记 `scope_gap`，交 DNA 环节定点补查，不改标签冒充覆盖。
2. 根据冻结的视觉关系提出 ROI，生成并查看真实裁片或实际渲染视窗。独立上下文对照原图及裁片，确认主关系突出、干扰受控、反证未隐藏。读 [裁切规范](references/crop.md)。
3. 对当前声明目标进行原生品质主判，另一个真实上下文复核归属与覆盖，再由原生 `quality/accept` 验收。读 [品质规范](references/quality.md)。已验收缓存只复用其实际覆盖；父品质与比较窗口分开保存，不能借另一物件的 PASS。
4. 品质 bundle 形成后完成原生绑定。范围、状态、ROI 或原字节变化只复验受影响的绑定、品质及裁片；闭合身份与依赖后输出是否可进入选组。若先做品质更符合依赖，可先验品质再取景，但最终必须检查实际显示结果。

原图细节清楚但展示像素不足时，可找同源高清图或在当次授权内另作展示增强。新增原字节需要复验受影响身份及证据；增强版本仅供展示，不能覆盖原图/R5、证明原来不可辨认的细节或替代原始品质。

## 原生接口与执行边界

原生合同按需读 [R5/H2 合同](../prism_skill_support/references/contracts.md)、[声明范围政策](../prism_skill_support/references/declared-visible-scope-policy.txt)、[执行回执](../prism_skill_support/references/execution.md)。工具从路径实际解析，不假设当前目录：

```text
python -B -X utf8 .agents/skills/prism_skill_support/scripts/native_api.py describe --module quality
```

工程离线验收复用 `backend/app/services/visual_workflow/colleague_v2.py::validate_target_material`，不能新抄一套品质算法。原生调用参数和回执投影见 [输入和输出合同](references/input-output.md)。

R5 提取及模型配置由 `prism-dna-sol-r5` 负责；本 Skill 不修改冻结 R5、不自行补提全库。没有当次执行授权不发模型请求；模型暂停时仍可做已有回执重放及缺口登记。独立上下文与真实图像附件必须有来源回执；合并入口不减少这些必需判断。
