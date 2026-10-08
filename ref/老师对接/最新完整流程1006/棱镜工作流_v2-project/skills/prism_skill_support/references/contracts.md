# 组合合同：阶段之间交什么

本包是17个可组合的助手工作技能、便携校验器和辅助脚本，不是训练好的分类器，也不是无需判断的一键生产系统。模型/实际审阅者仍需读新材料作判断。脚本不会从范例复制语义或视觉答案。

## 项目约定

首次开始或恢复时登记run_mode（end_to_end / historical_replay / visual_trial）、project_id、设计问题、数据目录、分支、期望方向数、图片目标数量及硬/软政策、当前模型和执行预算。`examples/project.example.json`是准备配置，执行授权默认false；`historical-six.example.json`仅复现六方向/3+3/严格10的历史配置。未知方向数或硬下限不要从例子继承为用户指令。

运行输出写入当前项目明确的输出目录。原图、原资料、模型原答复和失败不覆盖；新版本另存。配置中的相对路径以配置文件所在目录为基准。算法依赖随包相对定位；运行时FileRef使用当前真实本地绝对路径和SHA256，不能把源电脑路径抄给同事。

FileRef为`{"path":"本次本机绝对路径","sha256":"真实文件SHA256"}`。JSON pointer另存；引用与原字节核对。移动已有冻结运行需另建路径映射/新绑定，不改旧hash制造通过。技能安装目录可移动，原生模块依赖会在当前位置解析。

五种判定分别保存：semantic、visual、quantity、evidence、user_feedback。程序通过只证明其检查范围；独立同模型上下文不是人类金标，用户正面反馈也不补造旧程序PASS。合成夹具必须标synthetic_fixture，原生真实模式拒绝它。

## 用研原始材料

`intake.json`：dataset_id、dataset_mode以及sources；每个source有source_id、person_id、path，可有label/display_name。PPTX工具输出文字shape、媒体字节和出现/裁剪/旋转元数据；不渲染原页、不猜回答/偏好。由助手实际检查原页，把问题、选项、模板、回答和分析者笔记分开，再整理reviewed输入。

语义输入使用`prism-research-semantic-clustering/references/contracts.md`，支持简易JSON或原生八文件目录。每条保留原话全文、对象、页码、source_id/person_id、角色、态度。图片回链只是来源，不是自动的喜欢关系。研究Skill的prepare/accept/verify应先完成，然后将dataset与run整体交H01。

## 趋势文字

articles可以是JSON数组、带records的JSON、JSONL或CSV。必需article_id/title/summary，建议tags、text_kind、detail_url、source_url、published_at、category_original、image_urls。缺真实全文时`text_kind=source_paraphrase`，不能把模型摘要升级为网页原话。图像链接旁表不进入文字语义判断。

目录和逐条归类需要真实语义判断；脚本只冻结和编译。主归属支持复核与提案分开绑定，未归组/待定完整保留。`trend_text.py compile`直接输出H01可读的trend-clusters.json与text-catalogue.json；ranking.json只代表支持主成员规模。

## H01与选择

消费完整用研dataset/run和趋势两个接口文件，用现有portable H01校验器重放，不只拿handshake-input摘要或缓存supported字段。大库先做全目录候选发现，再补读候选簇的具体文章证据；保留完整主题池，代表例句不是全部可用文章。

H01输出候选、双侧依据、源态度、原对象、负向逐方向处置和未决义务。真实用户选择或当次明确AI代选确认后才能进入图片阶段。branch可ID、CMF或两者，不固定六个。H01选中仍是探索资格，不表示视觉合格、真实材质或目标人群已接受。

## 可见家族

visual-family.json至少说明：direction_id、H01选择引用、family_name、branch、comparison_unit、primary_questions、allowed_variation、confounders、comparison_scale、calibration_refs、scope_limits、source_extension_policy和count_policy。

ID native comparison_unit为whole_object；CMF为surface或same_object_interface。Native brief还要精确带h01_ref/h01_pointer、direction_evidence、audit_evidence、negative_audit、deferred_obligations。原negative和义务不由模型重新概括后替换。

count_policy需在看结果前登记target/minimum/maximum；随包原生H2仍需要具体minimum，不能因为少两图在验收时偷偷改小。若用户只给“约10”，先保持quantity状态独立，并在本次项目中明确选择的原生检验政策；历史严格10配置仅供复现。提案版软目标不是这次发布已验证的视觉算法改良。

## 素材与目标

1. metadata-pool：文章ID、原语义归属、召回理由、来源、待看图目标；扩展参考单列，不改原主题成员。
2. image-plan：images数组，每项image_id、article_id、source_group_id、本地local_path或原有image_url。下载动作只访问明确清单；没有--download不会联网。
3. original manifest：原图FileRef、像素、来源、项目/系列身份及其核实依据。没有证据的项目ID留未知，不造同项目或独立来源。
4. target choices：实际原图阅读依据、branch、selected_scope、selected_scope_limits、选择/拒绝理由、proposed_view。候选池可保留同文多个视角供比较；最终每板同文/已知同项目最多一图。ID不可全变局部，CMF不可拿另一对象补属性。

