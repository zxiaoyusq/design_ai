---
name: prism-run-contract
description: 冻结棱镜项目目标、资料范围、分支、候选容量、成板数量及模型预算，登记可复用状态。用于启动或接续运行；不代替各环节算法。
metadata:
  version: "2.1.0-project"
---

# 棱镜｜范围与运行约定

读取 [项目与阶段合同](../prism_skill_support/references/contracts.md) 和 [阶段路由](../prism-workflow/references/routing.md)。本技能只管运行约定与账本，各业务判断交相应小技能。

输入当前用户要求、资料目录、已完成产物和权限。输出 project.frozen.json、state.json、阶段清单和本次剩余工作。记录设计问题、ID/CMF分支、候选池规模、最终板目标/上下限、来源排重政策、当前模型、执行预算、输出位置、选向与审阅责任人。已明确的条件直接沿用。

候选池容量和最终图片数量分别设置。约10张是展示目标，不能据此把召回、解析或导航截为10张。30/100是已做的比较档位，不是新任务固定默认值。历史六方向、3+3也不是所有项目的必选数量。

H01之前只处理两侧语义。设计师确认后才对选中方向的有界候选池进行图片DNA/品质处理。同一原图R5可复用，当前目标品质不能因字节相同自动继承。固定Sol R5用 gpt-6-sol / low / default请求档 / Fast关闭；其他环节沿用当前指定配置并保留实际身份，不能暗换模型。

本包内的旧Root代审、任务调度、付费接口、额度卡授权均不继承。用户已授权的当前有界任务可直接做必要本地操作；不为常规可逆步骤反复问。新费用或外部写入没有授权时，先完成可审阅准备。

本地账本命令（不调用模型）：
```text
python -B -X utf8 ../prism_skill_support/scripts/workflow.py init --config project.json --out new-run
python -B -X utf8 ../prism_skill_support/scripts/workflow.py status --run new-run
```
按输入/规则/模型/当前范围哈希复用；只增加说明不重跑。中断时留下可接续阶段，不把局部完成写成全流程完成。问题复验由 `$prism-independent-evaluation-loop` 负责。
