# 选材与原图处理合同 4.3

brief保存direction_id、research_level、branch、research-binding ref、design_language、design_emotion及其可见依据、必要关系、容许差异、核心冲突、原型图与邻近方向区别。count_policy与候选池覆盖分开登记。

每张候选：image_id、original_ref、article_id、source_group_id、已知project_id及依据、原语义父簇、visual_extension状态、current_target、comparison_scope、归一化rectangle、图中证据位置、独立维度及联合情绪、会抢主题的信号、保留/换图/待定与原因、实际读图记录。DNA ref与新观察分开。

处理以keep_whole/crop/request_clearer_source/evidence_pending/exclude_for_family为主。当前原图约束不做生成式增强或调色。旧material_plan保留display_enhance字段供历史复验，不代表新任务授权。裁切不能把硬椅子变成软椅子、把薄片隐藏成实体厚壳。

候选不足时补授权来源或保留未成板。少于8张不标合格，不把背景、同图裁片或同系列变体计成独立项目。人物与跨品类找能共同支持关系的图，没有合适图如实报告缺口。

`material_plan.py`复用旧ID/CMF基础brief与候选结构检查；它要求显式正整数目标，不接受尚未决定的候选数量。未冻结数量时先留草案，不为调用程序虚构数目。总体风格成板用[style-board-contract](style-board-contract.md)额外核对语义与可见关系。
