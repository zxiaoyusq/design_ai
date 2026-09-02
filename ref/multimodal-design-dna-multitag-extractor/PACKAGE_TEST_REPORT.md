# Package Test Report

测试日期：2026-09-02

## 结论

`multimodal-design-dna-multitag-extractor` 1.6.3 已完成字段准入、受控值归一化、低置信镜像重建、证据区域声明同步、值级风格证据自动挂接、窄范围语义复核、弱引用裁剪与重新闭环、结构化源路径诊断及完整回归评测。它继续独立维护，不替换或修改原 `multimodal-design-dna-extractor`。

## 结构基线

| 项目 | 结果 |
| --- | ---: |
| 输出 Schema | `design_dna_multitag_extraction_v1.1` |
| 模型观察 Schema | `design_dna_multitag_observation_v1` |
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
- 模型阶段使用精简观察 Schema，不再输出字段/风格静态元数据、模块清单、统计值、排序、confirmed 候选镜像及可推导证据并集；最终 Schema 保持 v1.1，并要求派生字段与 Python 重算结果完全一致。
- 模型在确定视角与 profile 后只提取字段准入集合中实际可观察、风格需要或用户关注的项目；宿主再次过滤必要视角和 profile 不满足的字段。
- confirmed 模型观察可省略规则计数及 core/auxiliary 命中；宿主先以值级规则自动挂接，歧义项只向独立 DeepAgent 提交当前风格知识段落和每角色最多 6 个强字段，不重复传图片或完整 Skill。
- 显式字段值别名、合法 enum 的单键 `label` 包装、关系描述中的标准关系词和规定的 0/25/50/75/100 离散刻度由宿主归一化；不能无损归一化的受控值转为未知，而不是猜测。
- 低置信 `uncertainties` 携带自身可观察性、置信度和证据；宿主可生成缺失的低置信设计字段，并根据最终字段状态重建不确定项镜像。
- 高置信且有已观察最佳估计的记录若误入 `uncertainties`，宿主会在模型 Schema 校验前提升为普通观察；无可确认估计时只保守调整到不确定阈值。
- 有效证据已经提供区域、主体框内坐标与可见描述而 `visible_regions` 漏登记时，宿主只同步该已有区域；证据仍映射到原模型 JSON Pointer，编译器不根据字段名生成区域。
- 证据框相对主体框每边不超过 0.05 的坐标取整偏差由宿主吸收；更大的越界不做修正并继续由最终校验拒绝。
- 风格命中由宿主按 decisive/auxiliary allowlist 重分类；额外弱引用只退出风格证据链，设计字段与不确定项继续保留。裁剪后缺少可用决定字段、独立辅助、区域证据、规则闭环或特殊硬门槛的 confirmed 标签才降为 provisional。
- 严格 JSON 读取与保存拒绝 `NaN/Infinity`；证据、字段和风格区域只能来自主体可见区域或 `whole_object`。

## 自动化结果

- Agent Skills 快速规范校验通过；JSON Schema Draft 2020-12 元模式校验通过。
- 服装、单标签手机、双标签手机 3 个完整示例均以 `--warnings-as-errors` 通过 Schema、注册表和语义校验。
- 80 条 JSONL 图像规则评测 ID 唯一且可解析：24 条混淆、19 条通用、5 条多标签、32 条扩展风格正例/边界/反例/共存例；另有 14 条 Python 派生用例覆盖全部预设与误触发阻断。
- 变异门禁可拒绝旧层级字段、废弃标签、低置信风格字段、零规则计数、dominance/排序错误、候选状态错配、缺失标签对、同区冲突、同证据换字段、非法区域及非有限数值；合法的同区独立纹饰共存与冲突降级候选可通过。
- 保存入口可接收精简观察 JSON 或已有完整结果，在最终校验前统一执行幂等编译并覆盖写入组合预设；伪造、缺失或过期的最终派生值会被语义校验拒绝。
- 双标签手机样例转换为精简观察后，紧凑 JSON 从约 16.3 KB 降至约 8.9 KB，减少约 45%，编译后的最终结果仍通过完整 Schema、注册表和语义校验。
- 两组历史失败已转换为确定性回归：第一组覆盖必要视角、profile、关系值、枚举、序数和低置信镜像；第二组覆盖字段别名、风格 allowlist、缺值及区域证据；另新增 SaturatedBold 自动挂接、RefinedMinimalism 窄范围复核和证据区域漏登记回归，编译结果均通过最终 Schema 与语义校验。
- 弱引用回归证明额外低置信字段不会拖垮已闭环标签，同时 NeoRetro 缺少 `DET-17=历史造型化` 时仍会降级，裁剪不能绕过特殊硬门槛。
- 编译报告保留最终校验路径到模型观察 JSON Pointer 的映射；应用失败追踪保存完整结构化问题，便于定位原始字段或风格观察。
- 最终模块/元素 Schema 路径也映射到精简观察；修复响应格式错误或补丁路径无效时保留原始问题，使保守整理仍能删除无法闭环的低置信推断字段。
- 模型参考包以一次读取覆盖 38 个活动候选、192 个字段类型和 54 对显式关系；完整注册表继续作为宿主编译与校验权威。
- 模型 Schema、模型参考包与知识索引重建一致；Prompt bundle 不含组合预设及宿主值级证据规则，共 143,268 字符、194,021 字节，SHA-256 为 `38068dff7203c56b0f680152278f37a1d650952500fcdc3723a5cd279061f63c`。
- 包级结构、版本、双 Schema、示例、评测、脚本、索引及 41 个内容文件校验和通过。

