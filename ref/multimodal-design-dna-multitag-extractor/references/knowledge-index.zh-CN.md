# 设计 DNA 知识库稳定索引

本索引只用于通过稳定 ID 定位完整知识库；不包含判定规则。风格标签必须读取候选、关系、硬排除和异混淆特征的完整记录。

- 知识库版本：`4.1`
- 活动扁平风格标签：38
- 检索 facet：7
- 显式标签对关系：54
- 查询组合预设：12
- 规范 DNA 字段：192

## 扁平风格标签索引

| style_id | English | 中文 | kind | facets | similarity_weight | 混淆组 |
|---|---|---|---|---|---:|---|
| `ArcaneFuture` | Techno-Mysticism | 科技秘仪 | `atomic` | `graphic_ornament, color_optics, form_structure` | 1.0 | `CG-04` |
| `ArmorPower` | Armored Massing | 装甲体量 | `atomic` | `form_structure, motion_function` | 1.0 | `CG-03` |
| `BiomorphicForm` | Biomorphic Form | 仿生形态 | `atomic` | `form_structure` | 1.0 | `CG-06` |
| `BrutalistMassing` | Brutalist Massing | 粗野原块 | `atomic` | `form_structure, material_surface` | 1.0 | `CG-03, CG-06` |
| `CharacterMorph` | Character Morphology | 角色拟态 | `atomic` | `form_structure, graphic_ornament` | 1.0 | `CG-06, CG-07` |
| `ClassicPrestige` | Classic Pattern | 经典纹样 | `atomic` | `graphic_ornament, material_surface` | 1.0 | `CG-07, CG-08` |
| `CraftedIrregularity` | Crafted Irregularity | 制作式不规整 | `atomic` | `material_surface, graphic_ornament, composition_order` | 1.0 | `CG-06, CG-07` |
| `CyberNeon` | Neon Interface | 霓虹界面 | `atomic` | `color_optics, graphic_ornament` | 1.0 | `CG-04` |
| `DeconstructedAssembly` | Deconstructed Assembly | 解构拼装 | `atomic` | `form_structure, composition_order` | 1.0 | `CG-03` |
| `DecorativeLuxury` | Ornate Pattern | 华饰繁纹 | `atomic` | `graphic_ornament` | 1.0 | `CG-07` |
| `DigitalGlitch` | Digital Glitch | 数字故障 | `atomic` | `graphic_ornament, composition_order` | 1.0 | `CG-04, CG-07` |
| `DreamyAir` | Dreamy Air | 柔雾幻彩 | `atomic` | `color_optics, material_surface` | 1.0 | `CG-04` |
| `ExpressiveMotifs` | Statement Graphic | 主张图形 | `atomic` | `graphic_ornament` | 1.0 | `CG-07` |
| `FashionGraphic` | Geometric Color Blocking | 几何色块 | `atomic` | `graphic_ornament, color_optics, composition_order` | 1.0 | `CG-05, CG-07` |
| `FolkOrnament` | Craft Ornament | 工艺纹饰 | `atomic` | `graphic_ornament, material_surface` | 1.0 | `CG-07` |
| `FreshJoy` | Fresh Joy | 清新愉悦 | `atomic` | `color_optics` | 1.0 | `CG-01` |
| `FunctionalAesthetics` | Rugged Utility | 强韧机能 | `atomic` | `motion_function, form_structure` | 1.0 | `CG-03` |
| `InflatedForm` | Inflated Form | 气室膨胀 | `atomic` | `form_structure, material_surface` | 1.0 | `CG-04, CG-06` |
| `KineticEnergy` | Kinetic Energy | 动感能量 | `atomic` | `motion_function, form_structure, graphic_ornament` | 1.0 | `CG-05` |
| `LayeredTransparency` | Layered Transparency | 透明层叠 | `atomic` | `color_optics, material_surface, form_structure` | 1.0 | `CG-04` |
| `MaturePremium` | Deep Materiality | 深色醇厚 | `atomic` | `material_surface, color_optics` | 1.0 | `CG-02, CG-08` |
| `MechanicalTech` | Exposed Mechanics | 外露机械 | `atomic` | `form_structure, motion_function` | 1.0 | `CG-03` |
| `ModernPrestige` | Warm Metal Luxury | 暖金精奢 | `atomic` | `material_surface, color_optics` | 1.0 | `CG-02` |
| `MysticOrganic` | Dark Organic | 幽暗有机 | `composite` | `form_structure, material_surface, color_optics` | 0.0 | `CG-04, CG-06` |
| `NaturalTextures` | Natural Surface | 自然表面 | `atomic` | `material_surface` | 1.0 | `CG-06` |
| `NeoRetro` | Retro Recomposition | 复古重组 | `atomic` | `material_surface, graphic_ornament, composition_order` | 1.0 | `CG-08` |
| `NordicCalm` | Warm Calm | 温润静雅 | `atomic` | `color_optics, material_surface, form_structure` | 1.0 | `CG-01` |
| `ParametricTech` | Algorithmic Relief | 算法浮雕 | `atomic` | `form_structure, material_surface` | 1.0 | `CG-03` |
| `PlayfulGeometry` | Playful Geometry | 玩趣构成 | `atomic` | `form_structure, composition_order` | 1.0 | `CG-05` |
| `PrecisionMinimalism` | Precision Order | 精密秩序 | `atomic` | `composition_order, form_structure, material_surface` | 1.0 | `CG-02, CG-03` |
| `PureFuture` | Fluid Monolith | 流体单体 | `atomic` | `form_structure, material_surface` | 1.0 | `CG-04` |
| `PureMinimalism` | Pure Minimalism | 纯粹极简 | `atomic` | `composition_order, color_optics, material_surface` | 1.0 | `CG-01` |
| `RefinedMinimalism` | Refined Restraint | 精致克制 | `atomic` | `composition_order, form_structure, material_surface` | 1.0 | `CG-01, CG-02` |
| `RefinedWilderness` | Raw Refinement | 粗粝精工 | `atomic` | `material_surface, form_structure` | 1.0 | `CG-06` |
| `SaturatedBold` | Saturated Bold | 个性鲜彩 | `atomic` | `color_optics` | 1.0 | `CG-05` |
| `SoftContemporary` | Soft Pastel | 柔和粉彩 | `atomic` | `color_optics, form_structure` | 1.0 | `CG-01` |
| `TechComposition` | Technical Graphics | 技术图形 | `atomic` | `graphic_ornament, composition_order` | 1.0 | `CG-03` |
| `Y2KDigital` | Iridescent Optics | 虹彩光学 | `atomic` | `color_optics, material_surface` | 1.0 | `CG-04` |

