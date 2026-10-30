---
name: prism-dna-clustering
description: 对已有可见DNA作可追溯候选分组，保留未知和对象范围，作为视觉与解析联合筛选的可选辅助。
metadata:
  version: "4.3.0"
---

# 棱镜｜DNA辅助分组


这是可选辅助路线，不是当前总体风格工作流的必经门。随包`cluster.py`保留3.0-trial-5冻结的类型化字段、已知范围差异与complete-link算法，阈值未经人群标定。它不是DINO，也不重启已叫停的视觉嵌入路线。

输入稳定image_id、known_facts(p/v/at)、effective_texture_states、仅绑定原事实索引的id_objects。程序不使用语义标题、偏好词和来源类别作相似度；这些证据必须保留在旁表并在候选筛选/成板时重新合并，不能因隔离聚类输入而丢掉用研。

未知不填0或无特征；不同对象/表面不拼接；局部轮子形状不当整体形态。最终pending纹理不能覆盖成无纹理。按原SHA与规则复用，原图反证另存补充观察。

`python scripts/cluster.py --records blind-records.jsonl --out cluster-output`输出units、clusters、unit-gaps、receipt。只共享材质/颜色/光泽是检索组；真正总体风格还要由原图与解析一起确认多维组合、设计情绪和用研范围。

允许小簇、离群和无足够DNA记录。不要为了8张目标改变算法阈值强合组，不把全字段或聚类成功称成板通过。原图视觉+语义审阅可建立新的风格组，需明确不是冻结算法原生输出。


## 全流程衔接

读[4.3总合同](../prism_skill_support/references/contracts.md)及当前环节的引用。历史原生H01/H2和冻结R5只在对应模式执行；本环节的脚本检查不颁发设计情绪、用研认可或整板视觉通过。
