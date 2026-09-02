---
name: multimodal-design-dna-multitag-extractor
description: 仅在用户点名本 Skill，或明确要求扁平、多标签、无主次或组合风格时，从单张图片提取可追溯的同层风格标签与设计 DNA；普通设计 DNA 提取继续使用原版 Skill。
metadata:
  author: "AI审美洞察项目"
  version: "1.3.0"
  language: "zh-CN"
  schema-version: "design_dna_multitag_extraction_v1.1"
  knowledge-base-version: "4.1"
---

# Multimodal Design DNA Multitag Extractor

## 任务边界

本 Skill 从恰好一张图片中选择一个主物品，先提取适用品类的规范 DNA，再输出零到三个可共存的扁平风格标签及其强度、证据和组合关系，并发现知识库外新 DNA 候选。

不要用于多物品比较、多图聚合、图片生成或纯文本设计咨询。不得从像素断言真实尺寸、成分、重量、触感或耐久性；图片缺失或不可读时停止。

## 执行前加载

若宿主已把本 Skill、执行协议、模型参考包、知识库、适配规则和模型 Schema 作为带版本的完整系统前缀注入，则直接使用该快照，不再通过工具逐文件重复读取；未预装时按下列顺序读取。

1. 模型阶段只读取 `references/extraction-protocol.zh-CN.md`；`references/output-contract.zh-CN.md` 供宿主后处理和最终校验使用。
2. 模型阶段读取 `schemas/design-dna-model-output.schema.json`，只输出 `design_dna_multitag_observation_v1` 精简观察结构；最终结果由宿主编译并按 `schemas/design-dna-output.schema.json` 校验。
3. 模型读取 `references/model-reference-bundle.json` 中的全部活动候选、字段 allowlist、关系、依赖及规范字段类型；不得重复读取宿主专用的完整 `style-registry.json`、`tag-relations.json`、`field-registry.json`，也不得读取组合预设。用 `references/knowledge-index.zh-CN.md` 定位品类字段值域、全部候选规则及相关混淆记录。
4. 跨品类时读取 `references/category-adaptation.zh-CN.md`；出现知识库外元素时再读取 `references/novel-dna-governance.zh-CN.md`。

## 核心工作流

### 1. 锁定主体与图像质量

按视觉焦点、面积、完整度和展示意图选择一个主物品，输出归一化包围框。背景、人物、支架、包装、UI、水印、倒影及其他物品不得进入主体 DNA。

记录视角、可见区域及图像干扰；颜色和材质可靠度属于输入质量，不属于产品 DNA。

### 2. 先提取可观察 DNA

先确定品类与 `active_profiles`，再判断字段适用性。当前单图只允许 `core` 与有对象依据的单视图 profile，不激活 multi-face、reference 或 trend profile。

- `applicability_status` 只表示品类适用性；
- `observability` 只表示输入是否可见；
- `evidence_mode` 固定说明结论来源；
- `computation_status` 只表示计算状态；
- 确认不存在时使用字段值域内的“无”或空列表，不借用状态表达。

先完成规范 DNA，再用决定锚点召回风格；当前模型固定输出空的旧兼容维度槽。

### 3. 独立判定扁平风格标签

结果不输出一级、二级、主风格或次风格。每个 `style_id` 都是同层标签，只有同时满足以下条件才可进入 `style_tags`：

1. 硬门槛通过；
2. 命中至少一个决定锚点；
3. 命中至少一个不同字段、区域或视觉机制的辅助证据；
4. 未命中硬排除；
5. required 颜色通过；
6. `confidence >= 0.75`；
7. `applicable_rule_count>=1` 且 `passed_rule_count>=1`；
8. 与其他返回标签完成成对关系核对。

`style_tags` 只包含已确认标签，数量为 0～3；多标签不是目标，不得为凑数添加。每个新增标签须有自身决定证据，不能仅重复另一标签的同一物理现象。

KB 4.1 有 38 个活动标签：37 个 `atomic`，仅 `MysticOrganic` 为 `composite`。`TribeIdentity` 已废弃，不得进入标签或候选；可见文字/图标、身份显性度和经参考确认的实体分别记录到 `IDG-05`、`IDG-07`、`IDG-09`，身份信息不产生风格标签。

