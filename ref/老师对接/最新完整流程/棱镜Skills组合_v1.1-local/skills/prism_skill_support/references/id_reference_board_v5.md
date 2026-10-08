# ID 整体参考板 v5

`ID-FRESH-TARGET-V5-001` 第一次有界交付。独立模块版本 `id-reference-board-v5.0.0`，消费原生 `quality_selected_target_v2` 的 `branch=ID / scope_kind=overall_id` 和冻结 R5 的已知 ID 观察。

沿用 CMF v4 的 FileRef、别名、来源去重、数量、完整负向、当前视窗和整板审阅结构，以独立源码实现 ID 范围。旧 CMF v4、ID v3、R5、quality v2 均不修改；没有运行时 monkeypatch，也不把 ID 品质转换为 CMF 或旧格式。来源文件身份见 `source-lineage.json`，运行依赖哈希见 `dependencies.json`。

## 最小 API

```python
from prism_runtime.clustering.id_reference_board_v5 import (
    prepare, grouping_view, grouping_template, accept_grouping,
    prepare_board_review, board_review_template, accept_board_review,
)
from prism_runtime.clustering.r5_dual_v2.adapter import load_record

records = [load_record(asset, original_R5_result_ref, quality_ref=None)]
p = prepare(brief_ref, manifest_ref, records, quality_bundles)
model_input = grouping_view(p)
proposal_shape = grouping_template(p)       # unknown/false 默认值不会自动通过
# Root 负责真正的原图/整体视图评估、模型执行和保存原答复。
g = accept_grouping(p, proposal_ref)
request = prepare_board_review(g, rendered_board_ref)  # 实际板图的 binary FileRef
review_shape = board_review_template(g, request)
result = accept_board_review(g, request, review_ref)
```

函数只读本地输入、验证和返回对象。不会执行模型、联网、获取图片、剪裁、渲染或自动化。用户已经授权的六方向执行由 Root 继续管理；此模块不重新设置执行审批门。整板机器审阅通过仅为 `ready_for_user_feedback`，不冒充用户对当前 ID 结果的认可。

所有 FileRef 是 `{path:本地绝对路径,sha256:原文件字节SHA256}`。用本模块 `common.identity(path)` 取得规范引用。JSON 摘要为 finite canonical JSON；拒绝重复键和非有限数值。已绑定文件改变后，旧 prepared、proposal、视图或板图回执不能继续消费。

## Brief 和候选

所有新协议 schema 均为 `prism.id.<阶段>.v5`，阶段包含 `visual_brief`、`candidate_manifest`、`target_binding`、`view`、`prepared`、`grouping_proposal`、`grouping`、`board_review_request`、`board_review`、`board_acceptance`。

Brief 必须显式 `branch:"ID"`、`comparison_unit:"whole_object"`。其余结构延续 v4：`brief_id`、`direction_id`、已确认 `h01_ref/h01_pointer`、必要时完整方向的 `direction_evidence:{ref,pointer}`，主导整体形态/构造条件 `primary_signature`，`secondary_dimensions`，`allowed_variation`，`confounders`，只供校准的 `calibration_refs`，`count_policy`，完整 `negative_audit/deferred_obligations`、`scope_limits`。H01 选择只有方向 ID 时，使用 `audit_evidence` 分别指向完整原数组，逐字核对。不会因旧 H01 派生索引的图片集合而限制新目标池。

`count_policy` 显式约 10 个来源，本入口要求 `minimum >= 10`，常用 `target:10,minimum:10,maximum:12`，附原始 `basis`。不因为缺图改小最低数。品类没有配额。

Manifest 结构是 `dataset_mode:"real"|"synthetic_fixture"`、`brief_digest`、`images[]`、`units[]`。image 行和 v4 一致：`image_id/image_ref/pixels/source_kind/source_role/source_status/source_group_id/provenance_refs/dedup_keys`。候选来源允许 `trend`、`public_design_reference`，来源需 established；同 source group、article/project/series/product 去重键或 image SHA 每板 max1。校准原件和保留校准祖先引用的派生图不会入组。来源关系需由 Root 如实提供，本模块没有感知哈希或自动溯源能力。

unit 保留 `unit_id/image_id/target_ref/endpoints/target_binding_ref/view_ref`，新增显式整体目标声明：

```json
{
  "target_declaration": {
    "kind":"single_object",
    "object_ids":["primary"],
    "selected_scope":"逐字复制原生 target.selected_scope",
    "description":"实际选定的整件目标及边界",
    "excluded_objects":["邻近物件"]
  },
  "endpoints":[
    {"endpoint_id":"body","role":"整体轮廓","original_at":"原R5部位文字",
     "target_object_ids":["primary"],"observation_ids":["确切原观察ID"]},
    {"endpoint_id":"support","role":"构造关系","original_at":"另一原R5部位文字",
     "target_object_ids":["primary"],"observation_ids":["另一确切原观察ID"]}
  ]
}
```

`single_object` 只声明一个对象；`explicit_ensemble` 至少两个。`object_ids/target_object_ids` 是本次实际审阅中的目标成员标签，**不是 R5 新生成的对象树或物理身份**。所有端点的对象归属必须属于声明，且共同覆盖声明对象。组合关系端点可以列多个成员，但原 `at/value/source/path` 仍不动。R5 一个原部位只建一个端点，不把它复制为多个物件属性。

## 原生品质与 ID 事实

