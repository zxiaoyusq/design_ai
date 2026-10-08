# 给同事的使用说明

将整个`prism-dna-sol-r5`文件夹复制到项目的`.agents/skills/`。这是独立的解析skill，不需要此前10技能包的共享目录。

需要Python 3.12及可使用gpt-6-sol的Codex CLI。包内不带账号、密钥或登录状态。先在自己选择的Python环境安装依赖：

```text
python -m pip install -r .agents/skills/prism-dna-sol-r5/requirements.txt
```

从项目根执行。路径有空格时加双引号。

```text
python -B -X utf8 .agents/skills/prism-dna-sol-r5/scripts/cli.py doctor
python -B -X utf8 .agents/skills/prism-dna-sol-r5/scripts/cli.py self-test
```

doctor只检查本地CLI参数，不验证账号是否有该模型权限。找不到CLI时加`--codex "完整可执行文件路径"`。模型不可用或CLI配置不兼容时停止，不自动换模型、升档或回退Fast。

仅生成请求，不调用模型：

```text
python -B -X utf8 .agents/skills/prism-dna-sol-r5/scripts/cli.py parse --image "图片.png" --image-id IMG001 --out "outputs/r5-preview"
```

真正解析（会使用同事自己的模型额度）：

```text
python -B -X utf8 .agents/skills/prism-dna-sol-r5/scripts/cli.py parse --image "图片.png" --image-id IMG001 --out "outputs/r5-run-001" --execute
```

输出目录必须尚不存在。每个请求一次尝试；失败保留记录，不自动重启旧运行。未做定点复核的困难项保持pending。执行失败退出码2；有未决语义但调用成功时，结果状态partial不应误当程序崩溃。

可选补查：`--refine mixed-areas`只检查原区域名中并列多个部位的外观差异；`--refine optics`只检查有疑义的透明/透射字段。两者不能同时选择，最多增加一次调用；目标为空时不调用。它们来自R5实际试验的两种有界补查，并不保证每张新图都需要或受益。

## 输出怎么用

`result.json`保留：

- `local_features`：原字段p、值v、位置at、回复路径path和来源source。局部CMF以此判断同位置条件。
- `features`：图级按字段和值去重的索引，包含ID/CMF views、locations和provenance。适合图级召回，不证明不同部位属性共现。
- `pending`、`invalid`、`decisions`、`admission_adjustments`：不确定、程序拒绝、复核及显式纠正记录。
- 计数、图像哈希、模型配置、调用次数；全216视觉合格和人工准确率始终不自动宣称。

`calls/`中保留实际输入、schema、输出、事件与receipt；`call-ledger.json`记录尝试。`private-runtime-state`是执行时的本机CLI状态，转交结果时不要把它当算法资源发给别人。

## 验证口径

打包过程中只重放已保存的4图响应，核对局部特征、图级索引、pending、invalid和修正记录是否与冻结R5一致；没有新增模型解析。新机器的完整模型执行仍需同事在自己的环境中跑指定图片。

图片素材、原字典和原模型回复分别保存；examples目录不会被加入正式prompt。字段数接近Astra不等于准确率接近Astra。
