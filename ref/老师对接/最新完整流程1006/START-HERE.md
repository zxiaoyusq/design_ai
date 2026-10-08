# 棱镜完整工作流｜17个小Skill组合 v2.0

先打开 [完整工作流.html](完整工作流.html)，它详细说明从图文到两次握手、DNA、当前目标品质、裁切、整板复核及交接的全部步骤。按环节拆成17个Skill，共享代码放在prism_skill_support；没有一个包办所有算法的大Skill。

## 同事第一次使用

1. 解压整个包。先读流程和真实案例，确认每一步的输入输出与判断责任。
2. 需要Python 3.12+与requirements.txt中的依赖。真实模型执行还需要同事自己的Codex CLI和账号权限；本包不复制登录或额度授权。没有CLI也可读手册、看HTML并做已具备依赖的离线验证。
3. 整套安装时，把skills下全部17个Skill目录和prism_skill_support放在同一父目录；不能只复制SKILL.md。可选择当前项目的.agents/skills，或同事自己的技能目录。安装工具默认预览，拒绝覆盖同名目录。
4. 开始前先验证完整性、离线算法和本地图片显示。工具不会发新模型请求。

```text
python -B -X utf8 tools/verify_bundle.py
python -B -X utf8 tools/run_checks.py --out "自己的工作目录/离线检查" --native
python -B -X utf8 tools/prepare_case.py --out "自己的工作目录/真实案例重放"
python -B -X utf8 tools/install.py --dest "目标项目/.agents/skills"
python -B -X utf8 tools/install.py --dest "目标项目/.agents/skills" --apply
```

需要安装依赖时，在同事选定的Python环境中使用requirements.txt。环境安装按本机当前规则办理，不带作者解释器。安装到已有同名目录会明确失败，先有意识地备份/迁移旧版，不静默覆盖。

## 可直接复制的启动话术

“先用 $prism-run-contract 核对本项目资料和已有状态，再按技能导航完成两侧纯语义聚类、H01及选向。方向确定后建立广候选池，做Sol R5、当前目标品质及ID/CMF选组，最后精选约10图并独立审阅实际整板。候选解析量不要被最终图数限制。保存原图、原话、未知、实际调用和交接证据。缺决定性信息再简短询问。”

只试单板时说：“按visual_trial模式，用 $prism-visual-family 和 $prism-source-image-selection 先写清主关系、比较范围及处理动作，再做一个板。保留原图对照，不能把试板PASS写成全链路PASS。”

## 技能与顺序

|阶段|Skill|职责|
|---|---|---|
|00|[prism-run-contract](skills/prism-run-contract/SKILL.md)|范围与运行约定|
|01|[prism-research-intake](skills/prism-research-intake/SKILL.md)|用研证据入库|
|02A|[prism-research-semantic-clustering](skills/prism-research-semantic-clustering/SKILL.md)|用研纯语义聚类|
|02B|[prism-trend-semantic-clustering](skills/prism-trend-semantic-clustering/SKILL.md)|趋势纯语义聚类|
|03|[prism-h01-semantic-handshake](skills/prism-h01-semantic-handshake/SKILL.md)|第一次语义握手|
|04|[prism-direction-selection](skills/prism-direction-selection/SKILL.md)|设计选向|
|05|[prism-visual-family](skills/prism-visual-family/SKILL.md)|可见关系与选材说明|
|06|[prism-source-image-selection](skills/prism-source-image-selection/SKILL.md)|广候选池与素材计划|
|07|[prism-dna-sol-r5](skills/prism-dna-sol-r5/SKILL.md)|Sol R5原图DNA|
|08|[prism-target-view-binding](skills/prism-target-view-binding/SKILL.md)|当前对象与位置绑定|
|09|[prism-target-quality](skills/prism-target-quality/SKILL.md)|当前目标品质|
|10A|[prism-id-moodboard](skills/prism-id-moodboard/SKILL.md)|ID第二次握手|
|10B|[prism-cmf-moodboard](skills/prism-cmf-moodboard/SKILL.md)|CMF第二次握手|
|11|[prism-crop-enhancement](skills/prism-crop-enhancement/SKILL.md)|裁切与展示增强|
|12|[prism-board-review](skills/prism-board-review/SKILL.md)|整板独立审阅|
|13|[prism-moodboard-delivery](skills/prism-moodboard-delivery/SKILL.md)|离线交付|
|贯穿|[prism-independent-evaluation-loop](skills/prism-independent-evaluation-loop/SKILL.md)|独立评估与定点改良|


## 当前发布边界

三份原便携算法（用研语义、H01、Sol R5）与原生品质/ID/CMF验证器随包；新增前置材料合同、整板审阅合同检查及future负向引用适配。模型需要实际读新文字/图片，不能由校验器替代判断。

本版没有重跑付费模型或新全库。离线测试证明边界、回放和可迁移性，不证明新的审美准确率。历史六板原生未全部通过，新单板视觉PASS也未重跑H01/H2。严格区分这些范围。

原作者的AI代选、跨聊天发消息、自动化、额度卡权限不继承。默认模型调用prepare-only；当前任务有明确授权并使用自己的配置后才执行。完整数据由当前项目提供，私有访谈不随技能默认传播。

独立技能可以只阅读自身及需要的引用；安装共享依赖有三个旧便携算法和runtime的实际关系，整包安装最省事。`validation/validation-report.json`是本次验证结论，`metadata/bundle-manifest.json`是文件哈希清单。