## 查询组合预设

预设只把已确认标签转换为检索条件，不是可输出的风格标签。

| preset_id | 中文 | 子句门槛 | 可选原子标签 |
|---|---|---|---|
| `CyberAesthetic` | 赛博风格 | 1+2 | `ArmorPower, CyberNeon, DigitalGlitch, LayeredTransparency, MaturePremium, MechanicalTech, TechComposition, Y2KDigital` |
| `DarkRomanticAesthetic` | 暗黑浪漫 | 1+1 | `ArcaneFuture, ClassicPrestige, DecorativeLuxury, MaturePremium` |
| `GummyAesthetic` | 果冻软体 | 2+1 | `DreamyAir, FreshJoy, InflatedForm, LayeredTransparency, SaturatedBold, Y2KDigital` |
| `JapandiAesthetic` | 日式北欧融合 | 2 | `NaturalTextures, NordicCalm, RefinedMinimalism` |
| `KawaiiAesthetic` | 萌系风格 | 1+1 | `CharacterMorph, FreshJoy, PlayfulGeometry, SoftContemporary` |
| `MaximalistAesthetic` | 极繁风格 | 1+2 | `ClassicPrestige, CraftedIrregularity, DecorativeLuxury, ExpressiveMotifs, FashionGraphic, FolkOrnament, SaturatedBold` |
| `MemphisAesthetic` | 孟菲斯风格 | 1+1 | `ExpressiveMotifs, FashionGraphic, NeoRetro, PlayfulGeometry, SaturatedBold` |
| `NeoDecoAesthetic` | 新装饰主义 | 1+1 | `ClassicPrestige, DecorativeLuxury, FashionGraphic, ModernPrestige, NeoRetro` |
| `PlayfulAesthetic` | 玩趣风格 | 1 | `CharacterMorph, ExpressiveMotifs, FreshJoy, InflatedForm, PlayfulGeometry, SaturatedBold` |
| `RetroFuture` | 复古未来 | 1+1 | `CyberNeon, NeoRetro, PureFuture, TechComposition, Y2KDigital` |
| `SolarpunkAesthetic` | 太阳朋克 | 1+1 | `BiomorphicForm, FreshJoy, LayeredTransparency, NaturalTextures, PureFuture, TechComposition` |
| `SteampunkAesthetic` | 蒸汽朋克 | 2+1 | `ClassicPrestige, MaturePremium, MechanicalTech, ModernPrestige, NeoRetro` |

