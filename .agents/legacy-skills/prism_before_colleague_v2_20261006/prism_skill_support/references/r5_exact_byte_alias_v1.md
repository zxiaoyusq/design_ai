# R5 精确字节任务 ID 别名

版本 `r5-exact-byte-alias-v1.0.0`，对应 `R5-EXACT-BYTE-ALIAS-001`。只修复同图、同版本识别结果因任务内 `image_id` 不同而不能复用的传输问题。

## 最小入口

```python
from prism_runtime.clustering.r5_exact_byte_alias_v1 import load_record, consumer

record = load_record(current_asset, original_R5_result_ref, quality_ref=None)
api = consumer("CMF")  # 冻结 CMF v4；consumer("ID") 为冻结 ID v5
p = api.prepare(brief_ref, manifest_ref, records, quality_bundles)
model_input = api.grouping_view(p)
shape = api.grouping_template(p)
g = api.accept_grouping(p, proposal_ref)
request = api.prepare_board_review(g, rendered_board_ref)
review_shape = api.board_review_template(g, request)
a = api.accept_board_review(g, request, review_ref)
```

整个生命周期继续使用同一个 `api`。它读取并执行哈希固定的原消费者源码，仅在独立私有包命名空间中把相对 `r5_dual_v2.adapter` 导入接到新 loader。原文件、原 `sys.modules` 条目及原函数全局均不替换。直接调用未包装的旧消费者仍会拒绝别名记录。

## 验证顺序与保留范围

1. 校验冻结依赖和原 result FileRef；当前 `asset.image_id` 与原 result `image_id` 均需明确。
2. 相同 ID 原样委托旧 loader，输出完全保持旧行为。
3. 不同 ID 只接受带完整执行元数据的 `prism.sol_r5.portable_result.v1`。当前图片实际 SHA、asset SHA、原 result SHA 必须完全一致；有 image_ref 时也校验其字节和路径。
4. 临时构造**校验用 asset**：当前 asset 的副本只把 image_id 设为原 result ID。以此调用原 loader，完整验证 R5 baseline、模型、effort、请求 tier、Fast、状态、局部事实与归一化结果。它不是伪造的历史 asset 或执行回执。
5. 只在派生传输记录中改变顶层 `image_id/asset`，增加 `task_image_id_alias` 并重算传输摘要。别名记录明确原 ID、当前 ID、完整 SHA、原 result FileRef、原校验记录 digest 和校验用 asset。

原 `observations`、观察 ID、`at/value/source/path`、image index、全部 pending/invalid/decisions/audit、producer metadata、原 status 和 result FileRef 均不变。观察 ID 原本由图片 SHA 和原始观察行决定，不因任务 ID 改名而改变。`partial` 继续是 partial，未知项原样保留；各消费者仍只使用自己分支内的干净已知事实。

别名模式要求 `quality_ref=None`。native selected-target quality v2 仍在 `quality_bundles` 中按当前 image/branch/target_digest 独立原样回放；不会搬运旧整图品质、跨 ID/CMF 范围或改 H01/负向。错误图、SHA、执行设置、算法版本、未知 schema、被改坏的原结果或别名元数据均拒绝。裁剪/缩放等像素变化不属于这个入口。

传输记录 digest 会变化。因此 Root 应以这份记录的 digest 正常构造当前目标对应与视图绑定，再 prepare；本模块不替换旧 binding、quality、target、proposal 或视觉回执。

## 真实案例与自评

交付目录 `real-case/inputs.json` 给出可直接加载的真实 current asset、原 result FileRef 和 asset 来源位置；`record.json` 是派生记录；`replay.json` 记录只读校验结论。

实际案例原 ID 是 `V5-ID02-A06-I08`，当前 ID 是 `V5IMG-64e4ff6277d0bd79d09a`，原图 SHA 为 `64e4ff6277d0bd79d09a23b9684a68e000f2c3c46de4ad220f5765a55f7d4620`。原 103 条局部观察、2 条 pending 和 partial 状态均保留。只读调用两个消费者原有的 record 校验/清洗路径，确认可以读取各自的事实；这没有重新评估目标品质或产生新的整板 PASS。

`build_delivery.py` 使用已有 Python/jsonschema vendor，运行本模块小范围回归并保存上述案例及哈希，只写本 owner 新交付目录。合成测试覆盖两个原消费者的 prepare→分组→整板审阅路径，并验证原品质结果和原全局函数不变。合成案例不是实际视觉成绩。

没有模型/网络/取图/渲染/图片修改/新任务/自动化调用；原结果中已有的 model_calls 仍属于原历史执行，不被改为零。源文件哈希在 `dependencies.json` 和交付 handoff 中；旧模块前后比对随交付保存。自评范围仅为精确字节 ID 别名兼容，不是新 DNA 算法、视觉准确率或六方向运行结果。
