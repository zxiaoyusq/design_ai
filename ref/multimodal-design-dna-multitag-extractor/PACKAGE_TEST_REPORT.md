# Package Test Report

测试日期：2026-09-14

## 结论

`multimodal-design-dna-multitag-extractor` 2.0.0 已将风格输出统一为真实候选，不再生成“已确认风格”、未分类状态、主次关系或确认门槛相关结构。模型输出观察协议为 `design_dna_multitag_observation_v2`，最终协议为 `design_dna_multitag_extraction_v1.2`。

## 当前契约

- 模型输出 `style_observations.candidate_tags`，宿主编译为 `style_result.style_candidates`。
- 每张图允许输出 0～5 个候选；每个候选必须具有非空的可见支持说明，可保留真实冲突说明。
- 候选按 `match_score` 降序、`style_id` 升序稳定排列，`rank`、中英文名、别名、类型和 facet 由宿主补全。
- 候选不再承担旧版 confirmed 的决定字段、独立辅助字段、颜色门槛、规则覆盖、dominance 或两两仲裁闭环。
- 命名组合预设只根据最终 `style_candidates[].style_id` 由 Python 确定性派生；组合不是额外确认结论，也不能反向创造候选。
- 没有像素支持时允许空候选，不能为了避免“未分类”而虚构标签。
- v1.1 历史结果不批量改写，业务转换和前端保持只读兼容。

## 推理负担变化

- 模型不再输出确认状态、规则计数、core/auxiliary 命中、候选镜像、dominance 和成对仲裁。
- confirmed 晋级专用的窄范围语义复核不再参与新候选链路；字段值与 Schema 的必要修复流程仍保留。
- 模型参考包去除了成对仲裁与确认门槛专用内容，由 58,321 字节降至 44,870 字节，减少约 23%。
- 排序、静态元数据、组合派生、统计和最终一致性继续由宿主程序完成。

## 自动化验证

- 3 个完整示例通过最终 Schema、注册表和语义校验。
- Skill 内部候选编译、空候选、稳定排序、非法候选移除及组合派生回归通过。
- 模型观察 Schema 与模型参考包均由生成脚本重建，避免手写产物漂移。
- Skill 10 项单元测试通过；工程后端 121 项测试及 76 个子测试通过。
- 前端 TypeScript 检查与 Vite 生产构建通过。

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
