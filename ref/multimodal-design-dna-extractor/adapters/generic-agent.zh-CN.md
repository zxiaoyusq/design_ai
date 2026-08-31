# 通用多模态 Agent 接入

## 原生支持 Agent Skills

把整个 `multimodal-design-dna-extractor` 目录放入宿主的 Skill 注册目录或通过其 Skill 上传入口导入。宿主应先索引 `SKILL.md` 的 `name` 和 `description`，触发后再加载正文和引用文件。

## 不支持 Agent Skills

1. 运行 `python scripts/build_prompt_bundle.py --output prompt_bundle.txt`。
2. 把生成文件作为 system/context 输入。
3. 把一张图片作为视觉输入。
4. 把 `assets/user-request-template.zh-CN.md` 作为用户消息。
5. 用 `schemas/design-dna-output.schema.json` 约束输出。
6. 运行 `python scripts/validate_output.py result.json` 做二次校验。

## 工程重试建议

- JSON 解析失败：只要求模型修复 JSON 语法。
- Schema 失败：把校验器的错误路径回传，要求只修复对应字段。
- 语义失败：要求模型重新检查证据引用、低置信度字段和风格硬规则。
- 不要在重试时重新描述图片，以免引入新的无证据事实。
