---
name: user-research-ppt-json-importer
description: 将单个用户已填写的调研 PPT 中有问有答的内容、图片证据和喜欢/不喜欢选择补录到用户研究 JSON。适用于用户指定一个 PPT 与目标用户的增量导入；不用于批量猜测空白模板答案或修改 PPT。
---

# 单用户调研 PPT 补录

把语义判断与确定性写入分开。先确认 PPT 中哪些内容确实由用户填写，再用导入脚本完成图片提取、JSON 合并和校验。

## 必须遵守的边界

- 只补录同时存在问题和用户回答的内容。图片选择、排序或填入的参考图可以作为回答；只有主持人问题、备注或空白占位符的页面不得录入。
- 演讲者备注默认视为主持人提示，除非有明确证据表明它记录的是用户原话。
- 优先提取 PPT 内嵌原图。组合截图保持为一张图，并标记 `group_composite`；不要为方便而从整页截图中伪造单图。
- 只有 PPT 明确表达喜欢或不喜欢时才写 `ENJOY` 或 `DISLIKE`。用于解释概念但未表达偏好的图片写 `REFERENCE`。
- 保留缺图选择。如果 PPT 写了图片编号但实际没有图片对象，在 `ref_pic_links` 中写 `missing_source_image`，不要删除该回答或虚构文件。
- 不修改其他用户、原始调研记录或其他来源的补录。相同 `source_file` 的重复执行必须幂等。

## 工作流

1. 运行 `scripts/inspect_user_ppt.py` 生成逐页文本、备注及图片形状路径清单，并使用演示文稿渲染工具查看整套缩略图。默认只展开编号冲突、缺图、情绪边界或自动校验失败的关键页；不要逐张打开全部图片。
2. 逐页判断问题、实际回答、图片情绪和图片编号。排除只有追问、模板提示或复用前页选择的页面。
3. 按 [导入清单格式](references/manifest-schema.md) 创建 manifest。问题和回答应翻译为目标 JSON 使用的语言，但不要增加 PPT 没有表达的理由。
4. 运行 `scripts/import_user_ppt.py`。脚本会提取原图、创建 `ref_pic` 和 `ref_pic_links`、合并图片偏好、更新来源元数据和全局计数。
5. 检查脚本摘要，并按图片类型、边界编号和异常项做少量代表性抽查，不做全量逐图查看：
   - 所有本地路径存在且图片可读取；
   - 图片编号与 PPT 的视觉顺序一致；
   - 喜欢、不喜欢和参考图未混淆；
   - 每条补录记录都有非空问题和回答；
   - 缺图项明确标记且没有伪造路径。

## 运行方式

使用包含 `python-pptx` 与 Pillow 的 Python 环境：

```bash
python scripts/inspect_user_ppt.py --ppt INPUT.pptx --output inventory.json
python scripts/import_user_ppt.py \
  --ppt INPUT.pptx \
  --json users_selected.json \
  --user-name "User Name" \
  --manifest import_manifest.json
```

`manifest` 是语义审核入口。未经视觉核对，不要仅按 PPT XML 中的形状顺序推断编号。
