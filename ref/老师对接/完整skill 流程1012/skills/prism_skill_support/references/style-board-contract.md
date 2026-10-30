# 总体风格成板数据合同 4.3

这是当前风格层的本地交接格式，不是伪造的原生H2对象。用研、视觉、解析、工程及真人反馈仍分别判断。

## board.v4.json

必需字段：

- schema_version=`prism.style-board.v4`；run_mode=`visual_trial/end_to_end/historical_replay`；research_level=`overall_style/element`；branch=`ID/CMF/ID_CMF`；originals_only=true。
- design_language：core_relationships、allowed_variation、core_conflicts为非空文字列表，emotion_hypothesis为文字。维度要独立且图中可见；没有“几维自动通过”。
- count_policy：minimum/target/maximum为正整数且有序。当前minimum为8；新用户明确修改时保留user_override_basis。不足交候选，不降低政策。source_policy中one_per_article及one_per_known_project=true；runway_max_fraction默认null，有明确当期限制才填写比例及runway_policy_basis。
- research_binding_ref：当前绑定文件的path/sha256。
- native_status：H01/H2分别为not_executed/pending/failed/executed。executed必须另给native_H01_ref/native_H2_ref，是否真正成功仍由相应原生校验器核对。
- tiles：每图image_id、article_id、source_group_id、project_id（未知null）、project_identity_basis、original_ref、rectangle、comparison_scope、semantic_relation、visual_evidence、product_design_use、source_role（semantic_member/visual_extension）、semantic_parent_ids、image_kind（photo/concept_render/unknown）、observations、analysis_status、runway_status。observations每项dimension/location/visible_evidence；实际阅读记录用actual_image_read_ref；已有DNA用DNA_ref，否则保留未做/已有人工或当前助手解析状态。

original_ref保留完整图。board中coordinate_space固定声明为display_oriented：rectangle为原图按EXIF显示朝向后的归一化x/y/width/height。带旋转/翻转元数据的图片使用显示尺寸，原字节仍保持不变；旧原像素坐标不能直接冒充显示坐标。FileRef可用当前绝对路径，便携示例可用相对当前JSON文件的路径；工具按原SHA核对，缺文件不猜。

## research-binding.json

status为bound/partial/missing，三个状态都必须真实。包含research_evidence、trend_evidence、upstream_refs、negative_audit和deferred_obligations列表。无否定时填写negative_audit_basis说明核对范围，不能默默丢弃否定。

research_evidence每项保留unit_id、person_id、object_scope、full_text、准确quote子串、attitude、source_ref及可选pointer；必须原样继承上游evidence_kind（例如document_excerpt/transcript_excerpt/analyst_notes）、kind（例如selected_board_reason/brand_preference_or_impression/personal_identity_goal/elicited_concept_image_example/reference）和text_kind（original_text/source_paraphrase/analysis_note/unknown）。未知写unknown并保留partial，不为适配字段把品牌印象或举例改成直接偏好；claimed_direct_preference仅用于有真实直接偏好通道支撑的项。确为文档原句但并非逐字录音时evidence_kind仍是document_excerpt。trend_evidence每项保留parent_cluster_id、article_ids、text_kind（original_text/source_paraphrase/analysis_note）与source_ref。upstream_refs指向未经改写的原绑定/选择/负向记录，供实际复查；不是将摘要替换原始依据。

如果来源只有摘要，或只是视觉延展且语义未核，保留partial并交待缺口。语义原文真实性、引用支持程度、否定适用性仍需人/助手实际审阅；字节检查只防止无意换了文件。

## 原图编排

`render_style_board.py`需要canvas（width/height/background十六进制色）和每图layout（画布像素x/y/width/height）。ROI的原像素宽高比须与layout相符，工具拒绝拉伸。texts每项text、x/y/width/height、font_size、bold及color，位置都在板内。

不固定网格。逐图设计主次、留白、人物位置和裁切，实际打开两版HTML核对。纯图版省略所有text；沟通版显示标题与短说明，不能依赖文字补成视觉一致。

## 命令

从共享scripts目录执行，或改用脚本绝对路径：

```text
python -B -X utf8 style_board_check.py --board board.v4.json --out mechanical-check.json
python -B -X utf8 render_style_board.py --board board.v4.json --out rendered
```

前者返回machine_contract_valid和mechanical_requirements_met，明确不颁发审美PASS。后者生成内嵌真实原图的双版HTML、source refs及receipt，不会补造来源或视觉评审。

工程演示由包根`tools/demo_style_contract.py --out 新目录`创建，所有文字与色块标为synthetic_fixture，只测试数据衔接和排版；不冒充真实情绪板或用户研究。
