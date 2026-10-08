# 整板审阅与协议验收

## 当前板身份

board_manifest含direction_id、branch、brief_ref、rendered_board_ref和选中tiles，每图明确original_ref、当前view_ref、范围、source_group/project及原native状态。视觉审阅必须绑定这版整板哈希；换图或视窗后旧审阅不再给新板作证。

## 独立判断

review保存reviewer_actor、review_kind（ai_independent_context/human/synthetic_fixture）、review_trace_ref、board_sha256、brief_sha256、逐图issues与视觉judgment。运行者必须如实记录真实阅读上下文；本地JSON格式或一份自己写的PASS不是独立审阅。

不把作者结论预填给审阅者。展示实际整板、当前视窗与需要的原图，明确事先允许差异。逐图给身份对应、共同关系、干扰、范围/像素可读性、是否保留和具体修复。整板还要说明最不一致的成员和组合主次。

数量、SHA和已知项目排重可程序查；来源未知时标uncertain。视觉模型不能凭图片声称核验了来源和文件哈希。整板视觉PASS与semantic、quantity、provenance、native_gate、human_feedback分别保存。

review_gate.py检查表述与当前板绑定、逐图完整性、计数和重复项目，以及PASS不掩盖未通过成员。输出只叫`machine_contract_check`，`visual_judgment_origin`仍是提供的实际审阅；`new_visual_review_performed=false`。当synthetic_fixture时永远不能产生真实审美PASS。

## 原生门

正式H2使用原prepare_board_review/accept_board_review重放上游。alias或future adapter从prepare到全部后续调用必须一致；选材试验没有正式H01时不得创建假的H01来解锁原生门。

一次具体失败最多三轮，保留旧图/旧答案/原条件。修复先小范围；原失败仍未解决就不能降低数量或改定义。原生阻断与人类正面反馈可以同时成立，应并列展示。