## 原生校验

`native_api.py`为白名单函数包装器，不执行模型。`--args`接受JSON；`{"$json":"相对prepared.json"}`载入该值，`{"$ref":"相对source.png"}`登记FileRef，路径以args文件目录为基准。其余值原样传入。

Quality prepare输入manifest_ref/image_pointer、asset_evidence、selection_ref、实际选图request/receipt引用；build_request产生准确模型prompt/schema。accept需要实际execution_ref、实际target_review_ref，不能把模板中的布尔值当真实审阅。使用[执行回执约定](execution.md)。

质量selection是H01选择的图片阶段投影，包含当前direction/branch、候选图片ID、完整原负向/义务和原H01_ref；保持selection digest。不能用新的图像选择投影偷偷改语义选择。质量bundle保存prepared、target、execution、target_review、result、producer_ref/producer_version，并全程保持同一图片/来源/分支。

## R5到原生H2

使用`prism-dna-sol-r5`的原字典/主解析/定点复核。相同字节和版本复用，原pending/invalid保留。`native_api r5/load_record`检查原R5归一化一致；参数是asset、result_ref，可选quality_ref。asset包含image_id、image_path、sha256和source身份。需要同图不同任务ID时用alias-r5，不改原结果image_id。

位置绑定由实际看原图的审阅者建立：每个endpoint引用该图原R5位置/观察，不创造DNA或物体树；目标引用原质量target。view记录原图、归一化rectangle、actual_view_ref、绑定引用、原像素和真实阅读provenance。ID还包括声明对象及整体可读性；CMF说明同表面或同物件界面关系。

## 原生H2

ID/CMF prepare输入brief_ref、manifest_ref、records、quality_bundles，重新检查原生上游数据而非信任缓存状态。grouping_view输出可读候选；实际模型提案再交accept_grouping。精确字节别名使用alias-id/alias-cmf贯穿prepare/current/grouping/board_review，避免前后入口不一致。

正式整板需要真实rendered_board_ref及独立实际审阅，再由prepare_board_review/accept_board_review接收。程序模板只定义字段，不能替代看图；数据集synthetic_fixture绝不升级为真实视觉PASS。

原生参考文档和合成fixtures随runtime附带供字段参考。模型请求应使用当前输入构造，不携带历史样例答案。无法形成合法原负向义务引用时保留失败，不能填一个无关索引。真实原负向适用范围要按对象与阶段解释；不能用“未知”自动批量拒绝所有参考，也不能当已经解决。

## 交付

render_board可以直接读取native grouping或board-manifest；只做原图内嵌、可逆ROI显示、同注册来源与SHA检查，不授予PASS。每个tile有image_ref、article_id、source_group_id、可选source_project_id、rectangle、scope、limits、source_url。通过查看真实截图完成整体视觉与浏览器QA。

交接来源、原图/视窗、事实/推断/未知、实际模型原答复与回执、版本和修复台账。按实际请求次数计数；token仅代表已回传使用量，未知不是0。不要打包private-runtime-state、账号认证、数据库、旧自动化授权或原始私有访谈作为技能默认数据。

## 本版的流程与模式

正式end_to_end：原始证据→用研/趋势分别纯语义聚类→H01→当前实际方向选择→可见家族及低成本选材预览→冻结广候选池→R5→目标预绑定→当前目标品质/正式绑定→ID或CMF H2→实际取景处理→整板→交付。取景救援可以在品质或H2之前进行，但目标改变后必须重新绑定和重审受影响范围。

visual_trial可以从明确选择的可见家族及已有素材开始，只验证其声明范围；必须说明H01/H2是否未执行。不能新建一个假的confirmed H01来让正式入口通过。historical_replay严格复放既有算法/输入，不用新规则改写历史结论。

相同SHA的R5复用包括原已知、未知、pending与invalid及版本；品质复用还要求同target、同view、同direction规则和同算法语义输入。不得因为一张图的椅子品质PASS就把旁边桌面当已审。

请接续阅读 [选材前置合同](material-contract.md)、[整板审阅合同](review-contract.md)、[评估合同](evaluation-contract.md)。原生格式由native_api describe和冻结模块负责；新辅助合同不替代原生H01/H2数据结构。

## 配置冻结的路径约定

workflow init同时保留project.source.json原配置和project.frozen.json。原input_paths相对原配置目录解析，冻结文件改为当前绝对路径，并记录base_directory、原配置FileRef、实际存在性及文件SHA；不存在的路径仍明确不存在，不造输入。项目迁往另一台机器时重新prepare/绑定，不直接修改旧冻结记录。新项目最终数量只使用quantity_policy；它在选材brief冻结时明确映射为原生count_policy，不能同时留两个冲突的最终数量字段。
