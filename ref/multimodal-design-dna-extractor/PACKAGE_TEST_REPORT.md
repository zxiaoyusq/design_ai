# Package Test Report

测试日期：2026-09-01

## 结论

`multimodal-design-dna-extractor` 2.0.0 已完成定义重构、确定性校验和工程接入回归。知识库与注册表由 Skill 包独立维护，不依赖原 Excel 或其他外部源文件。

## 结构基线

| 项目 | 结果 |
| --- | ---: |
| 一级导航族 | 6 |
| 活动二级风格 | 31 |
| 已弃用并可迁移风格 | 1 |
| 集中混淆组 | 8 |
| 规范 DNA 字段 | 183 |
| 历史字段 ID 真别名 | 25 |
| 显示名别名 | 1 |
| 零权重兼容推导 | 31 |
| 回归评测用例 | 43 |

## 规则与数据校验

- 每个活动风格均具备机制定义、颜色角色、硬门槛、决定锚点、独立辅助证据、硬排除、混淆组、异混淆特征及机器字段 allowlist。
- 稳定 `style_id`、显示名、别名、弃用迁移、规范字段、真别名和兼容推导分别注册；兼容推导固定 `decision_use=none`、`weight=0`，不能参与风格判定。
- `active_profiles`、字段适用 profile、必要视角、M15 排除、可观察性、计算状态和证据模式均由 Schema 与语义校验器共同约束；单图禁用 multi-face profile。
- 枚举、受控列表、比例、长宽比、数量、语义刻度和 OKLCH 基础范围均执行确定性值域校验。
- 纯字符串标签集使用 `multi_label`，结构化集合使用 `list`；派生值必须闭合注册源字段及其证据，`CLR-20` 不再承担硬门槛。
- 主次风格命中只能引用本次可用的规范字段；决定字段与辅助字段不可混用，且必须命中对应风格 allowlist。
- `new_enum_value` 只能扩展现有枚举字段；通用字符串 `none` 已改为类型内缺席值或空列表。
- 原六维只保留空的宿主兼容槽，不再由模型重复生成或参与判定。

## 自动化结果

- Agent Skills 快速规范校验通过。
- JSON Schema Draft 2020-12 元模式校验通过。
- 手机与服装两个 v4 示例均通过 Schema、注册表和语义校验。
- 知识索引重建一致；Prompt bundle 可完整生成，共 173,257 字符、223,267 字节。
- 43 条 JSONL 评测用例均可解析且 ID 唯一，覆盖 24 条混淆边界和 19 条通用约束。
- 反例变异校验均被正确拒绝，覆盖非法 profile、缺失 M15、非法枚举/比例/语义刻度、风格字段越权、非观察计算、兼容推导冒充规范字段及跨 profile 字段注入。
- 完整结果保存与业务视图转换通过；v3/v4 标签格式及 M04/M10 模块语义分别兼容，`IMG-03` 的结构化标签可正常提取。
- 后端 28 项自动化测试通过；前端 TypeScript 检查与生产构建通过。
- 包级结构、内容与 28 个文件校验和通过。

## 独立前向测试

- 对 `20260831-213714.jpeg` 从零执行当前完整规则，主风格为 `SaturatedBold / 个性鲜彩`，91 分、置信度 0.91，无次风格。
- 42 个规范字段通过最新 Schema、注册表和语义校验；未激活 multi-face，缺依赖的 `CLR-12/CLR-20` 未输出。
- CG-05 仲裁明确排除背景运动模糊、结构边界和窄饰条；普通泡罩/卵形壳不触发 `BiomorphicForm`，通用功能件不触发 `NeoRetro`。
- 结果 SHA-256：`7589bb202a18fca98cc292c9986fdbe5cde006b5facd4134f45064b15bc45c39`。

## 关键命令

```bash
python scripts/validate_skill_package.py
python scripts/validate_output.py examples/smartphone-rear.example.json
python scripts/validate_output.py examples/apparel.example.json
python scripts/build_knowledge_index.py --check
python scripts/build_prompt_bundle.py --output /tmp/design-dna-prompt-bundle.md
```
