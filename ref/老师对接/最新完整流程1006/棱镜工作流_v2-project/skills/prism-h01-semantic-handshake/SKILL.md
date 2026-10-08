---
name: prism-h01-semantic-handshake
description: 对齐趋势语义簇与用研语义簇，完成第一次握手，输出可选择的方向、双侧原文依据、条件和完整负向审计。用于H01语义候选筛选；不做图片解析、高级感、H02视觉握手或情绪板。
---

# 趋势与用研：第一次语义握手

先用文字形成候选方向，再由设计师或获得本次明确授权的AI选定方向。候选选择完成以后，其他环节才处理图片DNA、高级感、ID风格与CMF细节。

模型进行含义对齐；随包代码冻结两侧资料、校验引用/角色/覆盖、记录选择。本 Skill 不内置付费模型调用器。使用当前用户指定的模型和 Fast 设置，保存实际模型身份；不要自行调用新API、启动另一个任务或用历史代理授权代替本次授权。

## 准备

读取 [输入输出与操作约定](references/contracts.md)。要求完整的用研语义簇、原始文字与编译提案，以及趋势语义簇与原文/存档释义目录；只拿到摘要时先列明缺项。

Python 3.10+。H01校验需要 requirements.txt 中的 jsonschema；先检查现有环境，缺少时按当前环境的依赖安装规则处理。从本 Skill 目录执行：

```text
python -m pip install -r requirements.txt
python -B -X utf8 scripts/handshake.py prepare --config config.json --out h01-run
```

prepare 冻结输入并输出 `messages.json`、`response-schema.json` 和模型传输用的 `response-schema.wire.json`。两侧都只有文字；图片关联可留在旁表，不进入模型判断。依赖中的用研校验核心已随包附带，不依赖另一台电脑或另一个Skill的安装路径。

## 做语义握手

读取 messages 中全部实际成员与原句，按当前设计问题提出候选。不能只做两个簇标题的字面相似度比较。每个方向都需双侧具体依据、共同设计原则、边界及未解决问题。

- `consensus` 共识优先：仅直接支撑候选；`extension` 适度延展：可有明确依据的延展；`exploration` 创新探索：可再含探索假设。档位不降低原文、否定和对象范围要求。
- 跨产品、跨载体或仅由品牌/背景联想而来的结论要明确延展依据和假设，不能写成用户直接想要。direct_support 不得夹带隐藏的延展假设。
- 保留原话、人物、正反态度、对象、程度与条件。品牌印象、愿望、提示举例不计直接偏好；引用摘要不升级为已验证支持。以原始材料的 evidence_kind/text_kind 区分原文和释义。
- 对每条原始否定，审计它对**每个候选方向**的适用性：applicable、unresolved 或有具体依据的 not_applicable。不得遗漏、重叠、删除未聚类否定，或批量把未知当作无关。
- 条件必须精确引自原句或对应簇边界。unknowns、common_meaning 或作者推断不能伪装成边界原话。
- 逐一交代两侧每个簇是否使用。所选方向建议走 ID、CMF 或两者，但此时还没有视觉匹配结论。
- 数量由证据决定。requested_selection_count 是希望后续选择的数量；不足就说明缺口，不扩宽标准或造方向凑数。不输出无依据的“高潜分”。

保留未经修改的模型回答为 `proposal.json`。先按 [语义审阅要点](references/review.md) 检查，再运行：

```text
python -B -X utf8 scripts/handshake.py accept --run h01-run --proposal proposal.json
python -B -X utf8 scripts/handshake.py verify --run h01-run
```

失败时保留原回答，按具体错误修订另存提案；每个问题最多三轮。不能改源数据或自动填齐“无关”使结果通过。本便携版采用严格验收，不附带旧案例中针对单个ID的应急修补器。

## 选择及交付

先呈现候选、双侧依据、每条负向意见和遗留问题。收到选择或当前明确的AI代选授权后，写 choices 和可追溯 confirmation，再执行 select；模板的 pending 状态不会通过。不能将自己作出的选择记录为人类设计师确认。

交付整个 h01-run，重点为 `candidate-directions.json`、`accepted.json` 和存在时的 `selection.json`。输出含原始语义证据和源关联图片ID，图片依然未筛选。执行DNA和高级感由后续独立Skill负责；本Skill到选择记录即结束。

“accepted/verified”证明协议、引文、覆盖可重放；不证明候选语义或设计效果正确，也不证明情绪板视觉一致。缺人群代表性、未知对象或未解决负向意见必须继续带往下游。

离线演示和边界测试：

```text
python -B -X utf8 scripts/demo.py --out h01-demo
python -B -X utf8 scripts/selftest.py --out h01-tests
```

示例全部合成；一个方向只是例子，真实工作不固定五个人、五个方向或固定簇数。源版本与便携适配见 [source-version.json](references/source-version.json)。

## 本组合的衔接

参见 [组合输入输出合同](../prism_skill_support/references/contracts.md)；上游/下游路径按当前项目配置，不继承源任务的执行批准。阶段问题到三轮应提交证据与方法决策，不代表整个项目自动停工。完整组合由 `$prism-run-contract` 按需路由。

## 选向分工

候选审阅后，把选向交 `$prism-direction-selection`；它仍调用本技能的原生select，不另造确认格式。H01只给探索资格，不证明图片已可用。
