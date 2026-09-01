# Claude / Claude Code 接入

把完整目录安装到 Claude 支持的 Skills 位置，确保目录名与 `SKILL.md` 中的 `name` 一致：`multimodal-design-dna-multitag-extractor`。

只有用户点名本 Skill，或明确要求“扁平、多标签、无主次、组合风格”时才触发。普通设计 DNA 提取继续使用原 `multimodal-design-dna-extractor`。

向会话提供一张图片并要求提取主物品设计 DNA。需要保留 `references/`、`schemas/` 和 `scripts/`；若环境不能执行 Python，应由外部服务执行同等校验。多图聚合或多物品比较应转交其他工作流。

当前只允许 38 个活动风格标签；TribeIdentity 已废弃，身份信息只写入 IDG-05/07/09。不要读取或生成组合预设，宿主 Python 会在模型输出后写入。
