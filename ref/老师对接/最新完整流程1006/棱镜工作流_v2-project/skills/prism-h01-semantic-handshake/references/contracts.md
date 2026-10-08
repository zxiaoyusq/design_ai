# H01 输入输出及选择

版本：Skill 1.0.0；来源为 `handshake_semantic_v2` 的 H01 与语义工作流合同。剥离了H02、图片解析、图片任务调度和案例专用修补。

## 配置

完整示例：[config.synthetic.json](../examples/config.synthetic.json)。路径相对配置文件；也接受绝对路径。

```json
{
  "research_dataset_path": "research-run/dataset",
  "research_run_path": "research-run",
  "trend_catalogue_path": "trend-catalogue.json",
  "trend_clusters_path": "trend-clusters.json",
  "brief": {
    "brief_id": "project-question-v1",
    "design_question": "希望探索的具体设计问题",
    "scope": "产品、对象、人群与当前证据范围"
  },
  "mode": "extension",
  "dataset_mode": "real_or_public",
  "max_directions": 12,
  "requested_selection_count": 5
}
```

max_directions 为1–20的有界候选上限；选择数量为1到上限之间的整数。这是一次调用的规模界限，不是自然类别数。候选不足时输出不足，不合成新依据。大范围研究可先按不同设计问题分批，但共同否定账和来源身份不能跨批丢失。

用研入口对应 `$prism-research-semantic-clustering` 输出。必须有原生八个数据文件及 clusters.json、handshake-input.json、analyst-proposal.json、handoff.json。程序重放原文到聚类的编译链，核查完整覆盖和原始否定，不信任摘要 supported 缓存。导入目录中的 `_methods` 不执行，只用Skill附带的可信校验器。

## 趋势入口

格式例子见 [趋势证据](../examples/trend-catalogue.synthetic.json) 和 [趋势簇](../examples/trend-clusters.synthetic.json)。趋势自身的语义聚类由上游提供，本 Skill 不把研究材料或图片补造成趋势证据。

- catalogue.articles：唯一 source_id 及来源元数据。
- catalogue.evidence：evidence_id、source_id、source_group_id、claim_origin_id、text、text_kind、locator、source_url、original_text_excerpt。
- text_kind：original_text、original_text_excerpt 或 source_paraphrase。释义的 original_text_excerpt 必须为空；不能把翻译/归纳改成逐字引用。
- clusters.schema_version：`prism.trends.semantic_clusters.v0.1`。
- 每个簇：cluster_id、title、definition、design_question、boundaries、evidence_refs、source_ids、source_group_ids、claim_origin_ids、hypotheses、unknowns、route_relevance。
- boundaries 包含 shared_design_mechanism、includes、excludes。来源组及原始主张ID从被引用证据中派生，转载不能伪装成独立来源。

可选 trend_associations_path 只承载来源图片关联，不能放DNA/质量结果。images 含 image_id、source_id、sha256、path、evidence_refs、association_role=`source_link_only`。图片像素不读取，不调用视觉模型，图片缺失不阻断H01。后续每块情绪板同来源组最多一张和约10张的要求由情绪板环节独立验收，本环节不证明满足。

## 模型提案

以每次生成的 response-schema.json 为准：request_snapshot、directions、negative_audit、双侧 cluster_coverage、overall_evidence_gaps。每个方向含具体问题、两侧簇/原文引用、relation_basis、共同设计原则、条件、假设、未决问题和建议分支。

本地规范schema与传输schema不同：仅对模型传输移除 uniqueItems 等不支持项；本地仍执行完整规范校验。禁止为了传输而丢弃本地唯一性验证。

当前源码三种关系：direct_support、anchored_extension、exploratory_hypothesis；适度延展和探索必须有非空 extension_explanation/hypotheses。overlap_candidate 至少有一条真正的直接设计表达；品牌或背景单独不足以支持它。

原始否定 × 所有候选形成完整审计矩阵。未聚类否定仍需逐候选审计；缺项直接拒绝。not_applicable 需要针对对象/场景的具体理由，程序无法判断理由是否真实，应保留语义审阅。

## 选择

先写 choices.json，例如：

```json
[{"direction_id":"D1","branches":["ID","CMF"]}]
```

生成待确认模板，再根据真实选择填写：

```text
python -B -X utf8 scripts/handshake.py selection-template --run h01-run --choices choices.json --out confirmation.json
python -B -X utf8 scripts/handshake.py select --run h01-run --choices choices.json --confirmation confirmation.json
```

confirmation 要有 `status=confirmed`、actor_kind、actor_id、source_ref，以及模板绑定的 candidate_digest、selection_digest。

- human_designer：真实设计师选择，保留实际回执来源。
- user_delegated_ai：用户明确让AI代选，必须有本次 current_scope_delegation_ref；不继承原项目/他人授权。
- synthetic_fixture：只允许合成数据的测试，不能批准真实方向。

程序验证绑定和完整性，不认证人类身份。当前用户已明确代选时无需再索要同一授权，但记录真实角色。仅提供参考文件不等于授权外发、发布、付费或图片生成。

## 输出与搬迁

prepared.json 绑定输入与引擎；inputs 是本轮冻结的数据副本；messages/schema 是模型输入；response.json 原样保存回答；accepted.json 带完整否定账和原始引用；candidate-directions.json 为候选；selection.json 为可追溯选择。

Skill本身可自由移到别的电脑；运行中的 prepared/accepted 绑定当时路径、字节哈希和代码版本。**已有运行换目录不能直接改路径继续接受旧快照**：用原资料在新位置 prepare 并重新完成提案绑定和验收，保留历史工件。离线 demo 会在任意新目录生成自己的快照。

局限：脚本只验证导入内容，不证明研究原话真实性、趋势热度、人物代表性、语义准确率、视觉一致性或量产效果。jsonschema 依赖须由使用者自己的环境提供，包内不含账号、密钥或额度重置权限。
