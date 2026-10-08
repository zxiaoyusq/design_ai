---
name: prism-target-view-binding
description: 把原DNA已知位置绑定到选定对象，确定ID整体或CMF局部视窗并核对实际显示。用于解析后范围绑定；不创建新DNA、不用后期增强证据补齐不可见特征。
metadata:
  version: "1.0.0"
---

# DNA目标绑定与可逆取景

先读 [组合输入输出合同](../prism_skill_support/references/contracts.md) 的“R5到原生H2”。输入质量bundle、原始R5结果、原图和可见家族。用native_api r5/load_record重放原归一化与图片字节；同字节不同任务ID只能走alias-r5入口，不能手改原结果。

实际看原图，把每条必要观察绑定到原at位置和其自己的观察ID。unknown/pending/invalid不得当已知；图级索引不能证明不同位置条件共现。R5平面位置没有对象树/bbox，不假装它已有精确几何锚点。

ID写single_object或有实际依据的explicit_ensemble；组合声明多个对象就必须保留其主要整体关系。CMF明确surface或same_object_interface，接口两端必须同属该物件且真实可见。不因框太宽自动借值，也不为入组随意缩掉已声明目标。

ROI使用原图比例x/y/width/height，记录原图SHA和当前像素；裁切与等比例显示可逆，保持原字节。随包render_board.py可以渲染单图manifest作视窗；由当前可用浏览器截图工具得到实际显示，记录图像FileRef。别把更大截图分辨率当成更高原始细节。

另一个真实上下文比较原图＋实际视窗，确认内容对应、主要关系可读、ID整件未被裁成局部。视窗证据不足就pending。图片增强只可另作展示版本，保留原图/增强标记，不回灌质量和DNA。

输出candidate_manifest、target_binding、view、质量bundle和R5 record。字段由 [原生API参考](../prism_skill_support/references/native-api.md)及随包schema/fixture说明，合成fixture只用于理解字段，不是实际审阅结果。
