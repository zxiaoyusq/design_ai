# 选材前置合同 v2

此合同解决“选素材时就写清应该怎么处理”。它是原生H01/H2前后的工作合同，校验器不替代看图，也不会生成DNA或品质PASS。

## brief：整个方向共同的标准

- direction_id、branch（ID/CMF）、selection_ref或visual_trial的明确来源；必须说明mode。
- comparison_unit：whole_object、surface、same_object_interface。
- primary_relation：共同的可见设计关系。必要证据、允许变化、confounders分别写。
- count_policy：最终板target/minimum/maximum和是否硬门。candidate_pool_policy单独写目标候选数、独立项目覆盖与预算；两者不能自动绑定。
- scope_limits：不可声称什么；negative_audit和deferred_obligations从H01完整继承。
- calibration_refs：仅参考；不能参与新候选数量。
- frozen_before_final_selection：冻结时间与文件哈希。变更规则创建新版本并明确受影响复验。

## 每张材料的工作项

必需image_id、原图FileRef、article_id、source_group_id；有依据时加入source_project_id/series_id及identity_basis。不能用不同文件名证明独立项目。FileRef在当前机器生成，SHA相同可复用原字节；portable案例先按相对路径校验，再转本机FileRef。

每行记录 current_target（对象/状态）、comparison_scope（当前部位）、primary_relation_evidence（看见什么）、secondary_signal（可能抢主题的其他信号）、crop rectangle、处理动作、原因、原像素、阅读者/真实读图记录。

处理动作：keep_whole、crop、display_enhance、request_clearer_source、evidence_pending、exclude_for_family。exclude只表示不适合这个家族，不能推出全图没价值；像素或证据缺口先单列。

若有原始DNA，携带result_ref、已知观察ID及原at，pending/invalid原样保留。当前对象没有被覆盖则标scope_gap；不把cached supported当验证结果，不造位置。品质父范围与当前比较范围是两个字段，可以是包含关系；不能跨物件。

## 处理分支

1. 图里主角不对，但其他表面有用：选择那个对象→重新绑定和审品质。
2. 目标合适、背景干扰：明确ROI→实际显示→与原图核对，不把裁切当删除原反证。
3. 原关系看得清，展示像素少：寻找更高质量同源原图，或另作展示增强；增强不修改DNA或原图真实性判断。
4. 原关系看不清：补更好来源或角度，保留pending；不能生成不存在的证据。
5. 单张有共同特征，但其他图案抢主题：在预览/整板审阅记录具体干扰；从候选池替换，标准不变。
6. 多张符合但都来自同一个项目：增加独立项目候选；不能把同源组图算作十张独立参考。

## 使用工具

`material_plan.py --brief brief.json --candidates candidates.json --out prepared-materials`只验证合同、当前原图哈希、ROI边界、分母和排重信息，输出prepared，不授予视觉通过。样例见包根examples/material-brief.example.json与material-candidates.example.json。

已验证案例：linear-relief先以20张真实原图进行新方向审阅，12张可继续，最终10张；整板第一次发现N111的花色干扰，按同一规则替换N080。该案例复用已解析原图，不证明新的全库H01召回效果，也不是所有家族都要低彩度或至少五条槽纹。