`match_score` 表示规则匹配度，`confidence` 表示结论正确概率，`dominance` 表示已确认标签之间的相对视觉主导度，三者不得混用。单标签 dominance 固定为 1；多标签之和应约为 1。`style_tags` 严格按 `(-dominance, -match_score, style_id)` 排序。

对每一对返回标签写入 `pairwise_arbitrations`，并按字典序满足 `style_id_a < style_id_b`；关系与作用域取 `tag-relations.json`，最终决策必须为 `coexist`。硬冲突或排他关系成立时不能同时返回；边界不可观察时，相关风格只进入 `candidate_ranking`。导航分组、检索 facet 与混淆组属于注册表元数据，不进入结果层级。

`conditional` 同区冲突 facet 按 `same_region_coexistence` 仲裁：`forbidden` 必拒；`independent_evidence` 仅在双方有独占核心字段、独占字段证据且仲裁同时引用两侧独占证据时共存。

关系依赖按 `target_quantifier="any|all"` 检查：`requires` 必须由相应数量的已确认目标满足；`implies` 只召回相应目标进入完整候选排序，目标仍须独立硬判。

### 4. 组合摘要、候选与不确定项

`composition_summary` 只概括已确认标签如何分布于主体区域及如何共同构成视觉，不得创造新标签或替代规则证据。没有已确认标签时说明未分类或暂定原因。

最终 `candidate_ranking` 由宿主完成排序并加入 confirmed 镜像；模型只输出 provisional/rejected 候选。若非 confirmed 候选仍通过自身门槛，表示因标签对冲突而降级，`main_conflicts` 必须非空。置信度低于 0.75、决定边界不可见或字段不可计算时写入 `uncertainties`，并携带可观察性、置信度和原始证据；宿主可据此生成缺失的低置信设计字段，模型无需在两个数组重复维护同一记录。

完成既有字段映射后，才可提出 `new_module`、`new_field`、`new_enum_value` 或 `new_relation_rule`；候选必须可观察、可复用、可参数化，并与已有字段去重。

### 5. 证据与输出

证据必须位于主体框内并只描述可见事实。证据、设计元素及风格 `regions` 只能使用 `target_object.visible_regions` 中的值或 `whole_object`。每个观察字段至少引用一条证据；已计算推断字段至少引用两条独立观察证据；每个风格标签必须引用其硬判所用的规范字段与证据。

模型只返回符合 `design-dna-model-output.schema.json` 的精简观察 JSON。字段与风格静态元数据、模块清单、统计值、排序、confirmed 候选镜像和可由已有规范字段推导的证据闭环均不得重复生成。宿主先运行 `scripts/compile_model_output.py` 编译完整结构，再由 `scripts/save_result.py` 写入 `derived_style_presets` 并按最终 Schema 校验。宿主不得利用编译步骤发明视觉事实、改变风格硬判或伪造缺失证据。

最终结果只包含 JSON，不附加 Markdown、解释、路径或思考过程，禁止 `NaN` 与 `Infinity`。

## 确定性校验

```bash
python scripts/compile_model_output.py model_observation.json > compiled_result.json
python scripts/derive_style_presets.py compiled_result.json --output result.json
python scripts/validate_output.py result.json
```

传统宿主需要合并上下文时运行：

```bash
python scripts/build_prompt_bundle.py --output prompt_bundle.txt
```

校验失败时只修复结构或语义错误，不改变有证据支持的视觉事实。

## 支持文件

- 执行协议：`references/extraction-protocol.zh-CN.md`
- 输出合同：`references/output-contract.zh-CN.md`
- 知识库：`references/design-dna-knowledge-base.zh-CN.md`
- 宿主校验使用的完整风格、关系与字段：`references/style-registry.json`、`references/tag-relations.json`、`references/field-registry.json`
- 模型精简召回与关系索引：`references/model-reference-bundle.json`
- 宿主专用组合派生规则：`references/style-combination-presets.json`
- 品类适配与新 DNA：`references/category-adaptation.zh-CN.md`、`references/novel-dna-governance.zh-CN.md`
- 模型/最终 JSON Schema：`schemas/design-dna-model-output.schema.json`、`schemas/design-dna-output.schema.json`
- 组合派生器：`scripts/derive_style_presets.py`
- 模型观察编译器：`scripts/compile_model_output.py`
- 结果校验器：`scripts/validate_output.py`
- 评测：`evals/rubric.zh-CN.md`、`evals/cases.jsonl`
