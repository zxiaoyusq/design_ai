# 棱镜 · 当前 HTML 截图可放大版 PPT

文件：`棱镜-产品路演-截图可放大版-20261026.pptx`。

- 当前 HTML 的 13 页全部保留：9 页主讲、4 页备用问答。
- 每页为 3200×1800 原页面截图，完整铺满 16:9 画布；不重排文字，不更换配色或图片。
- 在幻灯片放映模式下，点击第 4 页的“真实素材”或“专业关系”图片，即可打开相应原图的放大页。
- 点击放大图或右上角“返回第 4 页”按钮即可返回，之后正常翻到第 5 页。
- 编辑视图会看到共 15 页；最后两页为隐藏放大页，正常顺序放映会跳过。无需删除或取消隐藏。
- 原图与跳转全部内嵌，无需原 HTML、外网、外部图片或宏。其余页面中的 HTML 按钮和动效在截图版里为静态画面。

旧文件 `棱镜-产品路演-原页面截图版-20261026.pptx` 保留，不是此次最新导出。此前 HTML 与讲稿 ZIP 未重建；本次新版 PPT 单独交付。

## 复建与检查

原 HTML 未修改。逐页截图、两张放大原图、来源 SHA 和点击区域记录在 `ppt-screenshots-dark-zoom-20261026/`；`export.json` 记录 PPT 哈希及检查结果。

```bash
node docs/deliveries/prism-product-roadshow-20261022/source/capture_slides.cjs \
  docs/deliveries/prism-product-roadshow-20261022/index.html \
  docs/deliveries/prism-product-roadshow-20261022/ppt-screenshots-dark-zoom-20261026 \
  /tmp/bubble-ui-check/node_modules/playwright

/root/miniconda3/envs/314/bin/python docs/deliveries/prism-product-roadshow-20261022/source/export_pptx.py \
  docs/deliveries/prism-product-roadshow-20261022/ppt-screenshots-dark-zoom-20261026 \
  docs/deliveries/prism-product-roadshow-20261022/棱镜-产品路演-截图可放大版-20261026.pptx \
  --zoom-slide4
```

已检查原截图及两张原图字节一致、无裁切、点击范围与真实 HTML 按钮对应、两张放大页隐藏、两条放大跳转及四条返回跳转正确。LibreOffice Impress 可读取并渲染；临时取消隐藏的检查副本导出后，六条内部跳转均解析到预期页。检查副本不用于交付。
