# 通用多模态 Agent 接入

## 原生支持 Agent Skills

导入整个 `multimodal-design-dna-multitag-extractor` 目录。宿主先索引 `SKILL.md`，触发后再加载正文与引用文件。

路由条件必须是用户点名本 Skill，或明确要求“扁平、多标签、无主次、组合风格”。普通设计 DNA 提取应转给原 `multimodal-design-dna-extractor`。

## 不支持 Agent Skills

仅在用户明确选择扁平多标签工作流时执行以下步骤；普通设计 DNA 请求继续走原版工作流。

1. 运行 `python scripts/build_prompt_bundle.py --output prompt_bundle.txt`。
2. 把生成文件作为 system/context 输入。
3. 提供一张图片与 `assets/user-request-template.zh-CN.md`。
4. 用 `schemas/design-dna-output.schema.json` 约束输出。
5. 运行 `python scripts/validate_output.py result.json`。

重试时只回传具体 JSON、Schema 或语义错误路径；不要重新描述图片，以免引入无证据事实。

宿主应拒绝 TribeIdentity 等废弃风格 ID；身份信息只进入 IDG-05/07/09，不参与风格标签集合。