`target_ref` 是 `quality_selected_target_v2.prepare(...).target` 原样存盘。`quality_bundles` 直接使用 `prism.selected_target_quality.bundle.v2`，包含 `image_id/branch/source_kind/target_ref/target_digest/prepared_ref/execution_ref/target_review_ref/previous_result_ref/result_ref/producer_ref/producer_version/dataset_mode`。primary 的 `previous_result_ref=null`。本消费者重放原生 `accept` 并逐字比较 native result；如果有前一轮 primary，也重放验证。`clustering_view` 不是 native result 的替身。

进入 eligible 需同图、同源、同 H01/方向/完整负向、同 target、`ID/overall_id`，且新原生 `status=complete,decision=PASS,admissible=true,validated_target.target_scope_verified=true`。缺评估保持 pending；wrong image/branch/target 或篡改结果拒绝。fresh 不需要旧全图品质调用，旧回执不赋予新目标资格。

R5 按冻结 producer 的 `views` 和 `record_role` 读取 ID 观察。允许原生同时属 ID/CMF 的结构/关系参数，拒绝仅 CMF 的色值；pending、invalid、非特征、冲突值或纯引用不能支撑分组。保留全部原记录和未知项；`grouping_view` 同时展示未选作依据的原始不确定性。主条件可以使用不同 PID，但每个声明端点必须有明确的已知原观察支撑；相同文字或数值不产生整体视觉 PASS。

## 原图目标绑定与整体视窗

`target_binding` 延续 v4 的精确绑定：`unit_id/image_ref/target_ref/endpoints/record_digest/quality_result_digest`，加完整 `target_declaration`、`original_image_seen`。

`endpoint_reviews[]` 每条需原 `endpoint_id/original_at/observation_ids`，`confirmed_object_ids` 等于相应端点 `target_object_ids`，`selected_target_match:true`、`same_declared_target:true` 和具体 `reason`。错误部位不能靠整体 ID 标签合并。

新增必需的 `overall_target_review`：

```json
{
  "visibility":"whole_readable",
  "same_declared_target":true,
  "whole_shape_relations_readable":true,
  "distinguished_from_other_objects":true,
  "confirmed_object_ids":["primary"],
  "ensemble_relation_visible":null,
  "ensemble_relation_description":null,
  "reason":"实际原图中整体与关键构造如何可读"
}
```

ensemble 时最后两个关系字段必须分别为 true 和非空描述。`local_only/partial/unreadable/uncertain` 或缺实际确认保持 pending；原生 target 标为 overall_id 不绕过这一门。

`view` 保留精确 `unit_id/image_ref/target_ref/endpoints/pixels/original_image_review_ref`，加完整 `target_declaration`。`rectangle` 为原图归一化坐标，`coordinate_frame=original_pixels_no_rotation`，`transform` 只能 crop_only_no_retouch 或 crop_and_uniform_resize_no_retouch；Root 提供现存 `actual_view_ref`，保留原图。另需 `confirmed/original_and_view_match/reason/limits` 和：

```json
{"overall_view_review":{
  "visibility":"whole_readable",
  "whole_declared_target_visible":true,
  "whole_shape_relations_readable":true,
  "confirmed_object_ids":["primary"],
  "reason":"当前显示视图保留整个声明目标及必要形态关系"
}}
```

允许裁去背景；不会用矩形面积推断整件是否可见。整体可读性来自绑定到原图和实际视图的审阅。这里仅读图片尺寸与文件身份，不修改图片，也不声称已经做视觉感知。

所有实际审阅附 `review_provenance:{actor_kind:"human"|"model",actor_id,source_ref,inspected_refs,basis}`。source_ref 是已保存的真实审阅记录/模型执行与输出证据 JSON；inspected_refs 覆盖所需原图、当前视图和板图。哈希验证可证明引用一致，不能证明操作者真的看过图；Root 负责保存真实回执并独立审阅。real 模式拒绝 synthetic 标记。

## 分组与整板

沿用 v4 同名函数和短别名（U01 / U01.E1 / U01.E1.O01）。原图身份、声明对象、原始 at/值和完整原 ID 可逐项反查；未知或跨 unit 别名拒绝，不修复猜测。所有 eligible 单元必须分到 members 或 excluded_eligible，程序保留其余 pending/context/calibration 账本。

完整负向逐条处理：当前冲突/未决阻断；未来产品义务保留未解决状态和原义务引用，不能被删除或假称解决。提案通过只到 `candidate_for_board_review`，`visual_pass=false`。

整板 request 绑定实际板图字节、按成员顺序的 tile_index、原图、view、target、端点和整体声明。模板默认均为 false/unknown。每张 tile 新增 `whole_target_visible`、`whole_shape_relations_readable`；全局新增 `whole_ID_not_local_or_color_only`。通过需实际逐图/整板复核，不能靠品质 PASS、数量或 PID 匹配代替。

## 验证与自评范围

`build_delivery.py` 用已有 workspace Python、Pillow 和 R5 jsonschema vendor 执行本模块边界测试，只写本 owner 的 `ID-FRESH-TARGET-V5-001` 交付目录。没有安装依赖或模型调用。脚本提供 `synthetic-example/inputs.json`、完整原生 ID 品质 fixture、单物/组合声明、target binding、whole view、提案和整板回执作为最小可重放格式例子。所有图像字节是 1px 合成测试常量，不是生成或渲染的真实样张。

结果仅证明协议边界与原生回放兼容性。未评估真实 ID 聚类准确率、六方向结果、实际板图或用户偏好。旧模块前后字节校验和依赖哈希随 handoff 保存。Root 继续负责真实输入、实际运行和结果判断。