## 应用链路实测

- 1.4.0 阶段使用 `claude-opus-5-20260820` 复测 `20260901-165929.jpg`：1 次 Agent 执行、2 次内部模型请求，未触发语义补丁、完整重生成或安全降级，最终严格校验通过。
- 同模型复测 `20260829-163949.jpg`：风格 allowlist、引用字段缺值和区域证据问题均由宿主重分类/降级后通过；实测发现并随后修复“高置信记录误入 uncertainties”仍触发局部补丁的问题，已增加无需模型修复的确定性回归。
- 使用 `claude-opus-5-20260820` 对 `folder-phone-a.png` 完成真实图片多模态 DeepAgent 提取，生成 `20260902_020814_folder-phone-a_design_dna.json` 及业务视图，最终严格语义校验通过。
- 使用 `gpt-5.6-terra-20260820` 对省略证据链的 RefinedMinimalism 观察执行真实窄范围复核：独立 DeepAgent 仅调用 1 次模型，输入 3130、输出 431 token，补挂 `DEV-03+DEV-05` 决定组合与 `CMF-07` 辅助证据后恢复 confirmed，并通过最终严格校验。
- 使用 `20260829-163949.jpg` 的既有规范字段重放原 SaturatedBold 缺辅助证据场景；宿主从 `CMP-13=[色相,明度,材质]` 自动挂接辅助证据，无需语义复核即恢复 confirmed，派生与最终严格校验均通过。
- 诊断 `20260902_085729_432730_725e648a` 的原模型观察已离线重放；宿主从完整的 `EV-03` 证据同步 `wheel_contact` 到可见区域，未调用模型即通过派生与最终严格校验。
- 诊断 `20260902_094823_169638_5b82cd4e` 的 `IMG-08` 单证据场景已重放；错误补丁不再覆盖原问题，移除该低置信观察后其余结果通过最终严格校验。
- 诊断 `20260902_125932_756377_781f3477` 的原模型观察已重放；宿主无模型展开 18 个合法枚举包装，并将主体框扩至相差 0.05 的有效证据边界，最终 Schema 与语义校验通过且无 warning。
- 工程后端 59 项自动化测试及前端 TypeScript 生产构建通过。
- 结果包含 69 个规范字段、4 个不确定项及 5 个完整候选，确认标签为 `NordicCalm`；模型输出协议为 observation v1，最终协议保持 multitag extraction v1.1。
- 文件读取式 v3 Agent 的追踪显示：3 次 Agent 执行、19 次内部模型请求、约 164 万总 Token。该数据推动 v4 将 147,696 字符的稳定 Skill 上下文预装为可缓存系统前缀，避免逐文件工具调用；受网关限流影响，预装模式未重复进行昂贵的真实推理，已由系统提示构造和自动化测试覆盖。

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
python scripts/build_model_reference_bundle.py --check
python scripts/compile_model_output.py model_observation.json > compiled_result.json
python scripts/derive_style_presets.py compiled_result.json --output result.json
python scripts/validate_output.py --warnings-as-errors examples/smartphone-rear.example.json
python scripts/validate_output.py --warnings-as-errors examples/smartphone-red-multitag.example.json
python scripts/validate_output.py --warnings-as-errors examples/apparel.example.json
python scripts/build_knowledge_index.py --check
python scripts/build_prompt_bundle.py --output /tmp/multimodal-design-dna-multitag-prompt.txt
```
