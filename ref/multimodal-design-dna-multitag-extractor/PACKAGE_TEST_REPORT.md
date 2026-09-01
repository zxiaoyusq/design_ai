# Package Test Report

测试日期：2026-09-01

## 结论

`multimodal-design-dna-multitag-extractor` 1.2.0 已完成组合预设的确定性结果派生、双 Schema 分层、校验和回归评测。它继续独立维护，不替换或修改原 `multimodal-design-dna-extractor`。

## 结构基线

| 项目 | 结果 |
| --- | ---: |
| 输出 Schema | `design_dna_multitag_extraction_v1.1` |
| 知识库 | 4.1 |
| 活动扁平风格 | 38 |
| atomic / composite | 37 / 1 |
| 已弃用并可迁移风格 | 2 |
| 后台 facet | 7 |
| 显式标签对关系 | 54 |
| 复合依赖 | 1 |
| 查询组合预设 | 12 |
| 规范 DNA 字段 | 192 |
| 字段 ID 别名 / 名称别名 | 26 / 1 |
| 零权重兼容推导 | 31 |
| 完整示例 | 3 |
| 图像规则回归 / Python 派生评测 | 80 / 14 |

## 规则与数据校验

- 结果只含 0～3 个同层 `style_tags`，不含一级、二级、父级或主次风格字段；多标签不是强制目标。
- confirmed 标签分别闭合硬门槛、决定锚点、辅助证据、颜色、排除项和非零规则计数；其 core/aux 字段及证据置信度均须不低于 0.75。
- 单标签 dominance 固定为 1，多标签总和约为 1；标签与候选分别使用确定性排序。每对 confirmed 标签唯一且完整地写入仲裁。
- conditional 同区关系显式区分 `forbidden` 与 `independent_evidence`；后者须具备双方独占核心字段、独占字段证据及覆盖两侧的仲裁证据，默认关系也不能靠同一证据换字段绕过。
- `NeoRetro` 需要至少两族不共享字段证据，并以 `DET-17=历史造型化` 通过表达门；普通泡罩、圆灯、轮圈、结构包边、现代 Logo 或普通控件不能成立该标签。
- 37 个 atomic 标签独立计权；`MysticOrganic` 是唯一零权重 composite，须满足 `requires(any)` 依赖。`TribeIdentity` 已迁移到 `IDG-05/07/09`，身份不占风格名额或 dominance。
- 12 个命名组合预设只由 Python 根据 confirmed 原子标签派生；预设 ID 与活动标签不重名，只写入 `derived_style_presets`，不进入 `style_tags`，也不参与反向补证。
- 模型阶段使用不含派生字段的独立 Schema，Prompt bundle 不含任何预设定义；最终 Schema 要求派生字段存在且与 Python 重算结果完全一致。
- 严格 JSON 读取与保存拒绝 `NaN/Infinity`；证据、字段和风格区域只能来自主体可见区域或 `whole_object`。

## 自动化结果

- Agent Skills 快速规范校验通过；JSON Schema Draft 2020-12 元模式校验通过。
- 服装、单标签手机、双标签手机 3 个完整示例均以 `--warnings-as-errors` 通过 Schema、注册表和语义校验。
- 80 条 JSONL 图像规则评测 ID 唯一且可解析：24 条混淆、19 条通用、5 条多标签、32 条扩展风格正例/边界/反例/共存例；另有 14 条 Python 派生用例覆盖全部预设与误触发阻断。
- 变异门禁可拒绝旧层级字段、废弃标签、低置信风格字段、零规则计数、dominance/排序错误、候选状态错配、缺失标签对、同区冲突、同证据换字段、非法区域及非有限数值；合法的同区独立纹饰共存与冲突降级候选可通过。
- 保存入口可接收不含派生字段的模型 JSON，在最终校验前确定性覆盖写入组合预设；伪造、缺失或过期的最终派生值会被语义校验拒绝。
- 模型 Schema 与知识索引重建一致；Prompt bundle 不含预设规则，共 193,281 字符、243,646 字节，SHA-256 为 `9befa0224af1867237521c4386d9c04a763892e8ddde51edf2ff4b05fb34546a`。
- 包级结构、版本、双 Schema、示例、评测、脚本、索引及 35 个内容文件校验和通过。

## 既有前向盲测基线

- 1.0.0 阶段曾对 `20260831-213714.jpeg` 使用无历史结论上下文的独立执行者重新读取完整 Skill；正式结果首次严格校验即通过，0 error、0 warning。该结果作为兼容回归基线保留，本次未重新调用模型。
- confirmed 标签为 `SaturatedBold`（94 / 0.96 / 0.68）与 `RefinedMinimalism`（82 / 0.84 / 0.32）。前者由大面积高彩红色成立；后者由低信息壳体、细银饰带和规整黑色包边独立成立，二者按 `compatible + cross_region_or_mechanism` 共存。
- `PureFuture` 为 provisional；`NeoRetro`、`FreshJoy`、`KineticEnergy`、`BiomorphicForm` 均 rejected。`DET-17=必要功能结构` 明确阻止通用泡罩、轮圈和包边误触发 NeoRetro。
- 结果包含 59 个规范字段；SHA-256 为 `ae0b54a74507296f5cc72c29347e8c569fc10e3d12fce7fe56d4c7429a3fcb06`。
- 加固前曾出现一次通用组件误触发 NeoRetro；最终校验器现以“缺少两族独占证据”和“未命中 `DET-17=历史造型化`”两项确定性错误拒绝该旧结果。

## 关键命令

```bash
python scripts/validate_skill_package.py
python scripts/build_model_output_schema.py --check
python scripts/derive_style_presets.py model_result.json --output result.json
python scripts/validate_output.py --warnings-as-errors examples/smartphone-rear.example.json
python scripts/validate_output.py --warnings-as-errors examples/smartphone-red-multitag.example.json
python scripts/validate_output.py --warnings-as-errors examples/apparel.example.json
python scripts/build_knowledge_index.py --check
python scripts/build_prompt_bundle.py --output /tmp/multimodal-design-dna-multitag-prompt.txt
```
