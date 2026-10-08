# 棱镜：六卡流程小 Skill 组合 v1.1-local

本目录是原v1.0归档的本地维护副本，新增 [已有DNA省额度选图政策](skills/prism_skill_support/references/budgeted-visual-selection.md)。原始归档和冻结运行未改；运行库与原生门保持上游字节。更新文档不会启动模型或解除已有暂停。`metadata/upstream-bundle-manifest-v1.0.json`保留上游清单；本目录完整性用当前`metadata/bundle-manifest.json`核验，`validation/validation-report.json`仍是上游原报告，不能当本地策略的视觉验证。

这套文件把已经实际跑过的六卡流程拆为13个小Skill，供同事在新项目里组合使用。包含三个已有便携算法、品质与ID/CMF原生校验、输入输出约定、可逆取景/HTML辅助器、离线测试及六张正面反馈校准卡。它需要助手对新材料作真实判断，不是拿旧答案套新图的一键生产系统。

## 同事怎么开始

1. 解压整个包，先打开 `技能导航.html`，按角色查看技能及顺序。
2. 使用Python 3.12+；可选Excel读写需要openpyxl，图像元数据/验证需要Pillow，语义与原生校验需要jsonschema。用同事自己的Python环境安装 `requirements.txt`。不会复制原作者的解释器、账号或登录状态。
3. 将 `skills` 中全部13个Skill目录及 `prism_skill_support` 一起放到目标技能目录。项目级可用 `.agents/skills`；也可选择同事自己的 `$CODEX_HOME/skills`。不要只复制SKILL.md丢掉脚本/字典/参考。
4. 附带工具默认只预览；目标已有同名目录会拒绝覆盖。按本地实际路径执行：

```text
python -B -X utf8 tools/verify_bundle.py
python -B -X utf8 tools/install.py --dest "目标项目/.agents/skills"
python -B -X utf8 tools/install.py --dest "目标项目/.agents/skills" --apply
```

5. 在目标项目调用 `$prism-workflow`，告诉它资料目录、想做的设计问题和预期方向即可。数量/分支/模型等已给出的条件不用重问；缺决定性信息才简短澄清。

可直接给同事的启动话术：

> 使用 $prism-workflow 按这套棱镜流程处理我提供的趋势库和用研报告。先核对数据和当前阶段，再完成语义握手、方向选择、选图、DNA及ID/CMF情绪卡。沿用我本次给出的数量和模型设置，保存来源、未知、实际调用和交接记录。

## 13个分工

| Skill | 职责 |
|---|---|
| prism-workflow | 范围、阶段、增量复用、问题闭环和路由 |
| prism-research-intake | 原报告文字/图片出现关系与来源入库 |
| prism-research-semantic-clustering | 用研纯语义聚类、角色/否定/按人去重 |
| prism-trend-semantic-clustering | 趋势文字目录、逐篇归组与库内规模排名 |
| prism-h01-semantic-handshake | 两侧文字第一次握手、引用审计与选择 |
| prism-visual-family | 语义方向到可见设计家族，显式记录设计转译 |
| prism-source-image-selection | 有界全库召回、原图/目标选择与来源身份 |
| prism-target-quality | 指定ID/CMF目标的可读、可复用设计信号 |
| prism-dna-sol-r5 | 冻结Sol R5的主解析与困难项复核 |
| prism-target-view-binding | 原DNA部位对应、可逆取景和实际视窗检查 |
| prism-id-moodboard | ID整体形态第二次握手与整板检查 |
| prism-cmf-moodboard | CMF表面/界面第二次握手与整板检查 |
| prism-moodboard-delivery | 内嵌图HTML、真实状态、来源及可审计交付 |

`prism_skill_support`是共享资源目录，没有大而全的SKILL.md；各小Skill只按需读取其中对应合同、脚本和运行库。三份既有便携算法保留各自的执行入口和示例。

## 跑通前先看这些边界

- 数据由同事在当前项目提供：本包不含8,833文章全集、五人私有报告或大批真实模型回答。六张已交付页面截图随包仅作视觉校准，不作新候选或独立金标。
- “趋势排名”当前是受支持主成员规模；“高级感”当前是用途/设计参考质量；“H2聚类”当前是给定可见家族的实际视觉选组。名称不能扩大能力承诺。
- 历史6方向/3ID+3CMF/严格最少10张仅在historical-six示例里。新项目数量与硬下限先登记；不要为凑通过降低事先标准，也不要用一个布尔值合并视觉、数量与用户反馈。
- 原流程、实际证明过的修复、复盘建议分别列在 `docs/方法边界.md`。预DNA预拼板、软数量政策、商业潜力排名等建议尚不是本套装已经实测通过的新算法。
- H01要实际用户选择或当前明确AI代选授权。原作者的“代确认”、额度卡和自动化权限不会随包继承。
- 模型调用默认prepare-only，只有当前授权下显式执行才用同事自己的额度。R5固定Sol/low/default请求档/Fast关闭；无模型权限就明确说明，不能暗中切模型。
- 验证结果在 `validation/validation-report.json`：只说明结构、离线回放和可移植性，不是新图片准确率或真实业务效果。原机器的路径和回执没有冒充同事的新执行。

## 需要的资料和文件格式

`examples`提供项目配置、PPTX来源配置、趋势输入/提案格式、召回词组、原图计划、模型任务和图板manifest示意。示例是合成/模板，不是本次真实执行结果。

完整阶段字段看 `skills/prism_skill_support/references/contracts.md`。用研语义和H01各自还有contracts与demo/selftest。原生品质、R5转接、ID/CMF方法签名由 `native_api.py describe`查看，字典和原规范代码已经随包。

先做环境检查或离线演示不会发模型请求：

```text
python -B -X utf8 skills/prism_skill_support/scripts/native_api.py doctor
python -B -X utf8 skills/prism-dna-sol-r5/scripts/cli.py self-test
python -B -X utf8 skills/prism-research-semantic-clustering/scripts/demo.py --out "本项目输出/研究合成演示"
python -B -X utf8 skills/prism-h01-semantic-handshake/scripts/demo.py --out "本项目输出/H01合成演示"
```

新图片的完整业务效果需要实际看图、执行和验证；不要把合成演示移到真实模式来代替评估。此套装不会自动恢复之前的loop、创建聊天、发布页面或替用户购买/兑换额度。
