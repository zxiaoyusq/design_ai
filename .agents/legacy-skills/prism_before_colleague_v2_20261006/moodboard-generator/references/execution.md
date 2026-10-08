# 项目执行入口

使用项目 `314` conda 环境。Skill 正文包含完整的两阶段协议，本页只说明运行与发布。

## 网页与后端模型

`/moodboards` 支持选择已有趋势方向、批量选择 DNA、模型和确认范围。每次新任务冻结当前 Skill，历史任务恢复其冻结协议。

`backend/scripts/run_moodboard_sample.py --direction-ids D0001 --count 3` 只预览计划；已有本次执行授权时追加 `--confirm`。少于 4 张可以验证匹配和样本不足分支，不应期待正式主题。

- `--trend-task-id` 省略时取最新有效高潜趋势。
- `--direction-ids` 新建必填；`--count` 默认 3、范围 1–100。
- `--model-id` 为后端模型目录 ID，默认 `gpt-5.6-sol`；这不是当前 Codex Astra。
- `--resume-task-id` 沿用失败任务冻结范围，不与新趋势/方向混用。用户明确要求继续后可用 `--confirm`，不扩大范围。

任务记录保存在 `data/result/moodboards/<任务ID>/`，以 `task.json` 最终状态为准。

## 当前 Codex Astra 宿主

用户指定当前 Codex Astra 时，由宿主阅读 DNA 文字完成语义分析，不用其他 API 模型替代。`backend/scripts/run_moodboard_host.py prepare --confirm` 是**全量**冻结入口，仅在本次明确要求全量时使用；普通 Skill 验证用独立小样本快照。脚本只负责准备和校验，不使用关键词算法代替模型匹配。

1. 冻结趋势、所选 DNA、来源、当前 Skill 和选择依据，写 `inputs.json`、`skill.md`、`host_manifest.json`。每个匹配批次必须携带全部所选方向。
2. 宿主逐批执行第一阶段，保存 `assignments/<批号>.json`。可逆短别名只帮助阅读，提交前还原 `result_id`。
3. 验证全部输入唯一记账后，按唯一归属生成 `clustering_inputs/<方向ID>.json`，包含该方向全部候选 DNA；第二阶段精选并保存 `clusters/<方向ID>.json`，未入选者保留理由。
4. 每阶段回执放在 `receipts/assignment-<批号>.json` 或 `receipts/clustering-<方向ID>.json`，记录 `model: Codex GPT-6 Astra`、起止时间、输入输出文件及 SHA256、Prompt 版本 `moodboard-codex-host-v3`。内部调用次数和精确 Token 未知时保持 `null`。
5. `backend/scripts/run_moodboard_host.py publish --run <运行目录> --confirm` 校验冻结哈希、成员、证据、精选限制和回执后登记网页历史。不会覆盖已登记结果。保留真实的样本/全量范围，不把小样本称为全量验证。

可分包读取，但匹配不能按方向分割候选比较，单方向最终精选必须考虑该方向的全部输入候选。独立语义验证应只给执行者 Skill 和最少原始资料，不透露预期归属；检查输出后再决定是否需要调整规则。
