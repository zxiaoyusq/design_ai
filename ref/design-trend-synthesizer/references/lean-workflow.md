# 3.0轻量执行

默认入口`scripts/pipeline.py`，也可直接使用`scripts/lean.py`。仅依赖Python标准库，复用日期、文件保存与图片定位工具；2.x严格契约不参与新模型回复接收。

## 自动推进

准备时声明实际模型，例如：

```bash
python SKILL_DIR/scripts/pipeline.py prepare \
  --trends PROJECT/data/trend_data/trends.json \
  --users PROJECT/data/userreseach_data/users.json \
  --project-root PROJECT --start-date YYYY-MM-DD --end-date YYYY-MM-DD \
  --model ACTUAL_MODEL --model-parameters '{"temperature":0}'

python SKILL_DIR/scripts/pipeline.py run --run RUN \
  --adapter-command-json '["python","/absolute/path/to/adapter.py"]'
```

本项目可直接用backend/scripts/design_trend_model_adapter.py；命令数组中的python换成实际base环境Python绝对路径。适配器管理连接配置，不把密钥写进Skill或Prompt。默认不向model_profile注入max_tokens，输出预算预估为null（未设置），由模型服务或SDK默认行为决定。仅显式提供阶段输出预算或模型参数max_tokens时保留相应限制。

适配器接收`--request FILE --result FILE`，请求含纯文本messages和model_profile。成功结果如下，模型正文无需JSON：

```json
{"status":"ok","raw_response":"## 柔和触感\n设计归纳。[T00001 U000001]","model":"实际模型","input_tokens":1200,"output_tokens":300}
```

用量可为null。服务错误用status=error及category：overload/rate_limit/timeout/transport/authentication/permanent，可附retry_after_seconds。适配器内部关闭自动重试。

脚本自动串行推进。服务错误最多重试一次，失败计入max-calls；额度跨续跑保留。较长Retry-After保存到期时间并退出，认证或永久错误停止派发。格式不齐、未知引用和空正文不触发模型纠错。总预算为最终成稿保留一次名额，未处理包标明缺口；无可用笔记不继续成稿。SIGTERM/SIGINT停止新派发并保存当前调用。

## 文件与统计

- manifest.json：来源、日期、用户范围、模型及计划预算。
- sources.json：原始文本与图片索引；requests/和accepted/保存请求与普通文字回复，notes.json保存方向编号映射。
- calls/：实际调用原始留痕；performance_report.json记录调用数、耗时、用量。缓存原调用不重复计入本轮，缺失值不当作零。
- high_potential_trends.json/jsonl和report.md：最终归纳；原文只通过sources.json定位。
- image_paths.md：第一部分汇总最终结果关联的图片路径，第二部分汇总全部用户来源明确提及、且与第一部分去重后的图片路径；两部分内部按规范化绝对路径去重，不读取图片。
- completion.json：complete/partial/empty及has_content。partial可以交付但要说明缺口；empty不是完成研究。文件存在或退出码0不能替代状态检查。

status只返回简短状态；next最多生成一次综合任务。不要在宿主反复加载全部日志或扫描会话Token事件。常规运行在完成时读取性能摘要，用户另问宿主用量再单独核对。

方向笔记缓存位于项目data/result/high_trend/_lean_cache/，按实际消息、模型配置和3.0规则匹配。最后综合仍使用当前两侧笔记。未声明模型或指定--no-cache则关闭；不混用2.x观察缓存。

## 验证和兼容

验证只用1–2条趋势、2–3位用户的少量代表回答；直出、分包、缺图、预算和服务失败都用微型夹具/假适配器检查。不要为了证明效果重新跑前20用户或全量模型调用。

pipeline.py legacy显式调用旧实现；旧manifest的status/next/accept自动兼容。旧core.VERSION保持2.3，3.0单独记版本，不改变历史任务和缓存键。
