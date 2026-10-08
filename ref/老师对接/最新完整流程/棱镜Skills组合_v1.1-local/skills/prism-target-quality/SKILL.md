---
name: prism-target-quality
description: 对已选原图目标检查可读性和具体可复用的设计关系，并独立核对证据归属。用于ID/CMF用途筛查；不以此推断奢华档次、用户喜好或整板一致性。
metadata:
  version: "1.0.0"
---

# 指定目标用途品质

输入原图、精确目标、分支、当前H01选择和完整边界。先读 [组合输入输出合同](../prism_skill_support/references/contracts.md) 的“原生校验”和 [声明范围政策](../prism_skill_support/references/declared-visible-scope-policy.txt)。

使用随包selected-target-quality-v2：
```text
python -B -X utf8 ../prism_skill_support/scripts/native_api.py describe --module quality
python -B -X utf8 ../prism_skill_support/scripts/native_api.py call --module quality --method prepare --args prepare-args.json --out prepared.json
```
再build_request；通用执行器默认仅准备，实际调用使用本次授权及自己的模型环境，见 [执行与回执](../prism_skill_support/references/execution.md)。保留原生prompt/schema和实际有效输入，批量传输也分别绑定目标。

先确认声明范围，再评清楚、具体、受控、可复用的设计关系。ID评整体形态；CMF评指定表面。不是价格、品牌、稀有或“看起来高级”的代替指标。正向证据只能引用selected_target，不能从其他物体、背景或标题借用。

另一个实际阅读上下文看原图，逐条确认原证据归属和覆盖；没有实际复核不能写independent PASS。调用accept重放主判/确认与target_review，只消费admissible范围。未知、FAIL、scope_pending分别保留，不用一个布尔值抹平原因。

未请求的背面或另一状态留为限制；声明内关键遮挡仍阻断。只给必要目标做一次规则允许的确认，保留旧答案。输出原生quality bundle和所有引用；这个PASS不替代H2或整板判断。
