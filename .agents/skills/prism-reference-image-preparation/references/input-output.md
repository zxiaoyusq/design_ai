# 单图参考准备：输入与输出

这些字段组织一个单图任务，不替换原生 R5、quality 或 H2 数据结构。文件引用均保留可解析路径、SHA、必要 JSON pointer；原图字节、回执与原答复保持可追溯。

## 输入

| 输入 | 内容及用途 |
|---|---|
| `material_brief_ref` | 冻结的方向、ID/CMF 分支、比较单位、主关系、必要证据、允许变化、干扰项、限制、H01 负向与义务；不能在此为保留候选改变标准。 |
| `material_plan` | 单图 image_id、当前对象/状态、比较部位、拟议 ROI、处理动作、独立项目来源及身份依据；附原 article/project/source_group 信息和图片 URL（若来源提供）。 |
| `original_ref` | 原图路径、SHA、原像素；用于所有判断的共同图片身份。 |
| `r5_result_ref`、`r5_arguments` | 冻结 R5 的原结果和 `load_record` 参数，含原模型/规则/Prompt/执行时间和原答复引用。平面 at 与 pending/invalid 原样保留。 |
| `known_observations` | 当前拟使用的 observation_id、原 value、原 at、原 source，不取图级索引冒充同部位共现。 |
| `existing_quality_bundle`（可选） | 已有品质的真实输入、答复、target_review、accept 参数、目标 digest 和覆盖范围；只复用同字节、同目标且真实覆盖的部分。 |

## 输出

建议将本次业务包保存为 `reference-material.json`；这是容器文件名，并非新的原生算法格式。每图分开保存以便局部修复。

| 字段 | 内容及用途 |
|---|---|
| `image_id`、`direction_id`、`branch` | 与冻结输入一致的图片、方向和分支身份。 |
| `target_binding` | current_target、quality_parent_scope、comparison_scope、对象状态；每条 observation 的原值/at/source 及当前对象归属。 |
| `quality_bundle` | 原生 prepared、target、execution、target_review、result、producer_ref/version，保留 accept 参数、原输入、原答复及限制；admissible 只能来自原生验收。 |
| `comparison_view` | 真正生成的裁片或可逆显示视窗、原图引用、ROI、原像素和实际显示尺寸，及 actual_view_ref。ROI 计划不是实际裁片。 |
| `crop_review` | 独立阅读者/上下文与真实执行回执，明确原图及实际视窗已读、主关系是否突出、干扰/反证、ID 整体或 CMF 同表面/同物件界面条件；保留失败和 unknown。 |
| `provenance` | 原图片 URL 及来源、项目/系列身份依据、原图/R5/brief/品质/裁片/审阅 refs。无远程 URL 不造地址。 |
| `action_log` | 实际 keep_whole/crop/display_enhance/request_clearer_source/evidence_pending/exclude_for_family 动作、原因、前后版本、时间、执行者、工具/参数/回执。 |
| `candidate_eligibility` | `ready_for_grouping`、`pending` 或 `excluded_for_family`，附实际验证结论和原因；不授予 H2/整板 PASS。 |
| `gaps` | 区分 scope_gap、target_mismatch、relation_unclear、pixel_gap、presentation_issue、source_gap；指向需要补做的环节。传输失败单列，不当图片内容 FAIL。 |
| `display_variant_ref`（可选） | 仅展示的增强版本，保留方法/工具/参数和实际回执、变更审阅。不能成为原始证据。 |

`ready_for_grouping` 只在当前原生品质 admissible、已知观察确实覆盖声明范围、原图与真实视窗独立复核完成时登记。仍可能在 ID/CMF 选组或整板阶段被否决。

## 现有工程离线验收的原生投影

调用 `backend/app/services/visual_workflow/colleague_v2.py::validate_target_material(material, brief)` 时，从上述业务包机械投影以下现有字段；不通过新写布尔值制造审阅：

- `material`：`original_ref`、`actual_view_ref`、`view_review_ref`、`brief_ref`、`r5_module`（r5 或 alias-r5）、`r5_arguments`、`observation_bindings`、`quality_arguments`、`quality_target_digest`。
- `view_review_ref` 对应的实际 JSON：`original_ref`、`actual_view_ref`、`brief_ref`、`review_kind`（human 或 ai_independent_context）、`reviewer_actor`、`original_image_seen`、`actual_view_seen`、`primary_relation_prominent`、`confounders_controlled`、`evidence_derived_from_enhancement`；ID 附 `whole_target_visible`，CMF 附 `same_surface_or_same_object_interface`。
- `observation_bindings` 必须引用 R5 已知 observation_id，并逐条保留原 `value`、`at`、`source`。缺失范围交回 R5 定点补查；不能靠本地字段修补原结果。

该入口重放原生 R5 和品质、验引用及真实裁片审阅链，不发模型请求；返回的 `valid` 只表示这条链可用于后续选组，且 `visual_pass_awarded` 仍为 false。下游原生 H2 必须继续执行自己的 prepare、accept_grouping 与整板审阅。
