> 本页仅用于2.x历史流程；新任务使用 [3.0轻量流程](lean-workflow.md)。

# 证据、时间与图片关联规则

## 输入投影

趋势使用 id、title_zh、summary_zh、primary_category、subcategory、tags、release_time；可选 local_vl_info 为既有视觉分析，不是本轮看到的像素。confidence、clust_status 不作为潜力评分。images 只进入程序索引。

用户使用 id、profile、aesthetic_research 下 question/ai_analysis/answer_type/scenario_type/question_type，以及 demand_research 下 ai_index/scenario/ref_pic。“未提及”问答排除，其他问题和回答共同解释。画像仅用于上下文，不推测偏好；ai_analysis 称源分析字段片段，不能称已验证的访谈原话。

原值为列表或对象时投影为保留 Unicode 的 JSON 文本，引用按该文本校验；json_pointer 仍指向原字段对象。引用与输入文件哈希共同使用，不能假设跨版本数组下标不变。unlinked_demand_research 标为 orphan_demand，不能单独满足候选的用户侧要求，也不计人数。

## 提取与归纳

一条观察保留一个连贯事实或同条件、同态度的相关诉求。设计维度：color、material、form、structure、light、touch、interaction、identity、durability、sustainability、other。一条观察可有 1–3 个 dimensions，但保持单一证据 ID；一个记录可以有多条原子观察。防滑触感与耐摔需求可以同时保留 touch 和 durability，不因一个标签覆盖另一个。材料微观交联属于 material，制造定制不等于产品使用 interaction；概念或原型的来源状态必须保留。提取不另生成场景、原因或品类解释；这些语境保留在完整原文与 source_records 中，后续按需解释，不补造。

程序从 observations 和 skipped 恢复逐记录 coverage；不能用空 observations 隐藏未处理内容。skipped 仅记录不涉及设计或无法判定并说明原因。短文省略 quote 时恢复所选 field 全文；超过 600 字需显式连续引用，不能截断或把默认全文当作摘要。问题只是上下文，不能从“你喜欢透明吗”提取“用户喜欢透明”。趋势只能 stance=example；用户态度分支持、反对、条件、不明确。

候选同时引用趋势与可归属用户证据，并分别在 trend_basis/user_basis 说明依据，shared_principle 写双方共同支持的最小设计原则。先经过独立 screen 核对，再合并及完整反证；不能把“羊毛球缝合承重”当作“非对称布局”的趋势依据。相同机制和体验诉求才可能形成交集，共享关键词不够。反证以候选命题为参照判断关系；原始负面表达可能支持一个“避免某设计”的命题，必须解释推导。

边界情境：用户可能喜欢汽车灯光却拒绝手机灯光，接受透明手表却认为透明手机脆弱。要提炼情境差异，不能归纳成普遍喜好。跨品类应用列为 hypotheses，不自动扩大原用户证据范围。

## 确定性统计与优先级

按反证结果关联的唯一 user_id 统计，问答与需求重复不多计人。支持和反对并存为 mixed，单独条件支持为 conditional_only。无关证据不表示拒绝，不能提供整体市场偏好率或假设所有画像用户都回答过。

趋势计数是不同原记录数；首版无法验证项目与发布者独立性，independent_project_count=null。审核与人工复核应检查同一品牌项目的重复报道。

日期筛选依据 release_time；近期以固定 as_of 前 730 天内的已知日期判断，未来日期和未知日期不计近期。这是运行规则，不是市场研究中的统一标准。

模型给出的 priority_validation / contextual / exploratory 是建议。程序在支持/条件/混合用户合计少于 3、支持趋势少于 2 或没有近期趋势时降为 exploratory；有反对、混合或条件支持时不能保留不加限定的 priority_validation。独立性与原始访谈真实性未核实，evidence_strength 保守为 limited。

## 图片回填

输入 local_path 分别相对于各 JSON 所在目录，仅允许来源目录内的相对路径。最终提供项目相对路径及 absolute_path，只检查存在性，不打开图片。

趋势图片 association_level=article、visual_verified=false；不能声称某图准确证明某特征。用户证据只接受 quote 中实际出现的 image_codes，并沿同一用户的原始关联查找。

需求使用 ref_pic_links，问答使用同一用户 image_preferences 的 ref_pic_code。不能从长记录末尾 ref_pic 将图片扩散到每个观点。未匹配时保留空路径；同一编码对应多图时全部作为待核对候选，不自行选一张。不能跨用户猜配。

程序从当前来源与引文补齐已知编码，模型未判断的角色保持 unclear。每个最终 image_code 在 image_roles 中恰好有一个角色：target/comparison/reference/unclear。输出称 trend_reference 或 user_target/user_comparison/user_reference/user_unclear；evidence_relation 单独保留整条证据关系，image_attitude_from_text=null，不把整句反对关系赋给比较图片。例如“纹理不好，不像 P50 那样有手感”中的 P50 是比较对象。ENJOY/DISLIKE 可留作来源信息，不能直接归因于某视觉属性。没有精确图片关联不损害已成立的文本证据。

## 审核与措辞

每个核心事实引用证据，审核检验语义是否成立而不只是引用存在。claims 写资料支持的发现，opportunities 写跨品类探索假设，boundaries 写条件与反例；不能混为既成事实。弱拒绝如“不太会接受”不能改成绝对拒绝。

暂缓候选、反证后证据不足者和审核拒绝者全部进入 validation_report，不表示没有需求。审查覆盖候选维度内的已提取文本，保留此边界。人工评审状态初始 pending。
