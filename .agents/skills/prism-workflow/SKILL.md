---
name: prism-workflow
description: 按同事v2原生规则编排两侧语义、选向、合并后的视觉选材/单图准备/视觉选组与10项目情绪板；网页只做格式映射。
metadata:
  version: "2.1.0-project"
---

# 棱镜 v2 工程入口

以 [运行约定](../prism-run-contract/SKILL.md) 为起点，按 [当前项目路由](references/routing.md) 仅加载本阶段。主流程由13个业务Skill承担；原生17项同事基准仍在工程的v2-project包中作为实现和证据库，不再额外调用已合并的七个旧入口。

选向后统一交 [视觉转译与选材](../prism-visual-material-planning/SKILL.md)，先校准具体关系与素材容量再冻结。R5提取/范围复用仍由独立Skill负责；绑定、品质和实际裁片统一交 [单图参考准备](../prism-reference-image-preparation/SKILL.md)。随后 [视觉选组](../prism-visual-grouping/SKILL.md) 按显式ID/CMF分支调用原生算法。三个合并的是操作入口，原生字段、检查步骤、独立品质/裁片上下文与实际调用账本不合并成一次模型推理。

本次用户明确要求新板最终 **10张、10个可核实独立项目**。候选容量与最终数量分开登记，不能把解析池截成10–12张。原图预览先校准具体主关系、必要证据、第二强信号、来源容量和处理动作，再冻结material-brief；「高级」「简洁」不是完整视觉条件。槽纹案例的五条起伏/低彩度不泛化为所有方向。

依次完成定位目标、提出ROI、实际生成/查看裁片、重新判断主关系与干扰、原生品质与H2、实际整板独立审阅。裁片通过不保证整板；离群项可被板审否决，按原条件修ROI/补清楚来源/换成员，在第10合格独立项目补齐前保持未完成。单个问题最多三轮定点修订，模型执行失败不自动重发。

R5严格使用同事冻结gpt-6-sol/low/default/Fast关闭及原CLI输入；原提取和视觉审阅分开。已有DNA只复用其真实覆盖的对象/at与known范围，缺当前范围是scope_gap，不补造事实。CMF遵守surface/same_object_interface；历史H007跨物件扩展不进入新原生链。

预算按本项目资料和当前授权登记，不继承旧60原图/12ROI/2板审作为通用硬门，也不自动拿30/100作默认。预算耗尽记未完成。新的授权、模型上限与独立项目证据未就绪只做prepare；当前工程模型仍暂停。旧4/5张板和旧回执只作历史，不重标新10项目PASS。

工程执行合同见 `backend/app/services/visual_workflow/colleague_v2.py`；网页投影见 `web_adapter.py`。它们重放原生门，不用本地格式检查代替真实看图。需要交接完整流程时读[各阶段输入/输出](references/flow-input-output.md)，本次配置草案和迁移记录见[工程衔接](references/project-integration.md)。
