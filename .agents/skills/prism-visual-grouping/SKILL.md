---
name: prism-visual-grouping
description: 对冻结选材条件和已复核真实视窗按ID整体或CMF表面分支做原生视觉选组，保留候选去向、来源和负向；用于组成待审板，不代替独立整板验收。
metadata:
  version: "2.1.0-project"
---

# 棱镜｜视觉选组

合并原 ID / CMF 情绪卡的业务入口，按显式 branch 选择原生算法；两种比较标准、证据字段和接受门保持独立，不能混成同一模型判断。

## 输入与输出

输入：显式 ID / CMF 分支、冻结 brief 和候选 manifest、原 R5 已知观察及原位置、当前目标绑定、原生 quality bundles、真实原图/裁片及读图记录、来源与项目身份、完整负向及未决义务。

输出：对应分支的原生 prepared 和 grouping、精选成员及共同关系、全候选排除/待定原因、数量和独立来源缺口、待整板审阅资料。分组通过不等于整板通过；字段和交接见 [输入输出与交接](references/io-contract.md)。

## 分支和接受门

- **ID**：读取 [ID 分支](references/id-grouping.md)，使用 `id-reference-board-v5` 比当前声明状态的整件轮廓、比例与结构。局部材料特征、同颜色、同功能或同品牌不能替代整件关系。
- **CMF**：读取 [CMF 分支](references/cmf-grouping.md)，使用 `cmf-reference-board-v4` 比当前同一声明表面，或同一物件真实相邻界面；保持局部尺度可比，不跨对象拼色/纹理/光感，不推断材料成分或触感。

对本次分支通过共享 [原生接口](../prism_skill_support/references/native-api.md) 执行 `prepare → grouping_view / grouping_template → 实际提案 → accept_grouping`。模板只是字段形状；提案必须来自真实读取当前图像和上下游证据。prepare 重放完整上游，不信缓存 supported 或把合成夹具改标真实资料。需要同字节别名时，alias-id / alias-cmf 贯穿完整组板与板审链。

完整保留所有冻结候选的去向；不能暗中把广候选池再缩成几张。最终数量来自项目合同，本项目为 **10 张合格图片、10 个可核实独立项目**，同文章/同已识别项目最多一张。项目身份未知是证据缺口，不按不同 URL 认定独立；不足保持未完成，不能以降低一致性凑数。

单张合格仍可能成为整板离群项。实际裁片若主关系不突出，返回 `$prism-reference-image-preparation` 调整或换图，并复核受影响范围，不能改已冻结条件。负向、未来产品义务和范围限制原样携带；原生引用缺口保留失败，必要时按 native-api 的 future-reference 合同处理，不造 resolved。

输出交 `$prism-board-review` 独立检查真实整板，再交 `$prism-moodboard-delivery` 按真实状态交付。当前模型授权/暂停状态由项目合同控制；合并入口不自动运行模型或重试失败。
