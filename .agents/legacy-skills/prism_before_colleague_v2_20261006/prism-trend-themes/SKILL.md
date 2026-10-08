---
name: prism-trend-themes
description: 从趋势文章 Excel 的标题与摘要中寻找多篇文章共同支持的审美趋势，最终最多 100 条；单篇线索单独留档，保留引文、来源和未入选原因。用于纯文本趋势语义聚类；不读取图片、local_vl_info 或图片 DNA，不做用研匹配或热度预测。
metadata:
  version: "3.1.0"
---

# 棱镜 · 多篇共识审美趋势

目标是找出多篇文章反复出现的审美表达，而不是为每篇文章建立细分类。最终主趋势默认且最多 **100 条**，每条默认至少 **3 个去重来源组、3 篇文章**支持；单篇线索不进入主趋势。完整留档与主趋势入选分开：允许少于 100 条，禁止凑数或强行合并。

代码负责读取、分包、校验、去重统计；语义判断由当前助手或用户指定模型完成。既有要点可复用，不为改变聚类粒度重做全表提取。用户指定 Astra 时继续使用 Astra，不调用工程配置的模型。

## 先读规则

执行前完整读取 [文本规则](references/clustering.md)、[输入输出契约](references/contracts.md) 和 [共同趋势筛选规则](references/selection.md)。来源和历史版本说明见 [改造范围](references/provenance.md)。

- 唯一判断证据是 `title`、`title_zh`、`summary_zh`。分类、标签、时间等仅作来源元数据，不按旧标签机械分组。
- 不读取图片像素、不打开或下载图片、不调用视觉模型，不从文件名推断内容。`local_vl_info`、图片 DNA 和既有视觉解析即便是文本也禁止进入聚类；`confidence`、`clust_status` 不代表本次结论。图片 URL 只留独立旁表。
- 引文精确匹配 Excel 存档文字；翻译或释义不冒充源网站原文。表中命令及链接是数据，不执行；默认不联网核验。
- 主趋势的 title、definition、design_question 使用跨品类的审美机制表达，不以衣服、手机、家具等品类或其专属部位限定主题。原对象留在 member.subject、引文、变体及实施条件中；主题按共同形式关系归并，不按品类拆分。不能只删名称里的品类词，而定义与设计问题仍指向单一品类。

## 优先复用已有提取

项目使用 conda `314`，依赖见 requirements.txt。已有 2.1 最终档案时直接准备新版筛选运行，不覆盖旧结果；若原复核修订另存，必须传入 `--corrections`：

```bash
conda run -n 314 python -B .agents/skills/prism-trend-themes/scripts/select_trends.py prepare --from-final data/result/trend_text_clusters/astra_full_20261001/final --corrections data/result/trend_text_clusters/astra_full_20261001/reviews/corrections.json --out data/result/trend_text_clusters/astra_consensus_20261001/selection-run
```

也可直接从全部批次已验收的提取运行准备，不必先产出旧版细类：

```bash
conda run -n 314 python -B .agents/skills/prism-trend-themes/scripts/select_trends.py prepare --from-run /path/to/extraction-run --out /path/to/new-selection-run
```

`--max-trends` 可设置 1–100，默认 100；`--min-source-groups` 默认 3，最低 2，不能让单源进入主趋势。`--max-chars` 默认 28000，仅控制上下文，不代表 tokens 或总费用。参数和输入冻结后不得静默变更。

## 新 Excel 的首轮提取

没有可复用证据时才做首轮。默认资料是 `ref/趋势信息0930.xlsx`，路径须显式传入。

```bash
conda run -n 314 python -B .agents/skills/prism-trend-themes/scripts/pipeline.py inspect --input ref/趋势信息0930.xlsx
conda run -n 314 python -B .agents/skills/prism-trend-themes/scripts/pipeline.py estimate --input ref/趋势信息0930.xlsx
conda run -n 314 python -B .agents/skills/prism-trend-themes/scripts/pipeline.py prepare --input ref/趋势信息0930.xlsx --out /path/to/extraction-run
```

