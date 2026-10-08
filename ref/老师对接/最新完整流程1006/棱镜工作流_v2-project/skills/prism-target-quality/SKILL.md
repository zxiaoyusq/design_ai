---
name: prism-target-quality
description: 对明确的ID对象或CMF表面检查可读性、设计关系与证据归属，形成原生quality bundle。用于高级感流程的用途品质环节；不评品牌价格或用户喜欢程度。
metadata:
  version: "2.0.0"
---

# 棱镜｜当前目标品质筛查

输入原图、当前目标、ID/CMF分支、selection和完整边界；输出原生quality bundle、适用范围、限制、原答复和复核证据。读取 [原生校验合同](../prism_skill_support/references/contracts.md) 及 [声明范围政策](../prism_skill_support/references/declared-visible-scope-policy.txt)。

使用随包selected-target-quality-v2，先describe，再prepare/build_request，按当前授权进行真实判断并保存有效输入。它衡量清楚、具体、受控且可复用的设计关系；不是价格、奢华阶层、品牌名或物理加工水平的代称。

正向证据只引用selected_target。主图是椅子而这次要桌面时，应审桌面，不继承椅子的通过。未请求的背面或展开状态是限制；当前声明内关键遮挡仍需处理。

先区分语义不适用、目标错误、关系不清、像素不足和呈现问题。能通过裁切获得合适范围的，交裁切后重新审该范围；仅展示像素不足可考虑增强，但生成细节不补足原始证据。品质判断不回头缩小已经冻结的解析实验分母。

另一个实际阅读上下文确认归属与覆盖，再由accept重放主判、execution和target_review。不能拿受信缓存字段代替唯一可信验证入口。只消费admissible范围，FAIL、scope_pending和unknown分别保存。

工具入口：
```text
python -B -X utf8 ../prism_skill_support/scripts/native_api.py describe --module quality
```
具体回执约定看 [执行说明](../prism_skill_support/references/execution.md)。质量PASS不替代H2和整板判断；移交时保留父品质范围与当前比较范围的关系。
