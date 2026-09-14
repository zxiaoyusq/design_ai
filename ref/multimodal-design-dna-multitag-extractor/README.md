# Multimodal Design DNA Multitag Extractor

面向单图、单主体的扁平多标签设计 DNA 提取 Skill。它先提取可观察 DNA，再输出有真实视觉支持的风格候选，并由程序派生组合预设。

它与原 `multimodal-design-dna-extractor` 并存，不替换原版：普通设计 DNA 请求继续使用原版；只有用户点名本 Skill，或明确要求“扁平、多标签、无主次、组合风格”时使用本版。

## 关键约束

- 每次只处理一张图片并选择一个主物品。
- 风格是同层稳定 `style_id`，不输出一级/二级或主/次风格。
- `style_candidates` 保存 0～5 个有可见支持的同层候选，不再输出确认/未分类状态。
- 每个候选保留匹配度、置信度、适用区域、主要支持与主要冲突。
- 候选严格按 `(-match_score,style_id)` 排序；所有区域值均来自主体 `visible_regions` 或 `whole_object`。
- 当前有 38 个活动标签：37 个 atomic 参与相似检索，只有 MysticOrganic 为零权重 composite。
- 组合预设不交给模型判断；Python 仅根据候选 ID 确定性写入最终 `derived_style_presets`。
- 模型只输出视觉与语义观察；Python 从注册表补全静态元数据、排序和统计。
- 证据已有明确区域、有效坐标和可见描述而主体清单漏登记时，Python 只同步这个已有区域，不要求模型重生成结果。
- 合法 enum 的单键 `label` 包装由 Python 校验值域后展开；证据框与主体框每边不超过 0.05 的取整偏差由 Python 合并，更大的越界继续交给严格校验。
- 最终模块路径通过编译报告映射回精简观察路径；局部补证无效时保留原始问题，并保守移除无法闭环的低置信推断观察。
- `facet_ids` 只用于后台导航；TribeIdentity 已废弃，身份只写入 IDG-05/07/09，不再生成风格标签。
- 规范 DNA 继续约束 profile、必要视角、派生依赖、值域和证据状态。
- 单图只描述视觉材质候选，不断言真实成分、工艺或随角变化。
- JSON 禁止 `NaN` 和 `Infinity`。

## 主要资源

- `SKILL.md`：任务边界与核心流程。
- `references/design-dna-knowledge-base.zh-CN.md`：风格与规范 DNA 定义。
- `references/style-registry.json`、`references/tag-relations.json`：扁平标签及其组合关系。
- `references/style-evidence-rules.json`：宿主专用的值级证据挂接规则与语义复核边界。
- `references/model-reference-bundle.json`：模型一次读取的精简候选、allowlist 与关系索引。
- `references/style-combination-presets.json`：宿主专用的组合派生与查询规则。
- `references/field-registry.json`：规范字段机器表。
- `references/value-normalization.json`：宿主专用的显式别名、关系词与离散刻度归一化规则。
- `references/extraction-protocol.zh-CN.md`：完整执行协议。
- `references/output-contract.zh-CN.md`：输出语义约束。
- `schemas/design-dna-model-output.schema.json`：精简模型观察结构。
- `schemas/design-dna-output.schema.json`：包含 Python 派生字段的最终结构。
- `scripts/compile_model_output.py`：把模型观察编译为完整结果骨架。
- `scripts/derive_style_presets.py`：确定性写入组合预设。
- `scripts/validate_output.py`：Schema 与语义校验。
- `evals/`：单标签、多标签共存、冲突和通用回归。

## 使用

向宿主提供恰好一张图片。Agent 返回精简观察 JSON；宿主必须先编译完整结构、派生组合预设，再校验或保存最终 JSON。

高频宿主可将 Skill、协议、模型参考包、知识库与模型 Schema 组合成稳定系统前缀，以利用 provider Prompt Cache 并避免逐文件工具调用；未预装时仍按 `SKILL.md` 的加载顺序执行。

```bash
python scripts/compile_model_output.py model_observation.json > compiled_result.json
python scripts/derive_style_presets.py compiled_result.json --output result.json
python scripts/validate_output.py result.json
python scripts/validate_skill_package.py
```

不原生支持 Skill 的宿主可生成完整上下文：

```bash
python scripts/build_prompt_bundle.py --output prompt_bundle.txt
```

## 版本

- Skill：`2.0.0`
- 输出 Schema：`design_dna_multitag_extraction_v1.2`
- 设计 DNA 知识库：`4.1`

本 Skill 独立维护，不依赖外部 Excel 或旧 Skill 运行时。

## 宿主脚本维护

- `compile_model_output.py` 编排观察展开、字段整理、候选整理与源路径报告；具体字段和风格逻辑分别位于 `compile_fields.py`、`compile_styles.py`。
- `validate_output.py` 保留原命令行与公开校验函数，按主体/字段和候选调用 `validate_fields.py`、`validate_styles.py`；基础注册表契约位于 `validation_rules.py`。
- 编译与校验统一使用 `dna_rules.py` 解析知识库值域和视角准入，避免同一规则出现不同解释。
- `validate_skill_package.py` 负责包检查编排；静态 Schema/注册表检查位于 `package_checks.py`，行为回归测试位于 `tests/`。包自检包含这些测试，且主进程与子进程均不生成字节码文件。

后端已取得编译结果和报告时，使用以下入口只派生组合预设、严格校验并保存；不得再次归一化已编译字段。默认保存入口继续支持未编译输入。

```bash
python scripts/save_result.py --compiled --image original.jpg compiled_result.json
python -B -m unittest discover -s tests
```
