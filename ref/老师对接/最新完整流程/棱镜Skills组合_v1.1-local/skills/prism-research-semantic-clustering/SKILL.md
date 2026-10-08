---
name: prism-research-semantic-clustering
description: 将用研原话按含义归纳为偏好主题、单人线索与设计议题，保留正反态度、对象范围和来源。用于用研偏好纯语义聚类；不用于图片聚类、DNA解析、趋势排名或市场比例推断。
---

# 用研偏好：纯语义聚类

输出可供第一次趋势握手消费的语义簇。模型负责理解语义；随包 Python 负责冻结输入、校验原文和来源、保留覆盖台账、按人去重。它不是关键词分类器，也不是已经训练好的嵌入模型。

## 输入与运行

先读 [输入输出约定](references/contracts.md)。接受已整理的原话和来源；有原文报告时，先用现有文档工具逐条提取并核对。只拿到摘要时明确标为分析笔记，不能补造受访者原话。原文、对象和态度不清楚则保留未知。

脚本要求 Python 3.10+，仅用标准库。从本 Skill 目录运行；在其他目录调用时使用脚本绝对路径。

```text
python -B -X utf8 scripts/research.py prepare --input research-input.json --out run-01
```

也可用 `--dataset` 替代 `--input` 接收约定的原生数据目录。`prepare` 会复制和冻结输入，不读取图片像素、不调用模型。

读取 `run-01/reading-packet.json` 中全部记录、提示词和 contract。由当前助手作语义判断，参考 `proposal-template.json` 的身份绑定，另存 `proposal.json`。记录实际分析者、实际模型（拿不到则写 unknown）和自查状态。保持用户指定的模型和 Fast 设置；不要擅自开新付费 API、额外任务或自动批次。

## 归纳规则

- 根据共同含义归纳；同词可以异义，不同词可以同义。主题数由资料决定；同一条多义表达可进入多个簇，但要说明不同分量及残余含义。
- 区分四类：至少两位直接表达设计偏好者的 `shared_theme`；恰好一位直接表达设计偏好者的 `exploratory_signal`；包含分歧/条件的 `design_issue`；个人目标等 `background_theme`。类型人数按直接设计支持者计算，不按定义中的文字或所有提及者计算。只有品牌印象时不是 exploratory_signal，可在相关 design_issue 中单列品牌关联，或留为参考；不要将品牌改成直接设计支持。设计议题不是全体一致偏好。
- 每个 member 写准确原文子串、来源单元 ID、关系、分量、解释和限定。quote、relation、facet、rationale、limits 均为非空字符串；多个限定写在同一 limits 字符串中。程序同时附带完整句子；不能用短引文去掉“太、但、不”和对象。
- 直接偏好、品牌印象、个人愿望、概念举例、仅提及分别保留。品牌印象单列人数；举例不算喜欢；同一人重复记录只算一个人。
- 保留喜欢、排斥、替代方案、条件与未知。“边框可亮、背板太亮”按对象和程度保存；不要改成笼统“喜欢亮面”或“排斥所有光泽”。
- 每条输入必须有 coverage 去向。未聚类的否定必须是 `unclustered_boundary`。未提及/未选择不等于反对；不估计国家、市场或总体人群比例。
- 图片关联只是既有来源回链，不重新认图或猜偏好，不因进簇而变成视觉验证通过。

按 [语义复核表](references/semantic-review.md) 自查。明确同一助手自查是 `same_analyst_review`；没有另一位实际复核者时不写独立复核通过。

```text
python -B -X utf8 scripts/research.py accept --run run-01 --proposal proposal.json
python -B -X utf8 scripts/research.py verify --run run-01
```

验证失败时修正有来源的问题，另存提案；不得调整原始态度、预期或样本身份来凑通过。已有成功结果不覆盖，修订另开 run。每个问题最多三轮有界修订，仍失败交付缺口和证据。

## 交付与衔接

交付整个 run，重点说明 `clusters.json`、逐条 coverage、原文、未匹配记录和验收结果。`verify` 通过只证明结构/来源可复放，不证明语义正确或业务效果。

将 `run-01/dataset` 与 `run-01` 分别交给 `$prism-h01-semantic-handshake` 的 `research_dataset_path`、`research_run_path`。它会重放完整编译过程，不能只交 `handshake-input.json` 摘要或信任 supported 缓存。

离线合成例子与边界测试：

```text
python -B -X utf8 scripts/demo.py --out demo-run
python -B -X utf8 scripts/selftest.py --out test-run
```

这些例子全是虚构人物和材料；模板不能直接套到新受访者。算法来历和适配范围见 [source-version.json](references/source-version.json)。

## 本组合的衔接

参见 [组合输入输出合同](../prism_skill_support/references/contracts.md)；上游/下游路径按当前项目配置，不继承源任务的执行批准。阶段问题到三轮应提交证据与方法决策，不代表整个项目自动停工。完整组合由 `$prism-workflow` 按需路由。