### 迁移别名

- `QuietElegantLuxury` → `RefinedMinimalism`
- `TribeIdentity` → DNA 字段 `IDG-05, IDG-07, IDG-09`

## Facet 索引

- `composition_order`｜构成与秩序｜留白、信息密度、层级与精确秩序。
- `form_structure`｜形态与结构｜轮廓、曲面、体量、连接与结构组织。
- `color_optics`｜色彩与光学｜主色、彩度、渐变、发光与被动反射。
- `material_surface`｜材质与表面｜视觉材质、纹理、粗糙度与表面反射。
- `graphic_ornament`｜图形与装饰｜色块、纹样、文字、符号与装饰语法。
- `motion_function`｜动势与功能｜运动方向、防护、握持、操作与挂载系统。
- `identity_context`｜身份与语境｜经画面自标识或批准参考确认的身份信息；不参与视觉相似度。

## 规范 DNA 字段索引

### `DNA-M01`（14）

`GEO-01` 表观长宽比、`GEO-03` 表观厚度、`GEO-04` 圆角半径比例、`GEO-05` 体量紧凑度、`GEO-06` 视觉重心、`GEO-07` 主组件面积占比、`GEO-08` 凸起关系、`GEO-09` 可见体量层级数、`GEO-10` 轮廓完整性、`GEO-11` 主体—组件支配关系、`GEO-12` 体量分布、`GEO-13` 整体姿态张力、`GEO-14` 接地姿态、`GEO-15` 原块体量组织

### `DNA-M02`（16）

`FORM-01` 主导线性、`FORM-02` 主轮廓曲线占比、`FORM-03` 边缘锐度、`FORM-04` 主截面语言、`FORM-05` 表面转接、`FORM-06` 曲面连续性、`FORM-07` 表面张力、`FORM-08` 接缝可见度、`FORM-09` 边界宽度一致性、`FORM-10` 边界语法、`FORM-11` 防护几何、`FORM-12` 轮廓原型、`FORM-13` 组件融合度、`FORM-14` 曲率分布、`FORM-15` 具象拟态拓扑、`FORM-16` 体量成形机制

### `DNA-M03`（15）

`CMP-01` 主构图轴、`CMP-02` 对称类型、`CMP-03` 平衡方式、`CMP-04` 视觉焦点数、`CMP-05` 第一焦点、`CMP-06` 层级强度、`CMP-07` 对齐方式、`CMP-08` 元素分组、`CMP-09` 留白比例、`CMP-10` 信息密度、`CMP-11` 视觉节奏、`CMP-12` 构图流向、`CMP-13` 主要对比来源、`CMP-15` 构图张力、`CMP-16` 异质系统叠加

### `DNA-M04`（14）

`PRT-01` 可见组件清单、`PRT-02` 组件层级拓扑、`PRT-03` 父子关系、`PRT-04` 连接关系、`PRT-05` 接触关系、`PRT-06` 组件对齐、`PRT-07` 组件间距密度、`PRT-08` 重复拓扑、`PRT-09` 尺寸层级、`PRT-10` 凸起剖面、`PRT-11` 开口与负空间、`PRT-12` 开口面积占比、`PRT-13` 组件角色、`PRT-14` 结构重组关系

### `DNA-M05`（10）

`DEV-01` 成像模组中心、`DEV-02` 主要镜头数量、`DEV-03` 镜头排列、`DEV-04` 镜头尺寸层级、`DEV-05` 镜头环语言、`DEV-06` 显示区域占比、`DEV-07` 四边边框、`DEV-08` 正面开孔、`DEV-09` 控件与端口布局、`DEV-10` 正、侧、背语言一致性

### `DNA-M06`（19）

`CLR-01` 主色、`CLR-02` 辅色、`CLR-03` 点缀色、`CLR-04` 主色面积占比、`CLR-05` 辅色面积占比、`CLR-06` 点缀色总占比、`CLR-07` 有效颜色数、`CLR-08` 色温倾向、`CLR-09` 明度中心与跨度、`CLR-10` 彩度中心与跨度、`CLR-11` 色相关系、`CLR-12` 对比通道、`CLR-13` 区域—颜色映射、`CLR-14` 渐变类型、`CLR-15` 渐变方向与中心、`CLR-16` 随角色变候选、`CLR-17` 近无彩判定、`CLR-19` 绝对主导色、`CLR-20` 调色板结构

### `DNA-M07`（14）

