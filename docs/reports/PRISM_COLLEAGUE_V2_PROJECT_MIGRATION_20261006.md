# 同事v2基准迁移与工程接线（2026-10-06）

用户明确要求以同事Skill为基准，冲突按同事，网页仅匹配现有展示格式。原包保持不变，完整17项Skill及共享源码安装在 `ref/老师对接/最新完整流程1006/棱镜工作流_v2-project/`；`.agents/skills/`指向该版本。旧版本备份在 `.agents/legacy-skills/prism_before_colleague_v2_20261006/`。

## 新流程的实际规则

1. 两侧文字语义/H01/选向采用同事原生数据与验收协议。旧趋势要点多归属、100条/3来源门和旧用研B批次算法不再由兼容Skill入口调用。
2. H01方向先转成可指认的主关系、必要证据、允许变化、第二强信号、比较对象与尺度。低成本预览核来源容量/处理动作，再冻结material-brief。五条槽纹、低彩度等只属于具体案例。
3. 广候选容量与成板数量分开登记，不以最终10图截断候选；不把30/100或旧60/12/2作为通用默认。新项目预算需明确，耗尽保持未完成。
4. 本次新板硬要求10张、10个可核实独立项目。不能用不同URL、不同项目ID字符串或同一句泛指引用证明独立性。每成员实际来源身份复核须绑定项目、文章、图片、原图SHA及来源/raw答复；合成数据没有真实来源PASS。
5. 先定位→建议裁切→实际裁片→检查主关系/干扰→原生分组与整板。原品质只消费实际覆盖的当前目标，原生quality门完整重放，不沿用本地partial/basic直接放宽分支。
6. 独立板审能否决单张；少第10张、重复项目、有不能保留成员或版本身份变化均阻断。修ROI/补清楚同源/展示增强/替换后必须审当前实际版；原规则不为保留坏成员改写。三轮是同问题定点修订，模型失败不自动重发。
7. R5直接调用同事原CLI，固定gpt-6-sol/low/default/Fast关闭。不再额外注入DeepAgents Skill/Schema/用户Prompt。原答复、图片身份、实际调用及部分结果保留；旧DNA只复用实际known/at覆盖，不能借未知或旧品质给新目标。
8. CMF采用surface/same_object_interface；旧H007 paired-surfaces扩展不用于新原生链。历史4/5图板、H01提案和失败保持历史身份，不重标为新版通过。

## 当前入口

- `$prism-workflow`：工程总入口，路由同事17个Skill；旧`prism-trend-themes`、`user-research-design-clusterer`、`moodboard-generator`仅作兼容路由。
- 新配置草案：`ref/老师对接/最新完整流程1006/project.v2.json`，13方向为本项目既有范围，H01采用exploration/max20/选13；候选容量、预算未定，prepare-only，所有模型仍暂停。同一会话用户授予的设计代选准备权限记录为user_delegated_ai，不继承同事历史授权。
- DNA V2网页保留版式，显示冻结R5参数；历史结果仍能读取。
- 旧纯文本情绪板生成/续跑/执行及宿主发布入口停止；历史catalog/list/get/download为只读，初始化不重写queued/running档案。
- 网页通过 `/moodboards?native_run=<visual_workflow下相对目录>` 读取新原生结果，不启动模型。后端只读 `POST /api/v1/moodboards/native-results/preview`，实际重放原生门后才投影正式主题。坏清单返回可解释400，不生成任务。

原生运行目录放`web-handoff.json`：

```json
{
  "board_ref": {"path": "本机已保存board.json绝对路径", "sha256": "实际SHA"},
  "review_ref": {"path": "本机实际独立审阅文件绝对路径", "sha256": "实际SHA"},
  "native_module": "cmf",
  "native_arguments": {
    "grouping": "同事原生实际分组结果对象，不是这个模板字符串",
    "request": "原prepare_board_review的实际返回对象",
    "review_ref": {"path": "原生实际板审答复路径", "sha256": "实际SHA"}
  },
  "budget_exhausted": false
}
```

这只是形状示意，不能当回执。`board.json`须包含`project_identity_review_ref`，绑定实际10成员来源核实；缺资料或native门未闭合只能显示候选/未完成，不出现正式主题。旧结果没有这些新原生证据，不能仅改字段名声称迁移通过。

## 验证与边界

- 原包完整性273文件/17Skill通过；21个新/兼容入口结构验证通过。
- 同事原生8项检查组（doctor、冻结R5重放、用研、H01、辅助器、材料/复核、future-reference、ID/CMF alias）全通过，模型调用0。
- 68项受影响后端测试通过，包含真实裁片身份、10项目不足/来源弱证、离群成员否决、原生门、冻结模型/暂停、坏manifest、历史只读与旧入口停止；前端pnpm构建通过。
- 独立forward检查发现的坏manifest500与项目ID弱证均已修复并加回归。
- API服务已刷新；现场核验非冻结模型400、当前冻结R5提取409暂停、native不存在运行404，旧catalog执行supported=false。
- 未启动新模型、未重提8千图、未重跑13方向、未改写原视觉结果。历史200次请求仍195完成/5失败/0在途，暂停开关保持。离线通过不证明新审美准确率；实际视觉判断仍由真实阅读上下文完成。

旧执行源码与测试冻结在 `backend/tests/history/moodboards_pre_colleague_v2_20261006/`，扩展名`.py.txt`，附SHA，既不作为运行fallback，也不由pytest发现。迁移验证索引见本说明同目录的 `PRISM_COLLEAGUE_V2_PROJECT_MIGRATION_20261006.json`。
