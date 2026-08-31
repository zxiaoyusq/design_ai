# Package Test Report

测试日期：2026-08-30

## 已通过

- `SKILL.md` YAML frontmatter 可解析。
- Skill `name` 与父目录名一致，符合小写字母、数字、连字符命名约束。
- `description` 与 metadata 通过 Agent Skills 快速规范校验。
- `SKILL.md` 共 191 行，低于建议的 500 行。
- JSON Schema 通过 Draft 2020-12 元模式校验。
- 所有 Python 脚本通过语法编译检查。
- 手机示例通过 Schema 与语义校验。
- 服装示例通过 Schema 与语义校验。
- 完整结果通过 `save_result.py` 写入 `data/result/`，时间戳、图片名安全化、同名防覆盖与 0644 文件权限均通过测试。
- 工程业务视图脚本可从完整结果提取业务字段，并默认写入同目录的 `_business_view.json`。
- 包级自检脚本通过。
- 内置知识库与输入的 AI 审美 DNA 扩展版 Markdown SHA-256 完全一致。

## 校验命令

```bash
python scripts/validate_skill_package.py
python scripts/validate_output.py examples/smartphone-rear.example.json
python scripts/validate_output.py examples/apparel.example.json
python scripts/save_result.py examples/apparel.example.json --image sample.png
python ../../extract_design_dna_business_view.py ../../data/result/<完整结果文件名>.json
```
