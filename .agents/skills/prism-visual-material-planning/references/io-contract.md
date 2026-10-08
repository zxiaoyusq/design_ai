# 视觉转译与选材：输入、输出和交接

这是业务入口的资料包说明，不替代同事 v2 原生 JSON schema；本地 FileRef 必须引用当前真实字节和 SHA256，JSON pointer 单独登记。

## 输入

| 输入 | 用途和必要边界 |
|---|---|
| 项目合同 | run_mode、输出目录、branch、最终数量和候选容量、当前执行预算/授权；模型暂停不因合并解除 |
| H01 原结果与当前 selection | direction_id、双侧证据、完整原 negative_audit/deferred_obligations、实际选择身份；不能捏造 confirmed H01 |
| 设计背景与设计师参考 | 语义转译依据、role_shape/output_materials 等声明范围，区分参考判断和已证实用户偏好 |
| 趋势文章与图片清单 | article_id、语义成员归属、来源 URL / 图片 URL、图序、已有本地文件信息 |
| 可选已有 DNA | result_ref、版本、观察 ID、原 at、已知/未知/pending/invalid，用于候选发现和覆盖检查；不授予视觉或品质通过 |

visual_trial 允许使用其明确选择的视觉探索范围，但须说明 H01 未执行；不能把探索配置冒充正式 H01 选择。

## 输出

| 输出 | 内容 |
|---|---|
| visual-family / material-brief | direction_id、branch、comparison_unit、primary_relation、required_evidence、allowed_variation、confounders、comparison_scale、scope_limits、calibration_refs；原 H01 证据/负向/义务引用 |
| count_policy / candidate_pool_policy | 最终板 target/minimum/maximum/硬门与候选容量分别登记；本项目最终 10 张/10 独立项目，未知项目不能算已核实 |
| metadata-pool | 文章主成员或扩展参考身份、召回理由、原始 URL、图序；扩展不篡改原趋势归属 |
| original manifest | 每图 image_id、article_id、source_group_id、FileRef、SHA、像素、原图片 URL、可核实 project/series 及 identity_basis |
| material-plan | current_target、comparison_scope、primary_relation_evidence、secondary_signal、rectangle、treatment、reason、原像素、实际阅读者/时间和 read_trace_ref；原 DNA 观察与位置引用 |
| 冻结候选池与准备回执 | 条件/候选版本、文件 SHA 和冻结时点、供给容量、全候选去向、findings；只标 prepared，不标视觉 PASS |
| gaps / unresolved | 来源项目不明、缺更清楚原图、像素/证据不足、scope_gap、容量不足、尚未完成和失败分开记录 |

处理动作沿用 keep_whole、crop、display_enhance、request_clearer_source、evidence_pending、exclude_for_family。原关系不清楚不能用展示增强解决；exclude_for_family 不表示图片本身无价值。

`material_plan.py` 的 material-brief 至少使用 branch、comparison_unit、direction_id、primary_relation、required_evidence、allowed_variation、confounders、scope_limits、count_policy、candidate_pool_policy、frozen_before_final_selection。逐图 items 字段与共享 material-contract 对齐。校验输出包含 brief.frozen.json、materials.frozen.json、summary.json；summary 的 visual_PASS_awarded 为 false。业务资料包另外保留读取记录、版本时点和其他正式引用，不能把本地 validator 没检查的项目宣称已验证。

## 交接和回退

通过供应校准后，把冻结条件、候选 manifest、来源和处理计划交 `prism-dna-sol-r5` / `prism-reference-image-preparation`。已有 DNA 缺当前对象或区域，交 R5 补足其授权范围并保留原结果，不擅自改 supported。

之后换目标、扩大比较区域或修改家族条件，生成新版本；回传受影响材料复核。供给不足只能记录未完成或作一次明确上游决策，不能无限召回、改旧标准凑通过。
