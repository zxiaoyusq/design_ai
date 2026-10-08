---
name: prism-visual-material-planning
description: 将已选语义方向转成可检验的视觉条件，并通过真实素材预览校准候选容量、来源和处理计划；用于冻结选材标准，不授予单图品质或整板通过。
metadata:
  version: "2.1.0-project"
---

# 棱镜｜视觉转译与选材

合并原可见家族与广候选选材的业务入口，内部保留同事 v2 的比较规则、材料合同与原生字段；不是一次大 Prompt 取代原算法。

## 输入与输出

输入：已验证 H01 结果、当前方向选择及 ID/CMF 分支、设计背景、项目数量/预算政策、文章与图片来源清单；已有 DNA 可辅助召回，不作为视觉合格依据。

输出：一个可追溯的选材资料包，含共同视觉条件 `visual-family.json` / `material-brief.json`、`metadata-pool`、原图 manifest、逐图 `material-plan`、冻结的 DNA 候选池、容量不足与待补证清单。文件名可适配工程，内容保持原合同。详情见 [输入输出与交接](references/io-contract.md)。

## 执行

1. 把语义方向转为可指认的主关系，写出比较对象、必要可见证据、允许变化、干扰项和比较尺度。ID 比整件；CMF 比指定表面或同物件相邻界面，不能跨对象拼证据。
2. 从选中趋势文章池召回，扩展参考单列并说明设计关系依据。真实预览校准条件与独立项目容量，逐图登记目标、第二强信号、建议取景及处理动作。正文依据见 [设计转译](references/design-translation.md) 和 [候选选材](references/source-selection.md)。
3. 共同条件与材料供应满足后再冻结 brief / 候选池并保留原始来源引用、SHA、版本、实际读图记录与未完成项。候选不足反馈上游明确决策；冻结后改条件须新版本并复验受影响材料，不能为保留某图或凑数量改标准。

本项目新板目标为 **10 张合格图片、10 个可核实独立项目**；不同 URL 不证明项目独立。候选量与成板量分开，按素材异质性、容量与当前预算设定，不预设 10–12、30/100 或旧 60/12/2。后续新任务使用其明确项目合同。槽纹条数、低彩度等案例条件不泛化。

保留 H01 原负向和未决义务。旧 DNA 仅覆盖它实际解析的范围；当前目标缺失标 `scope_gap`，不能借另一对象的品质。预览与本地准备不等于视觉或品质 PASS，校准图不计正式候选。

需要完整字段时读取 [共用合同](../prism_skill_support/references/contracts.md) 和 [选材合同](../prism_skill_support/references/material-contract.md)。复用 `../prism_skill_support/scripts/material_plan.py` 校验冻结材料；它只产生 prepared / findings，不执行模型、不授予视觉通过。下载仅访问明确清单并服从当前授权。随后交 `$prism-dna-sol-r5` 与 `$prism-reference-image-preparation`，不自动开启全量模型运行。
