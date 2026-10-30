---
name: prism-target-view-binding
description: 实际看原图，将可见观察与DNA绑定到当前对象、部位和裁切范围，避免跨对象拼接或以局部替代整体。
metadata:
  version: "4.3.0"
---

# 棱镜｜对象与取景绑定


实际读取原图，定位当前对象/表面，核对观察位置与DNA所指范围。不能从at名称猜坐标；错归属、混合物件或不存在的细节保留为冲突。

总体风格需看形体、比例、色材与构造的组合，不能把所有图裁成匿名局部。ID保留声明形体及关键曲面转折；CMF局部保留相邻界面、厚度、边缘或接合以证明关系。半圆结构等主题特征必须完整看见。

记录原图FileRef、branch、comparison_scope、current_target、原像素、归一化rectangle(x,y,width,height)、DNA/观察引用、实际view_ref及阅读记录。品质父范围、比较范围、展示视窗分列；换视窗重新核对，不继承旧板通过。

源图片及身份不变，变的是展示范围。程序可查ROI边界，只有实际图像阅读能确认关系可见。


## 全流程衔接

读[4.3总合同](../prism_skill_support/references/contracts.md)及当前环节的引用。历史原生H01/H2和冻结R5只在对应模式执行；本环节的脚本检查不颁发设计情绪、用研认可或整板视觉通过。
