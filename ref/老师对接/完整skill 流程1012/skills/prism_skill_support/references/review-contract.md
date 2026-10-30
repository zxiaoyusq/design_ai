# 整板评审合同 4.3

视觉与解析共同判断；先实际看无标题的板及原图，再读解释。每张记录核心可见关系、独立支持维度、情绪、明显冲突、局部差异及面积/对比/位置/结构作用。检查最不一致对及与邻板的区分。不能用标签数量替代共同语言。

柔塑需要柔软+雕塑同时成立，暖色灯光、松散衣服、硬壳折椅各自不够。深色有序需形态组织规整，杂乱多关节灯不能只靠深色加入。银壳需约定厚实体块/包覆或折片等具体形态，灰色不证金属，圆润整机与局部圆件不同。粗颗粒和多彩仍需尺度、密度、配色及形体收敛。详见视觉技能实际反馈页。

允许不破坏核心情绪的局部差异。设计师对柔塑R4的“整体可、局部边稍利”是这一版的容忍说明，不是所有三板通过。不得以不可能完美一致为由放弃主关系，也不得见小差异就全删。

`review.json`至少保存board_manifest_sha256、rendered_board_sha256、brief_sha256、review_kind、reviewer_actor、真实review_trace_ref、逐图slots、最不一致对、core_conflicts、tolerated_variations、style_judgment、presentation_judgment与user_feedback refs。作者自审如实写same_analyst_review；没有真人选择就是未验证。

新`style_board_check.py`只检查机械与引用完整性。旧`review_gate.py`服务原v2字段，需其真实独立记录；原生H2另经prepare_board_review/accept_board_review。三种入口作用不同，均不从不存在的记录创造已看图或设计师批准。

换图/改裁切必须绑定新板SHA并重审该图与组合；旧意见保留版本。数量不够或来源独立性未决时，仍可交研究候选，但不可标合格访谈板。
