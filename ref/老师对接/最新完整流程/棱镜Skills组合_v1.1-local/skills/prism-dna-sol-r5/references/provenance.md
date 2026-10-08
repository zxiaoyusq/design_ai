# 来源、移植方式与限制

来源任务：棱镜-解析算法。用户于2026-09-29选择`sol-coverage-dna-r5-20260929`作为下一步ID/CMF聚类试用基线；不是生产认证。

`assets/source-r3.py`、`source-r5.py`、`source-refine.py`和`source-finalize.py`是冻结源码原字节，原提示、schema、字典和vision-only指令也按原字节保存。`source-manifest.json`提供哈希及原位置。

这些原源码顶层带有原电脑路径，不能直接当便携脚本执行。`scripts/engine.py`只加载冻结源码的纯算法函数，并以包内字典绑定其依赖；不会执行原顶层路径加载器、固定4图实验调度器或旧调用。补查前置prompt/schema直接来自原refine函数；最终合并包装将HP01/MC01固定样本名改为当前image_id，保留原替换规则和状态纠正逻辑。

`scripts/cli.py`是此次新增的便携执行封装，原算法规则未重写。初次/困难字段/可选补查均使用原规则；输出元数据另标portable_result.v1。离线一致性测试不能替代在新机器上的模型实跑。

冻结范围：4张图片，其中耳机和摩托车是开发样本，H11/H12是该轮未用于调优的新图；不是大样本盲测。普通字段没有全量独立视觉复核，存在未决项；没有人工金标准准确率。原费用字段为token价格估算，不是账单归因。

当前流程要求先做趋势语义和用研报告语义的方向握手，由设计师选定后再调用本skill。它可以一次提取供ID和CMF两条路线使用；高级感、用户偏好、物理量测及最终分组由其他职责处理。

CLI开关依据：已核对本机`codex exec --help`与官方 [CLI参数文档](https://learn.chatgpt.com/docs/developer-commands?surface=cli)、[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。模型与low由命令显式设置，service_tier单独设置default，Fast单独关闭；包内不推断同事账号的模型可用性。
