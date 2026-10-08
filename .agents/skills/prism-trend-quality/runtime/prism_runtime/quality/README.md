# 棱镜高级感：离线路由、既有结果导出与有界复核规则

当前算法：`cmf-reference-signal-cascade-v0.6.0`。接口遵守 `prism_runtime/CONTRACT.md` v0.1。

本模块可离线运行，不读取密钥、不访问网络、不重跑 DNA、不重新计算历史模型判定。`adapter.py` 导出保存过的原判定，`policy.py` 对已保存的首次与复核响应执行固定组合规则。它们不包含自动模型调用器或生产入库写操作。

## 来源路由

来源类别由上游真实 provenance 指定，不能根据图片外观、后缀或目录猜测。

| source_kind | 默认行为 | calibration_only=True |
| --- | --- | --- |
| trend | 导出有效 TrendQualityDecision | 同左 |
| research / generated / unknown / synthetic | not_applicable，不读结果，不调用 loader | 仍绕过 |
| calibration | not_applicable | 仅校准导出，applicable=false，保留 calibration |

合成夹具可以模拟 `source_kind=trend`，但 `provenance.mode=synthetic` 会保留；`production_admission=false`。未经来源核实的材料不可自行改成趋势来源。

`PASS/FAIL` 只表达有效的视觉判定。HTTP 错误、无效 JSON、模型空数组、缺必需字段、版本或身份冲突会返回 `decision=null` 与明确错误状态。不得据此送入审美淘汰库。

## 接口

工作目录：`D:/Codex/传音AI创客营`。下文 `python` 可替换成本机可用运行时：`C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`。

```python
from prism_runtime.quality import adapt_file, route_quality

result = adapt_file(
    image={"image_id": "upstream-stable-id", "source_kind": "trend"},
    result_path="absolute/path/to/existing-result.json",
)
# result_loader 是离线读取回调。非趋势输入不会调用此回调。
result = route_quality(image, result_loader, source_ref="absolute/original-result.json")
```

```powershell
python -B -X utf8 -m prism_runtime.quality `
  --image outputs/prism-algorithm-loop-20260926/modules/quality/examples/current-calibration-pass-input.json `
  --result outputs/prism-quality-pilot-20260926/designer-boards-round2-v06/resolved/B08-T04.json `
  --calibration-only
```

CLI 打印完整结果。`--out` 采用独占创建，拒绝覆盖旧输出。有效导出或不适用退出码 0，错误退出码 2。旧 v0.4 记录若没有版本，必须用 `--rubric-version` 给出其原始版本；不得默认套用当前版本。

输入可为 ImageDNA 全记录或含 `image_id/source_kind/provenance` 的子集；不消费其 DNA 特征。输出保留原 `image_id`，不同身份必须由上游提供明确映射，不能静默换号。`source_ref`、SHA-256、原版本、证据和原话均可追溯。历史有效 FAIL 不会在导出时被当前规则重新解释成 PASS。

完整输入输出示例见 `outputs/prism-algorithm-loop-20260926/modules/quality/examples-index.json`：4 个真实已保存的校准记录（含首次 FAIL 与无效输出）、3 个绕过案例、2 个显式合成的趋势 PASS/FAIL 夹具。示例 ImageDNA 子集不是新的 DNA 解析结果。

## v0.6.0 判标规则

1. 沿用 v0.5.2 的首次观察与二分类，不打分；可见的 CMF / 形体关系是依据。
2. 首次有效 PASS 保留。首次有效 FAIL 中，仅当 `design_reference=true`、`signal_level=basic`、有具体 evidence、可读且无 veto 时，允许一次独立图像复核。图像、固定提示词之外不提供设计师标签、身份或首次结论。
3. 首次 HTTP 200 但模型格式无效时，也只允许一次明确记录的补查。网络、授权、限流失败不自动重试。
4. 复核有效则依据同一二分类条件输出；复核仍无效则保留异常。最多两次请求，所有尝试保留。离线模块本身不发送任何请求。
5. 拼图独立判定与子图判定并列保存；整板 PASS 不能覆盖任何子图 FAIL 或异常。`aggregate_children` 有未决子图时返回 incomplete。

修正明确了 `distinct` 表示“明确可辨”而非“稀有原创”，补足装饰、强色彩、手工、透明材质、虹彩、仿生结构等风格覆盖；常见品类与商品摄影不能单独成为拒绝理由。没有按图片编号、品牌或设计师标签开白名单。

冻结提示词、参数与纯规则模块入口位于：

- `outputs/prism-quality-pilot-20260926/designer-boards-round2-v06/RELEASE.json`
- 首次：`outputs/prism-quality-pilot-20260926/designer-boards-round2/prompt-v0.5.txt`
- 复核：`outputs/prism-quality-pilot-20260926/designer-boards-round2-v06/prompt-v0.5.txt`
- 模型参数：Qwen3.8 Flash，temperature=0，enable_thinking=false，max_tokens=1400，JSON 对象输出。

## 实测与复跑

```powershell
python -B -X utf8 -m prism_runtime.quality.export_examples
python -B -X utf8 -m prism_runtime.quality.verify
```

这两条命令只读既有模型结果，不需要 API。验证覆盖来源绕过、身份/版本保真、执行错误区别于 FAIL、历史判定不被重写、复核次数边界及整板不能遮蔽子图。`verification.json` 记录实际测试结果和示例对照。

真实本组：16 张设计师拼图确定性拆成 103 个参考画面，119 次首次调用得到 115 PASS、1 FAIL、3 无效数组。显式补查4项全部 PASS；另1个未标定白T恤边界探针仍 FAIL。最终 16/16 整板、103/103 子图通过。合计124次既有校准调用、193708 tokens；这些不是接口或 loop 的新增调用。

旧 EE1 的138张设计师正例使用保存响应离线回归，138/138保持通过，新增调用0。并未把离线回放说成新提示词的全量再次推理。

## 自评与限制

接口范围合格：16项离线测试、9个完整输入输出示例复现通过；来源边界、错误状态和原判定保留已检验。算法整体状态为 **partial**：设计师正例的低误拒校准可用，但没有设计师负例及独立盲测，尚不能证明高级感判别的精确率、负例拦截率或多次运行稳定性。

旧138张和本组均已参与规则调整，不是独立留出集；本组在首次测试前已被明确标为正例。103个画面继承用户对设计师整组的确认，包含一些原本就在同一画面内的多物体组合。

首次1个误拒和3个无效输出永久保留。复核后的白T恤理由仍出现“独特/创新”措辞，提示词偏差可能残留。模型关于细金属丝、材质与表面工艺的描述是图像判断，未经实物验证；报告保留原话，不把它们转成制造事实。

前端交付是 `designer-boards-round2-v06/report.html` 逐图报告，无生产应用改动。上游输入清单、裁切坐标与哈希在 `designer-boards-round2/manifest.json`；下游只消费有明确 provenance 的导出结果。研究图绕过，校准记录不进正式趋势分库；正式图库与淘汰库未修改。EE1旧跟进仍 PAUSED。
