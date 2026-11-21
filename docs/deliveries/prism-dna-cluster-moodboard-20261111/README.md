# 情绪板聚类 Skill 独立补齐包

日期：2026-11-11。正确名称为 `prism-dna-cluster-moodboard`（`cluster` 末尾有 `r`）。

## 核查结论

原始 `prism-five-modules-20261031.zip` **已包含此 Skill 的全部 48 个文件**，其中包含网页 `clustering.py` 动态加载的 `.agents/skills/prism-dna-cluster-moodboard/scripts/llm_group.py`，文件 SHA 与原交接清单一致。

截图中的 `idtrendanalysis` 是接收侧快照，本次没有该快照可供逐项检查，不能断定遗漏发生在哪一步。`.agents` 是隐藏目录，使用 `cp *` 或部分同步规则时可能漏传。本补齐包方便恢复该目录及关联依赖。

全部业务源码从原已脱敏 ZIP 原样提取，算法与模型默认值未改；来源提交为 `38e83d0b3405eecf27f41e103206c31607ca3337`。`SOURCE.json` 记录原包 SHA、文件来源和逐文件校验值。

## 包内内容

| 路径 | 用途 |
| --- | --- |
| `.agents/skills/prism-dna-cluster-moodboard/` | 完整聚类 Skill、规则、脚本、渲染与离线测试 |
| `.agents/skills/prism-design-dna-preparation/` | 聚类依赖的冻结设计卡读取与关系规则 |
| `ref/multimodal-design-dna-multitag-extractor/references/` | 3 份直接依赖：风格目录、DNA 知识库、提取协议 |
| `backend/app/agents/`、`backend/app/services/llm/` | 配套 DeepAgents 运行代码与统一网关配置；已有同版工程不必覆盖 |
| `requirements-skill.txt` | 以上 Python 执行链的直接依赖 |
| `verify_skill.py` | 不联网、不调用模型的文件与导入检查 |

这是已有五模块工程的补齐包，不是完整 Web 应用，也不含原始图片库、运行结果、数据库、`.env`、API Key、Token、登录密码或 Git 历史。`agents/openai.yaml` 是 Skill 展示元数据，不执行 Codex。

## 如何恢复到接收工程

目录必须保持在工程根目录下，和 `backend` 同级。不要放到 `backend/.agents`，也不要把目录改名为 `prism-dna-cluste-moodboard`。

```text
idtrendanalysis/
  .agents/skills/prism-dna-cluster-moodboard/scripts/llm_group.py
  .agents/skills/prism-design-dna-preparation/scripts/design_cards.py
  ref/multimodal-design-dna-multitag-extractor/references/...
  backend/app/agents/design_dna_preparation.py
  backend/app/services/llm/...
```

先解压到临时目录，再设置下面两个路径。在 Linux 上执行以下命令只补缺失文件，不覆盖接收方已有修改：

```bash
PRISM_PACKAGE=/解压路径/prism-dna-cluster-moodboard-20261111
PRISM_PROJECT=/工程路径/idtrendanalysis
mkdir -p "$PRISM_PROJECT/.agents/skills" "$PRISM_PROJECT/ref" "$PRISM_PROJECT/backend/app"
cp -R -n "$PRISM_PACKAGE/.agents/skills/." "$PRISM_PROJECT/.agents/skills/"
cp -R -n "$PRISM_PACKAGE/ref/." "$PRISM_PROJECT/ref/"
cp -R -n "$PRISM_PACKAGE/backend/app/." "$PRISM_PROJECT/backend/app/"
```

不要使用 `cp "$PRISM_PACKAGE"/* ...` 复制 Skill，它会漏掉隐藏的 `.agents`。也不要用本包局部 `backend` 目录替换整个工程后端。

如果文件已有但版本不同，下面的检查会列出差异路径。接收方需结合自己的改动合并，尤其是统一模型运行时；检查脚本不会自动覆盖。

## 环境与检查

使用 Python 3.14（本项目为 conda `314` 环境）。完整交接工程已有依赖时无需重复安装；独立环境可执行：

```bash
python -m pip install -r "$PRISM_PACKAGE/requirements-skill.txt"
python -B "$PRISM_PACKAGE/verify_skill.py"
python -B "$PRISM_PACKAGE/verify_skill.py" --project "$PRISM_PROJECT"
python -B "$PRISM_PROJECT/.agents/skills/prism-dna-cluster-moodboard/scripts/llm_group.py" --help
```

`verify_skill.py` 检查包内 SHA、接收工程文件是否缺失/不同、聚类动态导入、38 个风格规则与 DeepAgents 默认配置，不读取模型密钥，也不发出网络请求。离线检查通过说明依赖已补齐，不能替代真实数据与模型效果验证。

模型默认使用 **DeepAgents + `gemini-3.8-flash`**，通过工程统一网关 SDK 调用，不依赖 Codex CLI 或个人 ChatGPT 登录。真实执行前由接收方设置自己的 `LLM_URL` 和 `LLM_KEY`（环境变量，或工程 `backend/.env`）；网关需提供相应模型及兼容接口。本包没有预配置凭据。

输入为已冻结的设计卡、对应原图和来源证据。聚类运行参数见 `llm_group.py --help` 及 `SKILL.md`；先检查计划与预算，显式 `--execute` 才进行模型执行。已有原始输入路径迁移后需重新绑定并校验 SHA，不能仅修改结果记录伪装成新运行。

## 可选工具边界

- `prepare_pool.py` 的默认路径来自历史业务素材；本包不提供这些图片或数据，接收方需指定自己的输入。
- `capture_boards.cjs` 用于浏览器截图，额外需要 Node.js、Playwright 和浏览器。运行时传入 `--playwright <接收方本机 Playwright 模块绝对路径>`，不要使用源码中的历史临时路径；它不影响网页聚类主入口。
- 本次仅做离线导入、规则读取、假模型测试和凭据检查，未运行真实模型、未验证接收方 `idtrendanalysis` 的完整业务流程。具体结果见 `VERIFICATION.json`。

包内 `MANIFEST.json` 覆盖所有交付文件（不列自身），压缩包另附 SHA-256。
