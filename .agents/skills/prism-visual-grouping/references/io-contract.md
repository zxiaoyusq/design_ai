# 视觉选组：输入、输出和交接

统一业务入口仅路由分支与收集结果。ID v5 / CMF v4 brief、manifest、records、quality bundle、proposal 和 native grouping 仍使用原格式，不新造统一算法 schema。

## 输入

| 输入 | 责任 |
|---|---|
| 显式 branch 与项目合同 | ID 或 CMF；已登记最终数量、独立来源政策和当前模型预算/授权 |
| 冻结 brief | 共同比较主关系、必要证据、允许变化、干扰、范围限制、H01 指针与原负向/义务，不从选中图片反推新条件 |
| 冻结候选 manifest | 所有候选与图像身份、来源/已核实项目、actual original FileRef、同字节 alias 身份；保留原分母 |
| 原 R5 records | 原始结果、原观察/at、known/unknown/pending/invalid、版本与图片 SHA；不伪造 DNA 或对象树 |
| 单图参考准备结果 | 当前对象/表面绑定、原生 quality bundles、actual_view_ref、真实 ROI、原像素、实际阅读记录和范围限制；当前图和取景变化后重新验证 |
| 原始证据和上下文 | 原图与实际裁片可读、selection/负向/未来义务来源，供 prepare 重放完整上游 |

ID manifest 为 prism.id.candidate_manifest.v5，brief 为对应 visual_brief.v5；CMF 分别为 prism.cmf.candidate_manifest.v4 / visual_brief.v4。prepare 参数沿用 brief_ref、manifest_ref、records、quality_bundles。

## 原生执行与输出

| 输出 | 表示什么 |
|---|---|
| prepared | 原生上游重放后的 eligible / pending / 不适用，不能由 cached supported 代替 |
| grouping_view / template | 供真实审阅者读取的候选或字段模板，本身不是提案和审阅 |
| actual proposal + execution/read refs | 当前真实看图产生的成员、共同关系、负向处置、排除与待定依据，保留实际原回答 |
| native grouping | accept_grouping 接收结果、真实 selected members、关系证据、来源与范围限制；仅表示其分组检查范围 |
| candidate dispositions / gaps | 全冻结候选的 selected/excluded/pending 及理由；visual、quantity、evidence、semantic、user_feedback 状态分别保留 |
| 待审板资料 | 成员真实原图/视窗、tile 来源、article/source_group/project 身份、主关系、未完成与实际工作量，供真实渲染和独立板审 |

本项目新板为 10 张/10 可核实独立项目。同文章/已知同项目每板最多一张；不同 URL 或 SHA 不证明项目独立。若原生仅验证来源组排重而未验证项目身份，项目身份的不足仍须独立输出，不能宣称 10 项目已满足。

prepare、模板和分组通过不等于整板通过，也不等于用户认可。所有未完成/失败保留；不能先交付 PASS 再补证据。

## 分支与回退

ID 使用整件轮廓、比例、结构关系；CMF 使用同一声明 surface 或 same_object_interface，二者没有统一可交换的比较单位。需要二分支时分别准备输入和结果，不能混在一份 native proposal 里。

实际裁片的目标、ROI、尺度或品质发生变化，交 `prism-reference-image-preparation` 生成新版本、重绑并复核受影响范围，再重放 grouping。分组结果交 `prism-board-review`，由它独立审阅真实渲染板；完成后由 `prism-moodboard-delivery` 按真实状态交付。若用 alias-id/alias-cmf，则这些后续原生步骤继续使用相同 alias 入口。
