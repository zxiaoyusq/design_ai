---
name: user-research-design-clusterer
description: 将用户画像、审美问答和需求文本完整整理为可追溯的审美设计方向，保留少数偏好、条件与冲突，输出供趋势聚类匹配的用研侧契约。用于用户调研文本聚类；不分析图片，不执行趋势匹配。
metadata:
  version: "1.0.0"
---

# 用户调研审美设计方向聚类

把用户喜欢的设计、审美偏好、身份表达、生活方式、使用情境和购买动机综合为**设计方向**。方向回答一个具体设计问题；同一用户可支持多个方向，单人偏好也保留。不以国籍、性别或图片重叠作为聚类规则。

默认输入 `PROJECT/data/userreseach_data/users_selected_5.json`，也接受同结构用户 JSON。先读 [文本整理规则](references/extraction.md)，聚类时读 [方向聚类规则](references/clustering.md)，文件格式和后续握手见 [输出契约](references/output-contract.md)。

## 完整性和输入边界

- 全部 `profile` 字段、每条 `aesthetic_research.ai_analysis`、每条 `demand_research.ai_index` 都进入文本清单；保留问题、场景、回答类型以及源定位。空值和“未提及”也登记，不能整条过滤有实质内容的混合回答。
- 每条文本按原顺序分成片段，片段全文拼接必须与源文本一致；每个片段产生一个或多个原子观点，或给出保留原因。聚类后每个观点都必须有去向，审美设计观点不能只因小众而丢入未聚类项。
- “不遗漏”依靠全文清单、片段和观点去向逐层约束。程序能检查文本及引用完整，不能证明模型理解已捕获每个隐含语义。不得把结构校验通过宣传为绝对语义无遗漏。
- 只读文本。不要打开图片、PPT、URL，不调用视觉提取或图片 DNA Skill。`image_preferences`、`ppt_images`、`ref_pic_links` 及图片描述不进入语义输入。回答正文中的图号和排序全文保留；只有图号时标为 `image_reference_only`，不得从图号、文件名或品牌常识补造造型/CMF。已有问答正文里的设计描述可以按文本引用。
- `ai_analysis` 是既有分析文本；PPT 补录是已转录/翻译文本；`ai_index` 是源需求记录。保留三者来源性质，引用只能称为“源文本”，不一概称为用户逐字原话。题干只是理解回答的上下文。

## 工作流

项目使用 conda `314`。以下脚本只做离线准备、完整性检查和编译，不请求模型；由当前宿主完成语义处理，服务接入时复用项目 DeepAgents 宿主。

```bash
conda run --no-capture-output -n 314 python SKILL_DIR/scripts/pipeline.py prepare \
  --input PROJECT/data/userreseach_data/users_selected_5.json --dry-run
conda run --no-capture-output -n 314 python SKILL_DIR/scripts/pipeline.py prepare \
  --input PROJECT/data/userreseach_data/users_selected_5.json \
  --out PROJECT/data/result/user_research_clusters/新的运行目录
```

准备会冻结输入哈希、完整文本清单、Prompt 和按用户组织的请求。默认单包 48,000 字符（不是 token）；超长用户只在源记录边界拆包，单记录超限则报告，不截断。输出目录必须新建。

1. 读取每个 `requests/B*.json` 的全部 messages，按其协议处理全部记录。将回复分别保存到 `extractions/B*.json`，记录真实模型标识/版本、执行时间和请求中的 `prompt_sha256`。服务未提供的模型字段写 `null`，不能猜测；结果会披露追溯缺项。每处理一包即保存文件，不依赖会话记忆。
2. 执行 `pipeline.py collect --run RUN`。程序检查每条输入和完整片段，生成 `observations.json`、`coverage.json` 和 `cluster-request.json`。缺包、截断、错误引文或未知引用只定位问题；保留原回复，针对问题修正，不自动全量重跑。
3. 读取 `cluster-request.json` 的全部观点，依据聚类规则编写 `clusters.json`。原文在 `sources.json` 和提取文件中可回查。不要固定方向数、只取高频或只取前三条；上下文放不下时分批形成候选方向并保留完整观点 ID，最终必须读取所有批次并合并，不能以裁剪摘要替代遗漏部分。
4. 执行 `pipeline.py finalize --run RUN --clusters RUN/clusters.json`。只有全部文本、全部观点和全部用户均有去向时才能生成 `final/result.json`、`final/report.md`、`final/handshake.json`。失败或中断不得宣布完成；没有设计证据则明确返回空方向。

## 聚类和后续使用

以设计问题和可描述特征聚合，不只按“高级、个性、科技”等词或品牌同名合并。保留对象、作用部位、场景、情绪意图、接受条件和排斥项；同一用户的不同场景与跨用户分歧可在一方向内并列，不强行平均。跨品类应用和设计建议标为推导建议，不改写成用户已认可。

每条方向输出带原子观点引用的具体设计特征、差异和推导建议；另输出全部用户的定位摘要及原画像。用户人数由代码按身份去重，各种态度分别计数；5 位样本不代表市场占比。

`handshake.json` 是独立的用研侧输入，保留方向 ID、设计问题、带态度的特征、使用条件和来源。后续与趋势方向的语义特征匹配，`clustering_label` 只能帮助检索；不能把用研中的排斥项当正向交集。本 Skill 不虚构趋势来源、交集强度或高潜评分，也不改变现有趋势 Skill 的运行协议。

## 开发验证

对真实五用户文件只做离线清单准备即可验证字段适配；语义流程与脚本使用 2 位用户、少量复合回答的微型夹具。开发 Skill 不等于授权全量真实模型回放。

```bash
conda run --no-capture-output -n 314 python -m unittest discover -s SKILL_DIR/tests
```

交付时给出结果文件和覆盖状态；不能只有方向短摘要。原文清单、保留片段和观点索引都是交付内容，可用于检查细节和后续重新匹配。
