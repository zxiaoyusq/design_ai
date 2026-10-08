# 原生品质 / R5 / H2便携接口

先安装包根requirements.txt至使用者选定的Python环境，再运行：

```text
python -B -X utf8 ../prism_skill_support/scripts/native_api.py doctor
python -B -X utf8 ../prism_skill_support/scripts/native_api.py describe --module quality
python -B -X utf8 ../prism_skill_support/scripts/native_api.py describe --module id
python -B -X utf8 ../prism_skill_support/scripts/native_api.py describe --module cmf
```

doctor加载并核对随包pins/原R5归一化，不执行模型。所有call通过--args JSON按关键字传参，并且--out必须不存在。例如：

```json
{"p":{"$json":"prepared.json"},"stage":"primary"}
```

```text
python -B -X utf8 ../prism_skill_support/scripts/native_api.py call --module quality --method build_request --args request-args.json --out native-request.json
```

R5 record转换参数：asset（包含实际image_id、image_path、sha256及来源），result_ref（用$ref登记实际result.json），可选quality_ref。同图字节不同任务ID用alias-r5，原结果不会被改写。

H2 prepare参数：brief_ref、manifest_ref、records、quality_bundles。manifest包含schema_version、dataset_mode、brief_digest、images、units。ID使用prism.id.candidate_manifest.v5，CMF使用prism.cmf.candidate_manifest.v4。brief使用对应visual_brief.v5/v4。

H2调用顺序：

1. prepare：重放上游，得到eligible/pending。
2. grouping_view或grouping_template：准备实际模型/人阅读的候选和字段；模板不是审阅结果。
3. accept_grouping(prepared, proposal_ref)：消费真实提案，检查来源/证据/原否定。
4. prepare_board_review(grouping, rendered_board_ref)：只对合规候选准备整板审阅。
5. board_review_template：提供字段形状；真实审阅者需看整板、原图和视窗。
6. accept_board_review(grouping, request, review_ref)：回放并记录实际结果。

字段的完整约束就在runtime/prism_runtime/clustering/id_reference_board_v5和cmf_reference_board_v4的protocol.py；fixtures.py包含明确synthetic_fixture演示数据。fixtures不能改dataset_mode后冒充真实资料。测试真实模式拒绝合成证据、错图、错来源、错部位、缺负向和未实际阅读等情况。

quality prepare的manifest/selection投影和execution/target_review完整字段，见runtime/prism_sidecars/quality_selected_target_v2/protocol.py和prompt.txt。本地逻辑executor标签为prism-local-executor；它仅满足本地记录一致性，不授予当前模型调用或数据权限。没有当前选择/授权时保留准备状态。

使用alias-id/alias-cmf时，整条prepare/current/group/board链都用该入口，不在中途切回普通消费者。原ID v5、CMF v4判断函数没有因为别名而变松；仍按原图相同字节及正常归一化验证。

两个历史接口的详细说明可按需读[id_reference_board_v5.md](id_reference_board_v5.md)、[cmf_reference_board_v4.md](cmf_reference_board_v4.md)。其中历史案例路径只作来历，不在新电脑执行；本文件与native_api是便携入口。可读性PASS、视觉一致、数量合格、用户认可分别记录。
