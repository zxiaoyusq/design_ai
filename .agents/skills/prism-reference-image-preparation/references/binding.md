# 棱镜｜DNA位置与当前对象绑定

输入原图、材料计划、R5结果、视觉brief及已有品质范围；输出target_binding、候选manifest、视窗计划。先读 [R5到原生H2合同](../../prism_skill_support/references/contracts.md)。

原R5采用平面at位置，不能假装已经有对象树或准确bbox。用native_api的r5/load_record复验原结果、字节和规则；同字节不同任务ID只能走alias-r5，不改原结果身份。

实际读原图，把本次要用的每条观察绑定到它自己的observation_id、原值、原at和图SHA。图级去重索引不能证明条件在同一部位共现。未输出、pending、invalid及unknown不当已知，也不能把结构字段伪装成纹理字段。

ID明确single_object或真实explicit_ensemble及当前状态，保留主轮廓/比例/主要结构。CMF明确surface或same_object_interface；界面必须同属当前对象且真实相邻。载体、表面和图像背景分开。

保存quality_parent_scope和comparison_scope：父品质可覆盖整件，实际CMF只比较其一部分；不能强迫裁片展示父范围所有部件，也不能把别的物体的品质通过继承过来。换目标、换状态或补图时重做受影响绑定与品质。

ROI按原图归一化x/y/width/height，留原像素和预期显示大小；缺少当前范围观察时交回DNA补查，不能仅改标签。实际裁片按本入口的 [裁切规范](crop.md) 生成，再与原图独立核对。

原生prepare的品质依赖按合同保留：可先做预绑定，再在品质bundle形成后完成原生绑定。没有实际看图不能填独立审阅PASS。