`CMF-01` 区域视觉材质候选、`CMF-02` 主要视觉材质族数量、`CMF-03` 主视觉材质占比、`CMF-04` 材质对比、`CMF-05` 表面效果、`CMF-06` 表观粗糙度、`CMF-07` 表观光泽、`CMF-08` 反射行为、`CMF-09` 视觉透明度、`CMF-10` 物体表面层次深度、`CMF-11` 触感联想、`CMF-12` 材质连续性、`CMF-13` 材质边界、`CMF-14` 表面均匀性

### `DNA-M08`（16）

`TEX-01` 纹理家族、`TEX-02` 视觉来源候选、`TEX-03` 纹理尺度、`TEX-04` 纹理密度、`TEX-05` 表面方向、`TEX-06` 规则度、`TEX-07` 重复方式、`TEX-08` 立体表现候选、`TEX-09` 纹理对比强度、`TEX-10` 覆盖面积、`TEX-11` 分布、`TEX-12` 边界、`TEX-13` 跨部件连续性、`TEX-14` 纹理动势、`TEX-16` 制作式偏差模式、`TEX-17` 数字失真语法

### `DNA-M09`（14）

`DET-01` 控件存在感、`DET-02` 控件形态、`DET-03` 控件分组与位置、`DET-04` 控件 CMF 对比、`DET-06` 孔位与端口节奏、`DET-07` 紧固件、`DET-08` 装饰线几何、`DET-09` 装饰环、`DET-10` 铭牌与标识载体、`DET-11` 透明窗与窗口填充、`DET-13` 微细节密度、`DET-14` 细节语言一致性、`DET-16` 线条角色、`DET-17` 细节语法角色

### `DNA-M10`（9）

`IDG-01` 标识位置、`IDG-02` 标识面积占比、`IDG-03` 标识对比度、`IDG-04` 标识表面表达、`IDG-05` 可见文字与图标系统、`IDG-06` 字形形态、`IDG-07` 身份标识显性度、`IDG-08` 可观察签名原子、`IDG-09` 可识别实体

### `DNA-M11`（11）

`OPT-01` 高光宽度、`OPT-02` 高光边界、`OPT-03` 反射清晰度、`OPT-04` 反射方向、`OPT-07` 透光表现、`OPT-08` 主动发光、`OPT-09` 边缘光来源、`OPT-10` 阴影缝深度、`OPT-12` 物体光学复杂度、`OPT-13` 物体光学主导度、`OPT-14` 透明层间关系

### `DNA-M12`（10）

`HUM-01` 握持友好感、`HUM-02` 边缘舒适感、`HUM-03` 便携感、`HUM-04` 视觉重量、`HUM-05` 坚固感、`HUM-06` 防护感、`HUM-07` 接触稳定感、`HUM-08` 控制可达感、`HUM-09` 方向辨识度、`HUM-10` 功能可理解度

### `DNA-M13`（14）

`SEM-01` 极简—装饰、`SEM-02` 硬朗—柔和、`SEM-03` 轻盈—厚重、`SEM-04` 安静—动感、`SEM-05` 理性—感性、`SEM-06` 自然—科技、`SEM-07` 经典—未来、`SEM-08` 克制—张扬、`SEM-09` 亲和—权威、`SEM-10` 日常—华贵、`SEM-11` 玩趣—成熟、`SEM-12` 规则—自由、`SEM-13` 熟悉—新奇、`SEM-14` 精致—力量

### `DNA-M14`（8）

`IMG-03` 情绪关键词、`IMG-04` 生活方式场景、`IMG-05` 典型参照物、`IMG-06` 自然母题、`IMG-07` 科技与性能母题、`IMG-08` 时代母题、`IMG-09` 文化母题、`IMG-10` 时尚与艺术母题

### `DNA-M15`（8）

`REL-01` 系列家族相似度、`REL-02` 上一代延续度、`REL-03` 创新度、`REL-04` 品类可识别度、`REL-05` 竞品差异化、`REL-06` 趋势一致度、`REL-07` 趋势生命周期、`REL-08` 迭代方式

## 加载规则

1. 先读取全局判定规则，再按 `style_id` 读取候选及同混淆组风格的完整记录。
2. 返回多标签前读取 `tag-relations.json`，对每一对已确认标签执行关系仲裁。
3. 需要解释命名组合时，原子标签确认后再读取组合预设；不得把预设写入输出或用于反向补证。
4. 按品类 profile 读取启用字段；同一字段 ID 不得跨品类改义。
5. 提出新 DNA 前检索规范字段、真 aliases 与零权重 compatibility_derived，避免重复。