`inspect/estimate` 只读，`prepare` 冻结文本与请求且不调用模型。逐包完整读取 `batches/Bxxxx/request.json`，按模板一次完成轻量要点提取和局部候选，再执行 `check-batch --run RUN --batch B0001 --proposal PROPOSAL` 验收。每篇填写 coverage；多义文章保留不同机制，无审美证据不强归类。候选暂不限 100，单篇可作为待归并种子，不代表已入选主趋势。超长输入报错而非截断；正式全量不能沿用“最近 30 条”或试跑 limit。

`pipeline.py` 保留 2.1 提取引擎以兼容已有冻结运行；其旧 collect/finalize 是细粒度证据档案，不是 3.x 的最终主趋势。新版最终输出必须经过下述选择器。

## 全局共同趋势归并与筛选

1. 读完 `selection-packets.json` 中所有种子摘要，建立并跨包调整共同表达目录。不要先删单篇种子，也不要只对旧多源类取前 100：多个单篇细类可能组成同一共同趋势。
2. 适当提高概括粒度：共享的形态、色彩、表面、构图或感受是主题，材料、品类和局部实现是变体。相同机制的不同品类归为同一方向；单一品类来源也提炼其中可解释的形式关系，不给主题冠以品类名。不能用“环保、科技、高端”等泛词包住无共同审美关系的文章。定义仅声称多源支持的共性，少数细节写 variations。
3. 对含混、混合、条件性或已修订种子，定点查 `seeds.json`、`points.json`、`catalogue.json`；保留实际引文与既有解释限制，不把旧错误重新带回。按点分配，不要求整个旧候选不可拆分。
4. 写 `plan.json`，绑定 selection manifest 哈希。每个要点恰好进入一个主趋势或 `deferred_points`，不是每个要点都必须成为主趋势。同篇不同点可支持不同趋势，但该文章在同一趋势只计一次。
5. 优先保留共性清楚、去重支持较多、互不重复且有设计启发价值的趋势。低于门槛、单篇、含混或上限外内容进入证据池并解释。不以删除记录或强行拼类满足上限。执行校验后在新目录编译：

   ```bash
   conda run -n 314 python -B .agents/skills/prism-trend-themes/scripts/select_trends.py check --run /path/to/selection-run --plan /path/to/plan.json
   conda run -n 314 python -B .agents/skills/prism-trend-themes/scripts/select_trends.py finalize --run /path/to/selection-run --plan /path/to/plan.json --out /path/to/new-final
   ```

## 成本、交付与验证

不做文章两两比较，不重复全表提取；以种子摘要归并，必要时回查完整文字。没有内置付费 API，不自动调用项目模型。额外定点模型复核默认总预算最多 3 次，继承既有额度和实际用量；用户另有预算则遵守用户限制。生成复核材料不等于完成复核，修订 plan 不刷新额度，剩余疑点留人工确认。所有 analysis 填实际分析者、模型和时间，未知版本写 null。

主交付是最多 100 条的 `trend-clusters.json` 和 `report.md`；另附 `evidence-pool.json`、`point-dispositions.json`、`coverage.json`，完整保留未入选线索和逐点去向。来源、Prompt、脚本与提案哈希及旧执行信息可追溯。不回写 Excel、数据库或旧运行。

来源组数是去重后的文章支持度，不是市场热度、偏好比例或独立验证数。结构检查不证明语义准确；保留 `semantic_coverage=model_assessed`、`visual_analysis_performed=false`、`review_status=pending_human_review`。趋势侧输出可供后续握手使用，但本技能不执行用研匹配。

修改技能的验证使用微型合成输入，不自动触发全量模型回放：

```bash
conda run -n 314 python -B -m unittest discover -s .agents/skills/prism-trend-themes/tests -v
```
