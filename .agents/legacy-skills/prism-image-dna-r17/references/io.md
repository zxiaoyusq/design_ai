# 棱镜 · 图片DNA与局部CMF：输入输出与实现

当前可继承范围：120张已实际提取；90张仅局部CMF可用，完整216项视觉正确性未验证。

输入：唯一原图、image_id、SHA256、来源manifest、冻结字典/生产者、原始模型回复及真实调用记录。输出：完整原回复、normalized或明确的recovered_partial_ledger、程序审计、独立review、cmf.image-dna.json与未决项。

在完整项目环境运行（输出必须新建）：

```text
python -B -X utf8 -m prism_runtime.dna.local_cmf_v1_2 prepare --image IMAGE --image-id ID --source-kind trend --source-provenance-ref MANIFEST --output-dir NEW_DIR
python -B -X utf8 -m prism_runtime.dna.local_cmf_v1_2 accept --prepared-dir NEW_DIR --raw-output EXISTING_RAW --run-record EXISTING_RECORD
python -B -X utf8 -m prism_runtime.dna.local_cmf_v1_2 accept-review --prepared-dir NEW_DIR --raw-output REVIEW_RAW --run-record REVIEW_RECORD
python -B -X utf8 -m prism_runtime.dna.local_cmf_v1_2 verify --path NEW_DIR/cmf.image-dna.json
```

本包保存源码、原字典及冻结源副本；旧回执仍绑定原路径和哈希。完整prepare/accept在新机器搬迁尚未全面验证，先检查源冻结依赖，不允许从原电脑静默回读。完整交接包可提供原运行布局和120图原件。

历史结果：90局部可用、19视觉/归属未放行、11编码/结构阻断。此分布是一次样本结果，不是准确率或每次必须达到的配额。

## 配套资料

- [capabilities.md](../../../../prism_skill_support/docs/capabilities.md)
- [冻结实现：dna/local_cmf_v1_2/README.md](../../../../prism_skill_support/runtime/prism_runtime/dna/local_cmf_v1_2/README.md)
- [冻结实现：dna/local_cmf_v1_1/README.md](../../../../prism_skill_support/runtime/prism_runtime/dna/local_cmf_v1_1/README.md)
- [冻结实现：dna/local_cmf_v1/README.md](../../../../prism_skill_support/runtime/prism_runtime/dna/local_cmf_v1/README.md)
