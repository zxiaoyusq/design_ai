# Multimodal Design DNA Extractor Skill

这是一个面向多模态 Agent 的通用设计 DNA 提取 Skill。它将原先的一段长提示词拆分为可版本化、可验证、可评测的能力包，适合接入审美洞察、素材入库、相似检索、方案契合度评分和知识库增量维护流程。

## 为什么需要 Skill

该任务同时包含单主体选择、跨品类适用性、规则型风格分类、开放式字段提取、证据定位、置信度校准、不确定性管理和知识库外新元素发现。单次 Prompt 可以完成演示，但难以稳定复用、回归测试和版本管理，因此建议沉淀为 Skill。

## 目录

```text
multimodal-design-dna-extractor/
├── SKILL.md
├── README.md
├── manifest.json
├── references/
│   ├── extraction-protocol.zh-CN.md
│   ├── output-contract.zh-CN.md
│   ├── design-dna-knowledge-base.zh-CN.md
│   ├── knowledge-index.zh-CN.md
│   ├── category-adaptation.zh-CN.md
│   └── novel-dna-governance.zh-CN.md
├── schemas/
│   └── design-dna-output.schema.json
├── scripts/
│   ├── validate_output.py
│   ├── save_result.py
│   ├── build_prompt_bundle.py
│   └── validate_skill_package.py
├── assets/
│   └── user-request-template.zh-CN.md
├── examples/
│   ├── smartphone-rear.example.json
│   └── apparel.example.json
├── evals/
│   ├── cases.jsonl
│   └── rubric.zh-CN.md
└── adapters/
    ├── generic-agent.zh-CN.md
    ├── openai-chatgpt-codex.zh-CN.md
    └── claude.zh-CN.md
```

## 最小使用方式

1. 将整个目录安装或挂载到支持 Agent Skills 的宿主。
2. 向 Agent 提供一张图片，并提出“提取主物品设计 DNA”类请求。
3. Agent 激活 `SKILL.md`，读取知识库与输出 Schema。
4. 结果生成后，在工程根目录执行校验与落盘：

```bash
conda run -n base python ref/multimodal-design-dna-extractor/scripts/save_result.py \
  --image /path/to/product.jpg result.json
```

完整结果会写入 `data/result/YYYYMMDD_HHMMSS_<图片名>_design_dna.json`。随后运行：

```bash
conda run -n base python extract_design_dna_business_view.py \
  data/result/YYYYMMDD_HHMMSS_<图片名>_design_dna.json
```

业务视图会写入同一目录的 `YYYYMMDD_HHMMSS_<图片名>_design_dna_business_view.json`。

## 传统 API 接入

对于不原生支持 Skill 的多模态 Agent，可先生成合并后的系统上下文：

```bash
python scripts/build_prompt_bundle.py --output prompt_bundle.txt
```

然后把 `prompt_bundle.txt` 作为系统提示词/上下文，把图片作为单独的视觉输入，把 `assets/user-request-template.zh-CN.md` 作为用户任务模板。

## 推荐模型参数

- 温度：`0.0–0.2`
- 结构化输出：JSON Schema 或 JSON object
- 图片：单张，尽量保留主体细节
- 生成后：Schema 校验 + 语义校验 + 失败重试

## 版本

- Skill：`1.1.0`
- 输出 Schema：`design_dna_extraction_v3.1`
- 设计 DNA 知识库：`2.0`

## 数据与权利说明

本包中的设计规则与知识库来自用户提供内容及针对该项目的扩展，默认用于项目内部。未额外授予第三方再分发许可。
