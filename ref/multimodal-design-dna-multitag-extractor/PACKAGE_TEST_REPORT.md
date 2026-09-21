# Package Test Report

测试日期：2026-09-15

## 结论

`multimodal-design-dna-multitag-extractor` 3.0.2 已移除独立不确定项协议，并可在严格校验前无损归一模型偶发生成的已知驼峰顶层别名。模型输出使用 `design_dna_multitag_observation_v3`，最终结果使用 `design_dna_multitag_extraction_v1.3`；低置信但有值的观察继续由字段自身 `confidence` 表达。

## 当前契约

- 模型不再输出 `uncertainties`，最终结果不再输出 `uncertain_fields`。
- 无值、不可见、不可计算、基础类型非法或缺少完整派生依赖的字段由宿主省略，原因保留在内部编译报告。
- 每张图允许输出 0～5 个有可见支持的同层风格候选；候选按 `match_score` 降序、`style_id` 升序稳定排列。
- `rank`、静态身份、模块、统计和组合预设由宿主确定性生成，不要求模型同步机械字段。
- `side` 保留“纯侧视但左右方向不确定”的真实语义；`ordinal_strength` 作为 `strength` 的明确键名别名，`low/medium/high` 分别受控映射到 `25/50/75`。
- 模型 Schema 的全部内部定义统一使用 snake_case；已知驼峰顶层键仅在不存在冲突的规范键时由宿主无损重命名。
- 结构化字段值已有非空 `value.description`、但漏写 `raw_visual_description` 时，宿主只复制该已有描述，不生成新内容。
- 只有一条证据的 inferred 字段由宿主省略并在编译报告留痕，不猜补第二条证据。
- 多标签业务视图升级为 v1.2。v1.1/v1.2 历史完整结果继续可读，但旧不确定项被兼容层忽略且不在页面展示。

## 推理负担变化

- 模型 Schema 删除不确定项字段和候选概率结构，由 22,840 字节降至 20,032 字节，减少约 12.3%。
- 当前预装 Skill 上下文为 122,247 字符；相较调整前快照 123,933 字符减少约 1.4%。
- 历史失败样本中该数组曾占模型紧凑 JSON 约 13%，因此图片实际输出的节省随不确定项数量变化；没有不确定项的图片主要只获得 Schema 上下文节省。
- 本次验证只做离线编译与假模型/既有夹具回归，没有新增真实模型调用。

## 自动化验证

- 3 个完整示例通过最终 Schema、注册表和语义校验。
- Skill 14 项单元测试通过，覆盖字段别名、描述复用、强度别名、低置信字段保留、无值字段省略、侧视、类型归一、派生依赖、保存与组合派生。
- 后端全量 129 项测试通过。
- 前端在 conda `314` 的 Node.js 22.23.2 / pnpm 11.19.0 下通过 TypeScript 检查与 Vite 生产构建。

## 关键命令

```bash
python scripts/validate_skill_package.py
python scripts/build_model_output_schema.py --check
python scripts/build_model_reference_bundle.py --check
python scripts/validate_output.py --warnings-as-errors examples/smartphone-rear.example.json
python scripts/validate_output.py --warnings-as-errors examples/smartphone-red-multitag.example.json
python scripts/validate_output.py --warnings-as-errors examples/apparel.example.json
python -m unittest discover -s tests
```
