# 设计 DNA 知识库

> **知识库版本**：4.1

> 风格标签只描述单张图片中可定位的视觉机制；可见自标识可逐字记录，但真实材质、工艺、年代、品牌归属、地域和用户意图若无外部资料，不得作为确认事实。

## 风格判定总则

1. 风格采用无层级的 `style_id` 多标签集合；每个标签独立判定，最多确认 3 个，不输出一级/二级或主/次关系。
2. 活动标签必须同时满足：硬门槛通过、命中至少 1 个决定锚点、再命中至少 1 个独立辅助证据、未命中硬排除。同一区域或同一物理现象拆成的近义描述只计一次。
3. 决定锚点和硬排除必须可在主体上观察并定位；背景、拍摄滤镜、运动模糊、主观价值词及不可验证来源不参与硬判定。
4. `颜色角色` 分为 `required`、`supporting`、`unrestricted`。只有 `required` 未命中时才能因颜色直接淘汰；低颜色可靠性时不得以颜色作硬排除。
5. 标签关系以 `tag-relations.json` 为准：conditional 同区冲突 facet 按 `same_region_coexistence` 处理；`forbidden` 必拒，`independent_evidence` 须由双方独占的核心字段证据闭环，不能用同一证据换字段。
6. 差异锚点不可见、被遮挡或仍可由结构功能解释时，候选只能为 `provisional`；不得用语义字段补足硬门槛。
7. `atomic` 表示不依赖其他 `style_tag` 的独立机制，即使跨多个 facet 也仍为 atomic，权重为 1；只有在 `tag-relations.json` 声明 `requires` 的标签才是 `composite`，构成标签须先确认且权重为 0。身份信息不属于风格标签。

### 运动锚点

运动锚点是主体上的前倾或低趴姿态、方向性压缩—释放、超出部件边界的渐缩/斜切/重复速度图形，或明确赛车/性能构件。沿部件边界闭合的接缝、窗框、包边、普通腰线以及背景运动模糊均不算；无法排除结构解释时记为 `unknown`。

## 风格注册表

`style-registry.json` 是 38 个活动标签的权威清单，记录稳定 `style_id`、显示名、别名、facet、标签类型、相似度权重和证据字段白名单；facet 只作后台治理。`QuietElegantLuxury` 与 `TribeIdentity` 仅供历史迁移，不得输出为 `style_tag`。

## 集中混淆组

| ID | 候选范围 | 共享表象 | 决定性边界 |
| --- | --- | --- | --- |
| CG-01 | PureMinimalism、NordicCalm、RefinedMinimalism、SoftContemporary、FreshJoy | 简洁、留白、低装饰 | 近无彩且零增量→Pure；温润低饱和+柔雾/生活材质→Nordic；克制细节增量→Refined；粉蜡低彩→Soft；明快中彩→Fresh |
| CG-02 | RefinedMinimalism、PrecisionMinimalism、ModernPrestige、MaturePremium | 精致、金属或克制表面 | 小面积精致增量→Refined；冷金属封闭秩序→Precision；暖金属主视觉→Modern；深色厚重表面→Mature |
| CG-03 | PrecisionMinimalism、MechanicalTech、ParametricTech、TechComposition、FunctionalAesthetics、ArmorPower、DeconstructedAssembly、BrutalistMassing | 结构、分区、阵列或部件感 | 冷金属封闭秩序→Precision；外露连接→Mechanical；连续参数变化→Parametric；信息图形系统→Tech；操作/防护结构→Functional；夸张装甲体量→Armor；反常重组→Deconstructed；原块/板块主导→Brutalist |
| CG-04 | PureFuture、CyberNeon、ArcaneFuture、DreamyAir、Y2KDigital、MysticOrganic、InflatedForm、LayeredTransparency、DigitalGlitch | 未来感、发光或光学表面 | 连续流体单体→PureFuture；主动发光界面→Cyber；秘仪符号+异常光层→Arcane；低对比柔雾光学→Dreamy；强虹彩被动反射→Y2K；有机基础+异常光层→Mystic；气室成形→Inflated；可读透明层间关系→Layered；数字错误语法→Glitch |
| CG-05 | KineticEnergy、SaturatedBold、FashionGraphic、PlayfulGeometry | 强冲击、运动色或对比构成 | 运动锚点→Kinetic；高饱和主色→Saturated；几何色块→Fashion；几何尺度跳变与非均匀节奏→Playful；机制独立时可组合 |
| CG-06 | NaturalTextures、BiomorphicForm、MysticOrganic、RefinedWilderness、CharacterMorph、InflatedForm、BrutalistMassing、CraftedIrregularity | 自然、有机、柔软或粗粝感 | 自然纹理→Natural；生长式轮廓→Biomorphic；有机基础+异常光层→Mystic；精确几何×粗粝表面对照→RefinedWilderness；具象角色拓扑→Character；气室成形→Inflated；原块体量→Brutalist；稳定制作偏差→Crafted |
| CG-07 | ClassicPrestige、DecorativeLuxury、FolkOrnament、ExpressiveMotifs、FashionGraphic、CharacterMorph、DigitalGlitch、CraftedIrregularity | 纹样、符号或高信息装饰 | 经典重复纹样→Classic；高密度华饰→Decorative；工艺化纹饰→Folk；表达型大图→Expressive；抽象几何色块→Fashion；具象角色拓扑→Character；数字错误语法→Glitch；稳定制作偏差→Crafted |
| CG-08 | NeoRetro、MaturePremium、ClassicPrestige | 深色、皮革感、五金或怀旧线索 | 低噪基体+两族独立线索+DET-17 历史造型化→NeoRetro；深色厚重表面→Mature；经典重复纹样/镶边→Classic |

## 活动风格标签规则

以下“异混淆特征”依次写共享表象、决定性差异、可组合条件和差异不可见时的降级方式。

### PureMinimalism — 纯粹极简

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以近单色、留白和必要结构隐藏形成最低视觉噪声。 |
| 颜色角色 | required：近无彩或近单色，不以可辨彩色承担表达。 |
| 硬门槛 | 主体近单色；除必要功能边界外无非必要装饰或材质分割。 |
| 决定锚点 | 连续静默表面；大面积无信息留白。 |
| 辅助证据 | 隐藏式细节；均匀哑光；简单几何轮廓。 |
| 硬排除 | 装饰图案、异材分割或加大装饰体成为焦点；主动光或强光学层破坏静默表面。 |
| 混淆组 | CG-01 |
| 异混淆特征 | 共享：与温润静雅、精致克制均简洁；分界：本类没有可见设计增量；不可判时：必要边界归因不清则降为 provisional。 |
| 典型视觉Token | monochrome、negative_space、silent_surface、hidden_detail |

### NordicCalm — 温润静雅

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以温润低饱和色、柔雾表面和生活化材质感建立安静感。 |
| 颜色角色 | required：暖灰、雾蓝、灰绿、米白、浅木色等可辨低饱和色。 |
| 硬门槛 | 可辨温润低饱和色，并命中柔雾表面、木/织物视觉或柔和轮廓之一。 |
| 决定锚点 | 家居感低饱和色；温和漫反射表面。 |
| 辅助证据 | 浅木或织物感；圆润轮廓；舒缓留白。 |
| 硬排除 | 主导色为高饱和荧光或粉蜡色；暖金属、主动光或强虹彩取代温润柔雾机制。 |
| 混淆组 | CG-01 |
| 异混淆特征 | 共享：与柔和粉彩、清新愉悦均可浅色；分界：本类需温润材质/柔雾辅助；组合：自然表面有独立纹理证据时可并存；不可判时降级。 |
| 典型视觉Token | warm_grey、misty_blue、soft_matte、home_tone |

### RefinedMinimalism — 精致克制

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 在简洁整体上加入少量、受控且精确的设计增量。 |
| 颜色角色 | supporting：近无彩或克制色常见，但不作单独门槛。 |
| 硬门槛 | 简洁基础成立，且至少有一项克制增量：轻分割、局部金属、轻层叠、细倒角或小面积材质对比。 |
| 决定锚点 | 单一清晰的精致增量；增量与整体保持低对比。 |
| 辅助证据 | 精确比例；细边框；柔和局部高光；统一表面。 |
| 硬排除 | 高密度装饰；强图案破坏简洁基础；金属覆盖成为主体；机械连接外露。 |
| 混淆组 | CG-01、CG-02 |
| 异混淆特征 | 共享：与纯粹极简同样克制、与精密秩序同样精致；分界：本类有小面积增量但无冷金属主体；组合：主色机制有独立证据时可并存；不可判时降级。 |
| 典型视觉Token | subtle_detail、clean_division、micro_contrast、restrained_trim |

### PrecisionMinimalism — 精密秩序

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以冷金属视觉、封闭表面和精确几何秩序表达精密感。 |
| 颜色角色 | supporting：冷银、钢灰、枪灰等冷金属视觉。 |
| 硬门槛 | 大面积冷金属视觉，并同时具有封闭表面与精确秩序；局部金属圈不够。 |
| 决定锚点 | 冷金属主体；严整闭合的几何关系。 |
| 辅助证据 | 平直线；对称布局；精细接缝；受控金属反射。 |
| 硬排除 | 同一主结构由外露紧固/传动或自然纹理主导；主体为暖金属；仅局部冷金属点缀。 |
| 混淆组 | CG-02、CG-03 |
| 异混淆特征 | 共享：与精致克制、外露机械都有精密部件；分界：本类金属为主体且结构封闭，外露连接转机械；不可判时：金属覆盖不清则降级。 |
| 典型视觉Token | cool_metal、precision_geometry、closed_structure、engineering_order |

### SoftContemporary — 柔和粉彩

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以高明度低彩度粉蜡色和柔和几何建立轻柔表达。 |
| 颜色角色 | required：粉、桃、藕、浅薰衣草等粉蜡主色。 |
| 硬门槛 | 粉蜡主色清晰，且整体为单色、近单色或极弱同色变化。 |
| 决定锚点 | 高明度低彩度粉蜡色；柔化几何。 |
| 辅助证据 | 圆润轮廓；细腻哑光；平衡留白。 |
| 硬排除 | 同一主色为无彩、米白/浅木、中彩果冻或高饱和色；同一主表面有虹彩/空气渐变。 |
| 混淆组 | CG-01 |
| 异混淆特征 | 共享：与温润静雅、清新愉悦、柔雾幻彩均柔和；分界：本类是粉蜡近单色且无光学渐变；不可判时：色彩可靠性低则不确认。 |
| 典型视觉Token | soft_pastel、powder_tone、gentle_geometry、matte_softness |

### ModernPrestige — 暖金精奢

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以暖金属覆盖与受控反射形成精奢表面。 |
| 颜色角色 | required：金、香槟金、暖铜等暖金属色为主视觉。 |
| 硬门槛 | 暖金属视觉覆盖主体或主要构件，且反射受控；小面积金色饰圈不够。 |
| 决定锚点 | 暖金属主视觉；连续柔和金属反射。 |
| 辅助证据 | 精细边缘；丝缎光泽；简洁现代构成。 |
| 硬排除 | 主体为冷金属或无可见暖金属；粗粝表面或高密度纹样取代受控暖金反射。 |
| 混淆组 | CG-02 |
| 异混淆特征 | 共享：与精致克制都可有金属；分界：本类暖金属覆盖成为主视觉，局部点缀归精致克制；不可判时：光源偏色无法排除则降级。 |
| 典型视觉Token | warm_metallic、champagne_gold、satin_reflection、metal_surface |

### ClassicPrestige — 经典纹样

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以重复经典纹样、镶边或压纹建立稳定装饰秩序。 |
| 颜色角色 | supporting：常见深色、低彩色或金属点缀，不限定色相。 |
| 硬门槛 | 命中重复经典纹样、连续经典镶边或规则压纹之一；品牌传承不是必要条件。 |
| 决定锚点 | 稳定重复纹样；连续镶边/压纹秩序。 |
| 辅助证据 | 经典比例；皮革视觉候选；温润金属点缀。 |
| 硬排除 | 无纹样且无镶边/压纹；只有纯几何色块；随机高密度华饰且无规则经典语法。 |
| 混淆组 | CG-07、CG-08 |
| 异混淆特征 | 共享：与华饰繁纹、复古重组都可复杂；分界：本类锚点是规则重复或镶边；组合：装饰层级或复古重组有独立证据时可并存；不可判时降级。 |
| 典型视觉Token | classic_pattern、heritage_trim、embossed_texture、classic_ratio |

### DecorativeLuxury — 华饰繁纹

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 让高密度、多层级的华饰细节成为视觉主体。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 高密度装饰纹样或多层华饰覆盖显著面积，且装饰是主要视觉焦点。 |
| 决定锚点 | 高装饰密度；多层雕饰、镶嵌或华丽边框。 |
| 辅助证据 | 浮雕细节；高对比装饰；宝石感点位。 |
| 硬排除 | 装饰仅占孤立小区域且主体大面积无图案；只有技术信息图形、抽象几何色块或身份图形。 |
| 混淆组 | CG-07 |
| 异混淆特征 | 共享：与经典纹样、工艺纹饰都有密集图案；分界：本类以装饰密度和层级取胜，不依赖经典重复或特定工艺；不可判时：局部图案面积不清则降级。 |
| 典型视觉Token | ornamental_pattern、engraved_detail、decorative_frame、layered_ornament |

### MaturePremium — 深色醇厚

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以深色基底和厚重、层次化表面建立沉稳视觉。 |
| 颜色角色 | required：深棕、酒红、墨绿、深蓝或近黑等深色基底。 |
| 硬门槛 | 深色基底成立，并命中皮革/丝绒视觉、厚涂层或分层深光泽之一。 |
| 决定锚点 | 深色厚重表面；低频、温润且有深度的反射。 |
| 辅助证据 | 克制五金；较实体量；细密纹理。 |
| 硬排除 | 主表面为明快浅色、荧光或主动光；只有深色但表面平薄无厚重线索。 |
| 混淆组 | CG-02、CG-08 |
| 异混淆特征 | 共享：与复古重组、经典纹样都可深色；分界：本类靠厚重表面；组合：怀旧语法或纹样有独立证据时可并存；不可判时降级。 |
| 典型视觉Token | deep_tone、leather_like、velvet_like、layered_gloss |

### PureFuture — 流体单体

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以连续流体曲面、单体融合和轻悬浮层次表达未来感。 |
| 颜色角色 | supporting：银白、透明或低彩冷色常见，但非单独门槛。 |
| 硬门槛 | 单体融合基础上，还需连续流体曲面、无框透明层或悬浮光学层之一；仅无缝外壳不够。 |
| 决定锚点 | 连续流体曲面；实体与透明/悬浮层的无缝融合。 |
| 辅助证据 | 隐藏连接；银白低彩；柔连续高光。 |
| 硬排除 | 主体连续性被外露紧固、复古五金、高密度机械分件或粗糙表面破坏。 |
| 混淆组 | CG-04 |
| 异混淆特征 | 共享：与霓虹界面、虹彩光学均有未来光泽；分界：本类锚点是连续单体形态；组合：主动光界面有独立证据时可并存；曲面被遮挡则降级。 |
| 典型视觉Token | fluid_monolith、seamless_curve、floating_layer、hidden_joint |

### MechanicalTech — 外露机械

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 通过可见连接、框架和机械层级直接展示结构关系。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 同时出现可见结构连接与至少两个机械层级；单个螺丝、格栅或普通部件不够。 |
| 决定锚点 | 外露紧固/铰接/传动关系；框架—部件—内层的机械层级。 |
| 辅助证据 | 金属视觉；散热结构；模块化接口；结构标记。 |
| 硬排除 | 完全封闭静默表面；只有平面网格/编号；均匀装饰孔阵；仅功能握持纹。 |
| 混淆组 | CG-03 |
| 异混淆特征 | 共享：与算法浮雕、技术图形、强韧机能都有结构感；分界：本类必须读出连接与机械层级；组合：操作/防护系统有独立证据时可并存；不可判时降级。 |
| 典型视觉Token | exposed_fastener、visible_frame、mechanical_layer、structural_joint |

### CyberNeon — 霓虹界面

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以主动发光构成可读界面、路径或视觉焦点。 |
| 颜色角色 | supporting：霓虹高对比色常见，核心是主动发光角色。 |
| 硬门槛 | 主动发光带、矩阵或图形承担界面/路径/焦点功能；单个状态灯不够。 |
| 决定锚点 | 连续发光路径；可读发光界面或符号。 |
| 辅助证据 | 暗色承载面；高对比荧光色；模块化数字布局。 |
| 硬排除 | 只有被动虹彩反射；仅状态指示灯；柔和珠光渐变；无可见主动发光。 |
| 混淆组 | CG-04 |
| 异混淆特征 | 共享：与虹彩光学、科技秘仪都有发光感；分界：本类是主动光且承担界面角色；不可判时：不能确认主动光源则降级。 |
| 典型视觉Token | neon_interface、active_light、luminous_path、dark_contrast |

### ArcaneFuture — 科技秘仪

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 将人工秘仪符号、仪式几何与异常光层组合成神秘科技感。 |
| 颜色角色 | supporting：深色、冷光或异常光色常见。 |
| 硬门槛 | 必须有人工秘仪符号或仪式几何，并同时出现异常发光层、深层透视或非日常结构之一。 |
| 决定锚点 | 仪式化几何/符号；符号与异常光层的耦合。 |
| 辅助证据 | 深色背景；环形层级；隐藏中心；冷暖异常光。 |
| 硬排除 | 只有暗色与戏剧灯光；纯自然纹理；只有普通技术刻度或常规界面且无秘仪符号。 |
| 混淆组 | CG-04 |
| 异混淆特征 | 共享：与霓虹界面、幽暗有机都可暗且发光；分界：本类必须有人造秘仪符号；组合：另有常规发光界面时可并存；符号性质不清则降级。 |
| 典型视觉Token | ritual_geometry、arcane_symbol、anomalous_glow、hidden_core |

### ParametricTech — 算法浮雕

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以尺寸、密度、高度或曲率的连续参数变化形成表面秩序。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 重复单元沿至少一个维度呈系统性连续变化；均匀阵列不够。 |
| 决定锚点 | 单元尺度/密度渐变；高度或曲率的规则变化场。 |
| 辅助证据 | 三维浮雕；连续波场；算法化重复；光影随结构渐变。 |
| 硬排除 | 候选阵列完全均匀、仅为平面网格/握持防滑或随机自然纹理。 |
| 混淆组 | CG-03 |
| 异混淆特征 | 共享：与外露机械、技术图形都可有阵列；分界：本类要求参数连续变化，均匀孔阵转机械、平面网格转技术图形；不可判时：变化规律不清则降级。 |
| 典型视觉Token | parametric_gradient、algorithmic_relief、density_field、variable_cell |

### TechComposition — 技术图形

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 用网格、刻度、编号、标签和功能分区构成可读技术信息系统。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 至少两类技术图形元素形成同一信息系统；单个数字、线条或普通分区不够。 |
| 决定锚点 | 刻度/编号/标签的关联；平面网格与功能分区的对应。 |
| 辅助证据 | 细线框；坐标感；模块编号；仪表式层级。 |
| 硬排除 | 只有三维参数浮雕、机械连接或纯几何色块；孤立Logo或装饰文字。 |
| 混淆组 | CG-03 |
| 异混淆特征 | 共享：与算法浮雕、外露机械、几何色块均有分区；分界：本类必须形成可读信息关系；不可判时：文字与刻度不可读则降级。 |
| 典型视觉Token | technical_graphics、scale_mark、module_label、instrument_grid |

### KineticEnergy — 动感能量

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 由主体姿态、方向张力或确认的速度图形形成运动趋势。 |
| 颜色角色 | supporting：高对比性能色常见，但不是必要条件。 |
| 硬门槛 | 命中至少一项运动锚点，且再有方向重复、压缩—释放或性能构件之一支持。 |
| 决定锚点 | 前倾/低趴姿态；超出结构边界的速度图形；明确赛车/性能构件。 |
| 辅助证据 | 渐缩斜切；方向重复；张紧曲面；前后体量差。 |
| 硬排除 | 唯一依据是功能接缝、窗框、包边、普通腰线或背景运动模糊；无可确认方向锚点。 |
| 混淆组 | CG-05 |
| 异混淆特征 | 共享：与个性鲜彩都可高饱和、与流体单体都可流线；分界：本类必须有本体运动锚点；组合：鲜彩由主色独立成立时两者可并存；方向线可解释为结构边界则降级。 |
| 典型视觉Token | forward_stance、speed_graphic、directional_tension、performance_form |

### ArmorPower — 装甲体量

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以夸张防护体量、层叠外壳和强边界表达力量。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 至少两处层叠装甲体或显著外扩防护壳形成整体体量；普通保护套不够。 |
| 决定锚点 | 外扩装甲体；多层防护壳与深接缝。 |
| 辅助证据 | 厚重比例；硬折角；护角；深凹槽。 |
| 硬排除 | 轻薄连续单体；仅功能防滑纹；只有内部机械连接而无装甲体量。 |
| 混淆组 | CG-03 |
| 异混淆特征 | 共享：与强韧机能、外露机械都可厚重；分界：本类由夸张装甲体量主导，功能防护结构转强韧机能；不可判时：装甲是否为普通壳体不清则降级。 |
| 典型视觉Token | armored_mass、layered_shell、protective_volume、deep_seam |

### FunctionalAesthetics — 强韧机能

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 将握持、防护、挂载或操作结构组织成清晰实用系统。 |
| 颜色角色 | unrestricted：功能色只作辅助。 |
| 硬门槛 | 至少两类可读功能结构形成系统，如握持+防护、挂载+操作、接口+标记；单一挂绳或色块不够。 |
| 决定锚点 | 成组握持/防护结构；可读挂载或操作界面。 |
| 辅助证据 | 防滑纹；护角；功能色标；加固边；可触控差异。 |
| 硬排除 | 只有装饰色块；只有单一挂绳；多处非必要外扩装甲体遮蔽功能结构；结构用途完全不可读。 |
| 混淆组 | CG-03 |
| 异混淆特征 | 共享：与装甲体量、外露机械都有强结构；分界：本类结构能对应操作、防护或挂载；组合：外露连接有独立层级证据时可并存；用途不可辨则降级。 |
| 典型视觉Token | rugged_utility、grip_system、mount_interface、protective_detail |

### NaturalTextures — 自然表面

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以木纹、石纹、纤维、叶脉等自然视觉纹理组织表面。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 主体有可定位的自然纹理，且纹理具有非机械重复和来源候选；只有有机轮廓不够。 |
| 决定锚点 | 木/石/纤维/脉络视觉；非均匀自然变化。 |
| 辅助证据 | 哑光；颗粒尺度变化；自然色阶；纹理连续跨越表面。 |
| 硬排除 | 纯仿生轮廓但表面均匀；均匀机械阵列；只有摄影背景自然纹理。 |
| 混淆组 | CG-06 |
| 异混淆特征 | 共享：与仿生形态、粗粝精工都有自然感；分界：本类锚点在表面纹理；组合：形态拓扑或精确×粗粝对照独立成立时可并存；主体归属不清则降级。 |
| 典型视觉Token | natural_surface、wood_like、stone_like、fiber_texture |

### BiomorphicForm — 仿生形态

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以生长、分枝、细胞、流体或器官式关系塑造主体形态。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 必须有不可由品类包覆、气动或基本功能解释的生长、分枝、细胞或器官式拓扑；普通流线卵形不够。 |
| 决定锚点 | 生长/分枝拓扑；成组细胞或器官式形态关系。 |
| 辅助证据 | 连续曲率；非均匀有机孔隙；软硬过渡；中心向外生长。 |
| 硬排除 | 只有自然纹理；普通圆角、泡罩、气动流线或常规包覆壳；纯算法阵列；仅摄影曲线。 |
| 混淆组 | CG-06 |
| 异混淆特征 | 共享：与自然表面、流体单体及圆润器物都有曲线；分界：必须有非功能性生长/细胞拓扑；组合：自然纹理有独立表面证据时可并存；常规泡罩不计。 |
| 典型视觉Token | biomorphic_form、branching_growth、cellular_shape、organic_topology |

### MysticOrganic — 幽暗有机

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 在明确有机基础上叠加非自然幽暗光层或异常空间感。 |
| 颜色角色 | supporting：深色自然色与异常微光常见。 |
| 硬门槛 | 先命中仿生形态或自然表面，再命中异常微光、深层半透明或非日常空间感之一；暗色灯光本身不够。 |
| 决定锚点 | 有机基础与异常光层耦合；深层半透明有机结构。 |
| 辅助证据 | 暗部细节；幽微点光；湿润反射；深邃孔隙。 |
| 硬排除 | 只有暗色摄影；异常层只能由人工仪式系统或常规UI解释；普通自然纹理无异常层。 |
| 混淆组 | CG-04、CG-06 |
| 异混淆特征 | 共享：与自然表面、仿生形态、科技秘仪都可幽暗；分界：本类须先独立确认自然表面或仿生形态，再确认异常光层；复合标签零权重；异常光来源不清则降级。 |
| 典型视觉Token | dark_organic、subsurface_depth、bioluminescent_hint、mysterious_nature |

### RefinedWilderness — 粗粝精工

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以精确几何或精细边界对照粗粝、矿物或风化表面。 |
| 颜色角色 | supporting：矿物中性色和大地色常见。 |
| 硬门槛 | 同一区域或相邻区域同时可见精确人工边界与粗粝自然表面；只有粗糙纹理不够。 |
| 决定锚点 | 精确切面×粗粝纹理；规整边界×风化颗粒。 |
| 辅助证据 | 原石视觉；金属精边；局部抛光与粗面反差。 |
| 硬排除 | 只有均匀自然纹理；纯机械加工纹；整体精致无粗粝面；完全随机破损无人工边界。 |
| 混淆组 | CG-06 |
| 异混淆特征 | 共享：与自然表面、精密秩序都有材质表达；分界：必须同时存在精确与粗粝对照；组合：自然纹理独立达标时可并存；本标签独立计分，损伤不清则降级。 |
| 典型视觉Token | raw_refinement、mineral_surface、precision_edge、rough_polish_contrast |

### FreshJoy — 清新愉悦

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以高明度、中彩度清澈实色建立轻快视觉。 |
| 颜色角色 | required：明快但非荧光的中彩主色。 |
| 硬门槛 | 高明度中彩主色占主要面积，表面为实色或极弱同色渐变。 |
| 决定锚点 | 清澈中彩果冻色；高明度轻量表面。 |
| 辅助证据 | 圆润轮廓；柔和光泽；低信息构图。 |
| 硬排除 | 低彩粉蜡色；高饱和荧光；强虹彩；异色云雾渐变。 |
| 混淆组 | CG-01 |
| 异混淆特征 | 共享：与柔和粉彩、个性鲜彩都靠色彩；分界：本类处于明快中彩且不荧光，粉蜡转Soft、高饱和转Saturated；不可判时：颜色可靠性低则不确认。 |
| 典型视觉Token | jelly_color、high_lightness、fresh_solid、soft_gloss |

### SaturatedBold — 个性鲜彩

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 由高饱和或荧光色本身承担主要视觉冲击。 |
| 颜色角色 | required：高饱和单色或简单撞色为主体。 |
| 硬门槛 | 高饱和/荧光主色占主要面积，且色彩本身形成可独立定位的视觉机制。 |
| 决定锚点 | 大面积高饱和实色；简单高对比撞色。 |
| 辅助证据 | 少量中性色功能件；清晰色边界；高色纯度。 |
| 硬排除 | 高饱和只存在于局部图形而非主色；异色光学渐变；仅中彩果冻色。 |
| 混淆组 | CG-05 |
| 异混淆特征 | 共享：与动感能量、几何色块都有强冲击；分界：本类只要求主色机制成立；组合：动势或色块版式有独立证据时可并存；颜色可靠性不足则降级。 |
| 典型视觉Token | high_saturation、bold_color、single_bold_hue、color_impact |

### DreamyAir — 柔雾幻彩

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以低对比柔雾渐变、珠光、极光或轻虹彩形成空气感。 |
| 颜色角色 | required：低彩浅色之间的柔和光学变化。 |
| 硬门槛 | 柔雾渐变、淡珠光、低对比极光/虹彩或半透明雾层至少一项清晰可见；单色哑光不够。 |
| 决定锚点 | 无硬边的空气渐变；柔和珠光/极光/轻虹彩。 |
| 辅助证据 | 半透明雾层；漫反射；浅彩云雾边界。 |
| 硬排除 | 同一表面只有高对比镭射/全息、主动发光或明快实色；无柔散光学变化。 |
| 混淆组 | CG-04 |
| 异混淆特征 | 共享：与虹彩光学都有彩色反射；分界：本类变化低对比、柔散且呈空气感，强镜面角变转虹彩光学；不可判时：反射强度受曝光影响则降级。 |
| 典型视觉Token | airy_gradient、pearl_luster、soft_aurora、translucent_haze |

### Y2KDigital — 虹彩光学

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以强被动虹彩、全息或铬色高光流动建立数字光学表面。 |
| 颜色角色 | required：同一表面可见高对比多色反射或铬色渐变。 |
| 硬门槛 | 镭射、全息、强虹彩反射或铬色高光流动之一明确可见；不得仅凭年代印象。 |
| 决定锚点 | 高对比多色被动反射；镜面铬色高光流动。 |
| 辅助证据 | 彩虹边带；镜面渐变；局部高彩反射。 |
| 硬排除 | 同一表面只有主动光、低对比柔雾或彩色实色；仅拍摄色散。 |
| 混淆组 | CG-04 |
| 异混淆特征 | 共享：与柔雾幻彩、霓虹界面都有多色光；分界：本类是强被动表面反射，不要求验证随角度变化；不可判时：光源染色或后期处理无法排除则降级。 |
| 典型视觉Token | iridescent_surface、holographic_finish、chrome_highlight、rainbow_reflection |

### FashionGraphic — 几何色块

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以平面几何色块和清晰分区建立版式构成。 |
| 颜色角色 | required：至少两个可辨色块形成边界或版式关系。 |
| 硬门槛 | 大色块、撞色或几何分割形成明确平面构图；单一色块或结构分区不够。 |
| 决定锚点 | 抽象几何色块；色块之间的版式关系。 |
| 辅助证据 | 棋盘/条带；视觉分区；平面印刷；图标化布局。 |
| 硬排除 | 只有三维参数浮雕或功能/机械分区；只有具象插画且无抽象色块版式。 |
| 混淆组 | CG-05、CG-07 |
| 异混淆特征 | 共享：与个性鲜彩、技术图形、主张图形都有强平面视觉；分界：本类由抽象色块版式成立；组合：鲜彩或动势有独立证据时可并存；结构分区不清则降级。 |
| 典型视觉Token | geometric_color_block、graphic_segmentation、contrast_panel、checkerboard |

### NeoRetro — 复古重组

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 在集成低噪基体上重组可见复古配色、表达性五金、缝线/包边或经典表面语法。 |
| 颜色角色 | supporting：焦糖、棕、酒红、墨绿、芥末黄、米白等常见。 |
| 硬门槛 | 集成低噪基体成立；至少 2 个线索族各有不共享的字段证据；`DET-17=历史造型化`。 |
| 决定锚点 | `DET-17=历史造型化`×异质表面、经典造型控件/五金或经典图形中的两族独立线索。 |
| 辅助证据 | 黄铜视觉；经典旋钮；皮革/麂皮候选；复古双色。 |
| 硬排除 | 只有怀旧色、滤镜或磨损；普通泡罩、圆灯、轮圈、控件、结构包边或现代标识；普通 `DET-02/08/10/IDG-04/05` 与 `CMF-01/04/FORM-04/PRT-13` 均不能替代 DET-17 门。 |
| 混淆组 | CG-08 |
| 异混淆特征 | 共享：与深色醇厚、经典纹样都可用皮革感和五金；分界：本类靠可见的新旧语法重组；组合：厚重表面或经典纹样独立达标时可并存；本标签独立计分。 |
| 典型视觉Token | modern_retro、brass_detail、retro_trim、material_mix |

### FolkOrnament — 工艺纹饰

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以编织、刺绣、珠饰、手绘或工艺化重复形成触觉型纹饰。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 至少一种可见工艺结构与成组纹饰同时成立；仅异域配色或未经确认的民族归属不够。 |
| 决定锚点 | 编织/刺绣结构；手工式边缘与重复纹饰。 |
| 辅助证据 | 流苏；珠饰；线迹；植物/动物母题；不规则手工痕迹。 |
| 硬排除 | 纯平面工业印刷且无工艺视觉；只有文化联想；只有抽象几何色块。 |
| 混淆组 | CG-07 |
| 异混淆特征 | 共享：与经典纹样、华饰繁纹、主张图形都有图案；分界：本类必须能看到工艺结构，不推断民族或地域来源；不可判时：工艺为印刷模拟且不可辨则降级。 |
| 典型视觉Token | craft_ornament、woven_structure、embroidery_detail、handmade_mark |

### ExpressiveMotifs — 主张图形

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 让大面积文字、插画、角色化图形或符号承担明确表达焦点。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 具象插画、大文字、涂鸦或强符号至少一项成为主要视觉焦点；小图标不够。 |
| 决定锚点 | 大尺度表达图形；单一强视觉符号中心。 |
| 辅助证据 | 拼贴；贴纸层；夸张比例；高对比图文。 |
| 硬排除 | 纯抽象几何色块；只有工艺纹饰结构；普通小Logo；无图案纯色。 |
| 混淆组 | CG-07 |
| 异混淆特征 | 共享：与身份标识、几何色块都可图形醒目；分界：本类只描述表达图形机制；身份可读性与实体候选另写 IDG-05、IDG-07、IDG-09，不生成身份风格标签。 |
| 典型视觉Token | statement_graphic、large_typography、illustration_focus、expressive_symbol |

### PlayfulGeometry — 玩趣构成

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以基础几何、尺度跳变、块面节奏和刻意不对称形成游戏式构成。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 基础几何对比、尺度跳变、非均匀块面节奏、刻意不对称中至少命中两族，且至少一族由 PRT 或 CMP 字段直接支撑。 |
| 决定锚点 | `PRT-09` 尺寸层级跳变；`CMP-11` 非均匀节奏与成组块面共同成立。 |
| 辅助证据 | 多体量层级；动态平衡；自由或近似对称对齐；组件簇群。 |
| 硬排除 | 只有鲜艳颜色、普通圆角、单个装饰形或儿童品类联想；只有抽象印花时判 FashionGraphic。 |
| 混淆组 | CG-05 |
| 异混淆特征 | 共享：与 FreshJoy、SaturatedBold 可明快，与 FashionGraphic 可几何化；分界：本类靠部件尺度与构图节奏，不靠颜色或平面图案；组合：各机制独立达标可并存。 |
| 典型视觉Token | playful_scale_jump、toy_block_rhythm、deliberate_asymmetry、geometric_cluster |

### CharacterMorph — 角色拟态

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 由多个实体部件共同形成脸部、角色身体或动物身体的可读拓扑。 |
| 颜色角色 | unrestricted |
| 硬门槛 | `FORM-15` 非“无/不确定”，且至少两个部件形成眼—口、头—身或身体—肢体关系；孤立的一对圆形或印刷角色不够。 |
| 决定锚点 | 可定位的脸部关系；可定位的头身或身体肢体结构。 |
| 辅助证据 | 部件比例夸张；中心焦点部件；层级化角色轮廓。 |
| 硬排除 | 只有印刷人物、偶发“像脸”、单个眼状件；生长、分枝或器官拓扑应判 BiomorphicForm。 |
| 混淆组 | CG-06、CG-07 |
| 异混淆特征 | 共享：与 ExpressiveMotifs 都可具象，与 BiomorphicForm 都可类生物；分界：本类必须由实体部件构成角色拓扑，不靠平面图形或生长结构；证据不足时降级。 |
| 典型视觉Token | face_topology、head_body_relation、character_part_hierarchy、animal_body_morph |

### InflatedForm — 气室膨胀

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 由封闭或重复气室、张力鼓包及收束节点共同形成膨胀体量。 |
| 颜色角色 | unrestricted |
| 硬门槛 | `FORM-16=气室膨胀`，且封闭/重复气室与接缝、张拉、收束或阀状节点之一同时可见。 |
| 决定锚点 | 重复枕状气室；张力鼓包与收束边界。 |
| 辅助证据 | 柔圆边缘；连续凸起高光；细胞式分区；软体压缩。 |
| 硬排除 | 普通软垫、单一圆润鼓包、光滑塑料壳、泡罩或透明舱盖；只有柔圆轮廓不够。 |
| 混淆组 | CG-04、CG-06 |
| 异混淆特征 | 共享：与 PureFuture、BiomorphicForm 都可流线柔圆，与 LayeredTransparency 可像膜体；分界：本类必须读出气室成形与张力节点；各自硬门槛独立时可组合。 |
| 典型视觉Token | inflated_chamber、pillow_volume、tension_bulge、constricted_joint |

### LayeredTransparency — 透明层叠

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以透明层的重叠、嵌套、包覆或折射建立可读的空间层次。 |
| 颜色角色 | unrestricted |
| 硬门槛 | `OPT-14` 为重叠、嵌套、透明外壳显构或多层折射之一，且透明/半透明与多层或深层关系同时成立。 |
| 决定锚点 | 可追踪的层间穿透与边界；透明外壳显露有组织的内部结构。 |
| 辅助证据 | 层缘反射或折射；嵌套拓扑；透明—不透明对照。 |
| 硬排除 | 单块普通透明窗、照片反光、仅不透明虹彩、无深度关系的雾化效果。 |
| 混淆组 | CG-04 |
| 异混淆特征 | 共享：与 Y2KDigital 都可虹彩，与 DreamyAir 都可轻透，与 PureFuture 都可有透明壳；分界：本类硬判层间空间关系，不靠色彩、柔雾或单层泡罩。 |
| 典型视觉Token | transparent_overlap、nested_shell、visible_inner_layer、multi_layer_refraction |

### DeconstructedAssembly — 解构拼装

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 通过错位、翻转、外翻、切断重组或反常悬置改变常规部件关系。 |
| 颜色角色 | unrestricted |
| 硬门槛 | `PRT-14` 非“常规/不确定”，并有第二条独立的边缘、连接或构图证据证明它是受控重组而非损坏。 |
| 决定锚点 | 部件错位、翻转或外翻；切断后重组；反常悬置。 |
| 辅助证据 | 非对称；轴线中断；外露边界；异质系统或细节并置。 |
| 硬排除 | 意外破损、临时拆解、普通模块化；正常部件关系下的机械外露；仅平面碎片图案。 |
| 混淆组 | CG-03 |
| 异混淆特征 | 共享：与 MechanicalTech 都可外露，与 FunctionalAesthetics 都可结构化；分界：本类必须改变常规部件关系，后二者保持可解释的机械或功能秩序；可独立达标并存。 |
| 典型视觉Token | displaced_part、inside_out_boundary、cut_reassembly、abnormal_suspension |

### DigitalGlitch — 数字故障

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以像素断裂、通道错位、扫描错位、数据撕裂或压缩块化构成受控数字错误语法。 |
| 颜色角色 | unrestricted |
| 硬门槛 | 主体图形系统中至少两种独立数字错误线索共同成立，且 `TEX-17` 非“无/不确定”；单一拍摄伪影不够。 |
| 决定锚点 | 像素断裂与数据撕裂；RGB 通道或扫描带错位。 |
| 辅助证据 | 硬裁切条带；跨部件中断；电子色分离；运动图形线。 |
| 硬排除 | 输入压缩、相机色差、显示屏故障、背景叠加；规则技术网格或可读参数界面应判 TechComposition。 |
| 混淆组 | CG-04、CG-07 |
| 异混淆特征 | 共享：与 CyberNeon 都可电子高彩，与 ExpressiveMotifs 都可醒目；分界：本类靠可重复的数字错误语法，不靠发光界面或表达题材；无法排除成像瑕疵时不确认。 |
| 典型视觉Token | pixel_break、rgb_shift、scan_displacement、data_tear |

### BrutalistMassing — 粗野原块

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 以少量巨大原块或板块、钝直边缘及裸露粗粝表面形成压迫体量。 |
| 颜色角色 | unrestricted |
| 硬门槛 | `GEO-15` 非“无/不确定”，且大尺度钝重体量/板块与裸露粗粝表面或直接结构边界同时成立。 |
| 决定锚点 | 单一原块或板块堆叠；钝直大边界与无遮饰粗表面。 |
| 辅助证据 | 少量大层级；可见连接；低装饰；厚重接地。 |
| 硬排除 | 只有混凝土色、石纹或粗糙纹理；装甲壳体；精确几何×粗粝表面对照；常规机械层级。 |
| 混淆组 | CG-03、CG-06 |
| 异混淆特征 | 共享：与 ArmorPower 都可厚重，与 RefinedWilderness 都可粗粝，与 MechanicalTech 都可显结构；分界：本类由原块/板块体量主导，不靠装甲、防护或精密对照。 |
| 典型视觉Token | monolithic_mass、slab_stack、blunt_edge、raw_exposed_surface |

### CraftedIrregularity — 制作式不规整

| 字段 | 内容 |
| --- | --- |
| 核心机制 | 在重复系统中保留稳定可读的边缘、间距、尺寸、错版或工具痕偏差。 |
| 颜色角色 | unrestricted |
| 硬门槛 | `TEX-16` 非“无/不确定”，重复系统存在稳定偏差，并有工具痕、笔触、边缘或接合线索之一；不声明真实手工工艺。 |
| 决定锚点 | 多次重复中的受控不一致；可追踪的边缘、错版或工具痕偏差。 |
| 辅助证据 | 微不对称；线宽不均；哑光或局部深浅变化；非机械式间距。 |
| 硬排除 | 随机破损、磨损、污渍、噪点、天然纹理或工业随机印刷；只有粗糙表面不够。 |
| 混淆组 | CG-06、CG-07 |
| 异混淆特征 | 共享：与 FolkOrnament 可有工艺感，与 NaturalTextures 可不均匀；分界：本类硬判重复系统中的稳定制作偏差，不推断工艺来源；工艺纹饰或自然纹理独立达标时可并存。 |
| 典型视觉Token | controlled_variation、misregister、uneven_edge、visible_tool_mark |

# 设计元素与 DNA 规范字段

本节是设计元素的规范定义与值域表；字段身份、类型和适用性等机器元数据以 field-registry.json 为准，enum/multi_label 值域以本表为准。字段按稳定语义维护且不按品类改义；品类差异通过 applicability 与 profile 控制。

## 一、单一字段体系与兼容原则

1. 模型只提取 canonical_dna_fields。旧六维名称仅是 legacy_alias，由规范字段派生，不独立提取、不独立存证、不参与计分。
2. 同一可见现象只保留一个规范字段；别名值继承规范字段的 value、confidence 与 evidence_refs，weight 固定为 0。
3. 字段 ID 一经发布不得换义。适用性、可观察性与可计算性分轴记录，不得用一个状态代替另一个，更不得改造字段含义。
4. 模块只是组织方式，不整体承诺优先级。是否可用于判定由每个字段的 decision_use 决定。
5. 单图只能确认当前视图直接可见的内容。真实尺寸、真实材质、制造工艺、随角变化、品牌关系和趋势关系不得从单图断言。

### 旧六维兼容视图

| legacy_alias | 规范来源 |
| --- | --- |
| ID形态 | GEO、FORM、CMP |
| 相机架构 | DEV、PRT 中适用字段 |
| 颜色 | CLR |
| 材质工艺 | CMF、OPT |
| 纹理图案 | TEX |
| 设计细节 | DET、IDG |

兼容适配器若仍需输出 `original_md_dimensions`，必须使用 `schema_source=md_original`、`evidence_mode=derived` 与 `source_path=legacy_alias/...`；宿主按零权重处理，不得再次调用模型生成。

## 二、字段记录与元数据

每条规范字段由字典元数据和本次观察值组成：

~~~yaml
dna_field:
  field_id: GEO-13
  value:
    label: 前倾
    vector: [0.82, -0.18]
  value_type: object
  unit: normalized
  applicability: [core]
  applicability_status: applicable
  evidence_mode: direct
  required_views: [any]
  decision_use: hard
  observability: observed
  confidence: 0.91
  evidence_refs: [EV-04]
~~~

| 元数据 | 合法值与约束 |
| --- | --- |
| applicability | core 或 profile:名称；须逐字段判断，不继承“模块全部适用”。 |
| evidence_mode | direct、derived、inferred、reference_computed。derived 必须列 `derived_from`；reference_computed 的 `required_views` 必须声明 reference_set 或 time_series。 |
| required_views | any、front、rear、side、three_quarter、detail、multi_view、reference_set、time_series，可组合。 |
| value_type / unit | enum、boolean、integer、float、object、list、multi_label、text；结构化集合用 list，纯字符串标签集用 multi_label；数值须给 normalized_ratio、degree、count、oklch 等单位。 |
| decision_use | hard、support、semantic_only、none。hard 字段仅在 direct，或全部依赖已观察的确定性 derived 情况下满足硬门槛。 |
| applicability_status | applicable、not_applicable。仅表示字段是否适用于该对象；不适用字段不进入覆盖率分母。 |
| observability | observed、not_observable、unknown。描述必要视觉输入是否可见；非直接字段只有在 observed 时可标 computed，不承载品类适用性或计算失败。 |
| computation_status | direct 固定 not_requested；derived、inferred、reference_computed 只能为 computed 或 not_computable，缺依赖时写后者。 |

表中 E/V 表示 evidence_mode / required_views，D 表示 decision_use。

## 三、规范字段总览

| 模块 | 数量 | 范围 |
| --- | ---: | --- |
| M01 GEO | 14 | 比例、体量、姿态与接地 |
| M02 FORM | 16 | 轮廓、曲面与边界 |
| M03 CMP | 15 | 构图、层级与动势 |
| M04 PRT | 14 | 组件、父子关系、开口与负空间 |
| M05 DEV | 10 | 成像与屏幕设备 profile |
| M06 CLR | 19 | OKLCH 色彩系统 |
| M07 CMF | 14 | 视觉材质与表面关系 |
| M08 TEX | 16 | 纹理与图案语法 |
| M09 DET | 14 | 微构件、线条与细节语法角色 |
| M10 IDG | 9 | 标识、文字与图标系统 |
| M11 OPT | 11 | 物体自身光学表现 |
| M12 HUM | 10 | 功能与人因视觉推断 |
| M13 SEM | 14 | 有锚点的感知语义坐标 |
| M14 IMG | 8 | 意向、文化与场景推断 |
| M15 REL | 8 | 参考集计算关系 |
| **合计** | **192** | 不含 legacy_alias 与拍摄质量元数据 |

## 四、规范字段定义

### DNA-M01｜比例、体量、姿态与接地

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| GEO-01 | 表观长宽比；float / aspect_ratio | core | direct / any | hard |
| GEO-03 | 表观厚度：薄、中、厚，可附比例；object / normalized_ratio | core | direct / side或three_quarter | support |
| GEO-04 | 圆角半径比例；float / normalized_ratio | core | direct / front或rear | hard |
| GEO-05 | 体量紧凑度：紧凑、均衡、舒展；enum | core | inferred / any | support |
| GEO-06 | 视觉重心；object / normalized_xy | core | direct / any | support |
| GEO-07 | 主组件面积占比；float / normalized_ratio | core | direct / any | hard |
| GEO-08 | 凸起关系：无、弱、中、强，可附比例；object | core | direct / side或three_quarter | support |
| GEO-09 | 可见体量层级数；integer / count | core | direct / any | hard |
| GEO-10 | 轮廓完整性：一体、轻分割、强分割、模块化；enum | core | direct / any | hard |
| GEO-11 | 主体—组件支配关系：主体、均衡、组件；enum | core | derived / any | support |
| GEO-12 | 体量分布：均匀、顶重、底重、中央、多点；enum | core | direct / any | support |
| GEO-13 | 整体姿态张力：静稳、前倾、后仰、低趴、上扬、扭转；object / enum+vector | core | direct / any | hard |
| GEO-14 | 接地姿态：平贴、点接触、轮式、支脚、悬挑、悬浮感、不可见；enum | core | direct / any | support |
| GEO-15 | 原块体量组织：无、单一原块、板块堆叠、块板混合、不确定；enum | core | direct / any | hard |

所有比值均是当前视角的表观值；无标定尺寸时不得写成真实尺寸。

### DNA-M02｜轮廓、曲面与边界

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| FORM-01 | 主导线性：直线、曲线、直曲混合；enum | core | direct / any | hard |
| FORM-02 | 主轮廓曲线占比；float / normalized_ratio | core | derived / any | support |
| FORM-03 | 边缘锐度：锐利、利落、中性、柔圆；enum | core | direct / any | hard |
| FORM-04 | 主截面语言：平直、倒角、圆弧、双曲、复合；enum | core | direct / side或three_quarter | support |
| FORM-05 | 表面转接：齐平、倒角、台阶、包覆、连续、悬浮；enum | core | direct / side或three_quarter | hard |
| FORM-06 | 曲面连续性：突变、平滑、高连续；enum | core | direct / any | hard |
| FORM-07 | 表面张力：绷紧、中性、膨胀、流体；enum | core | direct / any | support |
| FORM-08 | 接缝可见度：隐藏、弱、清晰、主动外露；enum | core | direct / any或detail | hard |
| FORM-09 | 边界宽度一致性：一致、局部变化、强变化；enum | core | direct / any | support |
| FORM-10 | 边界语法：封闭、开放、切断、嵌入、包围、悬浮；enum | core | direct / any | hard |
| FORM-11 | 防护几何：无、护边、高唇、包角、护甲；enum | core | direct / any | hard |
| FORM-12 | 轮廓原型：几何、仿生、器物、自由、不确定；enum | core | direct / any | hard |
| FORM-13 | 组件融合度：融合、过渡、拼接、独立；enum | core | direct / any | hard |
| FORM-14 | 曲率分布：均匀、端部集中、局部鼓胀、连续渐变、不规则；enum | core | direct / any | support |
| FORM-15 | 具象拟态拓扑：无、脸部关系、角色身体、动物身体、复合角色、不确定；enum | core | direct / any | hard |
| FORM-16 | 体量成形机制：常规、气室膨胀、软体压缩、张拉收束、切断错置、不确定；enum | core | direct / any | hard |

FORM-12 的“仿生”仅指可见生长、分枝、细胞或器官拓扑；常规气动流线、卵形泡罩与品类包覆壳归“器物”或“几何”。

### DNA-M03｜构图、层级与动势

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| CMP-01 | 主构图轴：垂直、水平、对角、放射、环形、自由；enum | core | direct / any | hard |
| CMP-02 | 对称类型：双边、旋转、近似、非对称；enum | core | direct / any | hard |
| CMP-03 | 平衡方式：静态、动态、明显失衡；enum | core | inferred / any | support |
| CMP-04 | 视觉焦点数；integer / count | core | direct / any | support |
| CMP-05 | 第一焦点：组件、颜色、材质、图案、标识、结构、其他；enum | core | inferred / any | support |
| CMP-06 | 层级强度：弱、中、强；enum | core | derived / any | support |
| CMP-07 | 对齐方式：中轴、边缘、网格、模块、自由；enum | core | direct / any | hard |
| CMP-08 | 元素分组：集中、分散、成组、模块、连续带；enum | core | direct / any | support |
| CMP-09 | 留白比例；float / normalized_ratio | core | direct / any | hard |
| CMP-10 | 信息密度：低、中、高；enum | core | derived / any | support |
| CMP-11 | 视觉节奏：均匀、重复、渐进、交替、不规则；enum | core | direct / any | hard |
| CMP-12 | 构图流向：无、上下、横向、对角、旋转、扩散、汇聚；enum | core | direct / any | hard |
| CMP-13 | 主要对比来源；multi_label / 尺寸、形状、色相、明度、彩度、材质、光泽、纹理 | core | direct / any | support |
| CMP-15 | 构图张力：稳定、轻张力、强张力；enum | core | inferred / any | support |
| CMP-16 | 异质系统叠加：无、双系统、三系统、多系统、不确定；enum | core | direct / any | hard |

CMP-12 仅表示构图流向；表面方向统一使用 TEX-05，两个字段不得以同名值互相替代。

### DNA-M04｜组件、父子关系、开口与负空间

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| PRT-01 | 可见组件清单；list / typed_object | core | direct / any | support |
| PRT-02 | 组件层级拓扑；object / tree | core | direct / any | hard |
| PRT-03 | 父子关系：包含、承载、包围、穿越、覆盖、同级；multi_label / relation | core | direct / any | hard |
| PRT-04 | 连接关系：融合、嵌入、贴附、悬置、铰接、穿插、分离；enum | core | direct / any | hard |
| PRT-05 | 接触关系：相接、相切、相交、留缝、遮挡；multi_label / relation | core | direct / any | support |
| PRT-06 | 组件对齐：轴线、边缘、中心、网格、无；enum | core | direct / any | hard |
| PRT-07 | 组件间距密度：疏、中、密，可附均值；object / normalized_ratio | core | direct / any | support |
| PRT-08 | 重复拓扑：线性、矩阵、环形、放射、簇群、自由；enum | core | direct / any | hard |
| PRT-09 | 尺寸层级：等大、一主多辅、两级、多级渐进；enum | core | direct / any | hard |
| PRT-10 | 凸起剖面：无、单阶、多阶、火山口、一体隆起、桥接；enum | core | direct / side或three_quarter | support |
| PRT-11 | 开口与负空间：无、孔、槽、窗、框架、贯穿、包围空腔；multi_label | core | direct / any | hard |
| PRT-12 | 开口面积占比；float / normalized_ratio | core | direct / any | support |
| PRT-13 | 组件角色：功能、结构、装饰、标识、未知；multi_label / role | core | direct / any | hard |
| PRT-14 | 结构重组关系：常规、错位、翻转、外翻、切断重组、反常悬置、不确定；enum | core | direct / any | hard |

### DNA-M05｜成像与屏幕设备 Profile

仅当对象命中相应 profile 时启用；不适用的字段不进入覆盖率分母。

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| DEV-01 | 成像模组中心；object / normalized_xy | profile:imaging_device | direct / rear或front | support |
| DEV-02 | 主要镜头数量；integer / count | profile:imaging_device | direct / rear或front | hard |
| DEV-03 | 镜头排列：纵、横、三角、矩阵、环形、自由、混合；enum | profile:imaging_device | direct / rear或front | hard |
| DEV-04 | 镜头尺寸层级：等大、一主多辅、两级、多级；enum | profile:imaging_device | direct / rear或front | hard |
| DEV-05 | 镜头环语言：细窄、厚重、刻度、宝石、护甲、隐藏；multi_label | profile:imaging_device | direct / rear或detail | support |
| DEV-06 | 显示区域占比；float / normalized_ratio | profile:screen_device | direct / front | support |
| DEV-07 | 四边边框；object / normalized_ratio | profile:screen_device | direct / front | support |
| DEV-08 | 正面开孔：无可见、居中孔、偏置孔、刘海、水滴、多孔、未知；enum | profile:screen_device | direct / front | support |
| DEV-09 | 控件与端口布局；list / typed_object+normalized_xy | profile:device_controls | direct / any | support |
| DEV-10 | 正、侧、背语言一致性：低、中、高；enum | profile:multi_face_device | derived / multi_view | support |

“屏下”“真实镜头用途”等需要产品资料时只能写 unknown，不得从外观补全。

### DNA-M06｜OKLCH 色彩系统

颜色流程统一为：主体分割 → 曝光与白平衡质量评估 → sRGB 线性化 → XYZ D65 → OKLCH 聚类。普通图片不以 NCS 黑度/彩度作硬判定；有校准色卡或人工 NCS 标注时，仅作为外部映射保存。

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| CLR-01 | 主色；object / OKLCH+hex+区域 | core | direct / any | hard |
| CLR-02 | 辅色；object / OKLCH+hex+区域 | core | direct / any | support |
| CLR-03 | 点缀色；list / OKLCH+hex+区域 | core | direct / any | support |
| CLR-04 | 主色面积占比；float / normalized_ratio | core | direct / any | hard |
| CLR-05 | 辅色面积占比；float / normalized_ratio | core | direct / any | support |
| CLR-06 | 点缀色总占比；float / normalized_ratio | core | direct / any | support |
| CLR-07 | 有效颜色数；integer / count | core | direct / any | support |
| CLR-08 | 色温倾向：冷、中性、暖、冷暖并置；enum | core | derived / any | support |
| CLR-09 | 明度中心与跨度；object / OKLCH_L | core | direct / any | hard |
| CLR-10 | 彩度中心与跨度；object / OKLCH_C | core | direct / any | hard |
| CLR-11 | 色相关系：同色、邻近、互补、分裂互补、三角、自由；enum | core | derived / any | support |
| CLR-12 | 对比通道；multi_label / hue、lightness、chroma、temperature、area | core | derived / any | support |
| CLR-13 | 区域—颜色映射；object / region_to_OKLCH | core | direct / any | hard |
| CLR-14 | 渐变类型：无、线性、径向、角向、多中心、局部晕染；enum | core | direct / any | hard |
| CLR-15 | 渐变方向与中心；object / degree+normalized_xy | core | direct / any | support |
| CLR-16 | 随角色变候选：无、珠光感、干涉感、全息感、结构色感、未知（单图仅候选）；object / candidate+confidence | core | direct / any或multi_view | support |
| CLR-17 | 近无彩判定；boolean / OKLCH_threshold | core | derived / any | support |
| CLR-19 | 绝对主导色：主色占比大于 0.50；boolean | core | derived / any | support |
| CLR-20 | 调色板结构：无彩、单主色、多主色、主辅点缀；enum | core | derived / any | support |

主色永远是有效颜色中面积最大者，不要求超过 50%；CLR-19 单独表达是否形成绝对主导。色相区间采用左闭右开，粉色需同时满足相应色相、较高明度和有效彩度，不得只按色相判定。

### DNA-M07｜视觉材质与表面关系

字段描述“看起来像什么”，不声明真实成分或制造工艺。具体材质、涂层、阳极、PVD、NCVM、纳米处理等只有在产品资料明确时才能进入外部 metadata。

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| CMF-01 | 区域视觉材质候选；object / region_to_candidate_distribution | core | direct / any | hard |
| CMF-02 | 主要视觉材质族数量；integer / count | core | direct / any | support |
| CMF-03 | 主视觉材质占比；float / normalized_ratio | core | direct / any | support |
| CMF-04 | 材质对比：同质、硬软感、透明不透明、金属非金属感、自然工业感、光哑；multi_label | core | inferred / any | support |
| CMF-05 | 表面效果：均匀漫反射、方向细纹、柔抛光、镜面感、蚀刻感、压纹感、印刷感、未知；multi_label | core | direct / any或detail | hard |
| CMF-06 | 表观粗糙度；float / normalized_ratio | core | inferred / any或detail | support |
| CMF-07 | 表观光泽；float / normalized_ratio | core | direct / any | hard |
| CMF-08 | 反射行为：漫反射、柔高光、清晰高光、镜像、各向异性；enum | core | direct / any | hard |
| CMF-09 | 视觉透明度：不透明、半透明、透明、局部透明；enum | core | direct / any | hard |
| CMF-10 | 物体表面层次深度：平面、浅层、多层、深层；enum | core | direct / any | hard |
| CMF-11 | 触感联想：冰冷、温润、干爽、丝滑、软触、粗粝、未知；enum | core | inferred / any | semantic_only |
| CMF-12 | 材质连续性：连续、局部分段、强分段、拼接；enum | core | direct / any | support |
| CMF-13 | 材质边界：齐平、压边、包边、嵌入、台阶、渐隐；enum | core | direct / any | hard |
| CMF-14 | 表面均匀性：均匀、微变化、强变化；enum | core | direct / any | support |

“金属感”“玻璃感”“皮革感”等均是候选标签；低证据时输出候选分布，不把候选最高项改写成事实。

### DNA-M08｜纹理与图案语法

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| TEX-01 | 纹理家族：无、颗粒、拉丝感、编织感、石纹感、木纹感、晶体、波纹、放射、几何、有机、文化纹样、未知；enum | core | direct / any | hard |
| TEX-02 | 视觉来源候选：自然、工业、数字、手工、文化、品牌、unknown_unverified；object / candidate+confidence | core | inferred / any | semantic_only |
| TEX-03 | 纹理尺度：微观、小、中、大、跨整面；enum | core | direct / any | support |
| TEX-04 | 纹理密度：低、中、高，可附频次；object | core | direct / any | hard |
| TEX-05 | 表面方向：无、水平、垂直、对角、径向、环向、流线；enum | core | direct / any | hard |
| TEX-06 | 规则度：严格、近似、半随机、随机；enum | core | direct / any | hard |
| TEX-07 | 重复方式：平铺、交替、渐变、镜像、旋转、自由；enum | core | direct / any | hard |
| TEX-08 | 立体表现候选：平面、视觉浮雕、实体浅浮雕、深浮雕、镂空、未知（单图仅候选）；object | core | direct / detail或multi_view | support |
| TEX-09 | 纹理对比强度；float / normalized_ratio | core | derived / any | support |
| TEX-10 | 覆盖面积；float / normalized_ratio | core | direct / any | hard |
| TEX-11 | 分布：整面、中心、边缘、组件周围、条带、角落、局部；multi_label | core | direct / any | support |
| TEX-12 | 边界：出血、有框、渐隐、硬裁切、结构对齐；enum | core | direct / any | hard |
| TEX-13 | 跨部件连续性：无、对齐、环绕、被中断；enum | core | direct / any | support |
| TEX-14 | 纹理动势：静止、向外、向内、旋转、流动、爆发；enum | core | inferred / any | support |
| TEX-16 | 制作式偏差模式：无、边缘偏差、间距偏差、尺寸偏差、错版、工具痕、不确定；enum | core | direct / any或detail | hard |
| TEX-17 | 数字失真语法：无、像素断裂、通道错位、扫描错位、数据撕裂、压缩块化、不确定；enum | core | direct / any | hard |

TEX-02 的文化、品牌来源需要参考库才能确认；没有参考时必须使用 unknown_unverified。

### DNA-M09｜微构件与线条角色

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| DET-01 | 控件存在感：隐藏、弱、中、强；enum | profile:device_controls | direct / any | support |
| DET-02 | 控件形态；object / geometry | profile:device_controls | direct / any | support |
| DET-03 | 控件分组与位置；object / count+normalized_xy | profile:device_controls | direct / any | support |
| DET-04 | 控件 CMF 对比：同色同感、同色异感、异色同感、异色异感；enum | profile:device_controls | direct / any | support |
| DET-06 | 孔位与端口节奏：均匀、分组、镜像、不规则；enum | core | direct / any | support |
| DET-07 | 紧固件：无、隐藏、功能可见、装饰强化；enum | core | direct / any或detail | hard |
| DET-08 | 装饰线几何：无、直、曲、环绕、切割、发光；object | core | direct / any | support |
| DET-09 | 装饰环：无、细环、厚环、多层、刻度、宝石感；enum | core | direct / any或detail | support |
| DET-10 | 铭牌与标识载体：无、平面、刻印感、嵌件感、浮雕感、发光；enum | core | direct / any或detail | support |
| DET-11 | 透明窗与窗口填充：无、透明、半透明、深色光学、发光、未知；enum | core | direct / any | support |
| DET-13 | 微细节密度：低、中、高；enum | core | derived / any | support |
| DET-14 | 细节语言一致性：统一、局部混合、明显冲突；enum | core | inferred / any | support |
| DET-16 | 线条角色：结构边界、功能提示、装饰、运动图形、文字图标组成、未知；multi_label / role | core | direct / any | hard |
| DET-17 | 细节语法角色：必要功能结构、通用装饰、历史造型化、当代技术化、未知；enum | core | inferred / any | hard |

DET-16 先判断线条角色，再把几何写入 DET-08；接缝、速度线和版式分隔线不得因“都是线”而互相触发风格。

DET-17 只归纳当前可见细节的造型语法；“历史造型化”不等于真实年代、来源或复刻身份，须由至少两条可见证据共同计算。

### DNA-M10｜标识、文字与图标系统

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| IDG-01 | 标识位置；object / grid9+normalized_xy | core | direct / any | support |
| IDG-02 | 标识面积占比；float / normalized_ratio | core | direct / any | support |
| IDG-03 | 标识对比度；float / normalized_ratio | core | derived / any | support |
| IDG-04 | 标识表面表达：平面、刻印感、浮雕感、嵌件感、发光、隐藏；enum | core | direct / any或detail | support |
| IDG-05 | 可见文字与图标系统；object / text_icon_inventory+layout | core | direct / any | hard |
| IDG-06 | 字形形态：几何、人文、科技、经典、运动、手写、混合；enum | core | direct / any或detail | support |
| IDG-07 | 身份标识显性度：弱、中、强；enum | core | direct / any | support |
| IDG-08 | 可观察签名原子；list / field_ref+value | core | direct / any | support |
| IDG-09 | 可识别实体；object / entity+reference_id+confidence | core | reference_computed / reference_set | support |

通用 Logo 只能满足“存在标识”，不能单独证明品牌传承、IP、圈层或社群身份。

### DNA-M11｜物体自身光学表现

本模块只记录物体表面或主动发光的可见表现；拍摄灯光、渲染、白平衡与模糊进入输入质量元数据。

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| OPT-01 | 高光宽度：细、中、宽，可附比例；object | core | direct / any | support |
| OPT-02 | 高光边界：硬、中、柔；enum | core | direct / any | support |
| OPT-03 | 反射清晰度：无、模糊、半清晰、镜像；enum | core | direct / any | hard |
| OPT-04 | 反射方向：无、单向、径向、环向、多向；enum | core | direct / any | support |
| OPT-07 | 透光表现：不透光、半透、透光、局部透光；enum | core | direct / any | hard |
| OPT-08 | 主动发光：无、点、线、面、图案；object / enum+region | core | direct / any | hard |
| OPT-09 | 边缘光来源：反射、主动发光、混合、未知；enum | core | direct / any | hard |
| OPT-10 | 阴影缝深度：无、浅、中、深；enum | core | direct / any | support |
| OPT-12 | 物体光学复杂度：低、中、高；enum | core | derived / any | support |
| OPT-13 | 物体光学主导度：低、中、高；enum | core | inferred / any | support |
| OPT-14 | 透明层间关系：无、单层透明、重叠、嵌套、透明外壳显构、多层折射、不确定；enum | core | direct / any | hard |

入射角敏感与随角变色只有多视图或视频才能确认；单图仅通过 CLR-16 记录候选。

### DNA-M12｜功能与人因视觉推断

全部字段均是视觉推断，不代表真实人体工学、重量、强度或耐用测试。

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| HUM-01 | 握持友好感：低、中、高；enum | profile:handled_object | inferred / any | semantic_only |
| HUM-02 | 边缘舒适感：低、中、高；enum | profile:handled_object | inferred / side或three_quarter | semantic_only |
| HUM-03 | 便携感：低、中、高；enum | profile:portable_object | inferred / any | semantic_only |
| HUM-04 | 视觉重量：轻、中、重；enum | core | inferred / any | semantic_only |
| HUM-05 | 坚固感：低、中、高；enum | core | inferred / any | semantic_only |
| HUM-06 | 防护感：低、中、高；enum | core | inferred / any | semantic_only |
| HUM-07 | 接触稳定感：低、中、高；enum | profile:contact_surface | inferred / side或three_quarter | semantic_only |
| HUM-08 | 控制可达感：低、中、高；enum | profile:device_controls | inferred / any | semantic_only |
| HUM-09 | 方向辨识度：低、中、高；enum | core | inferred / any | semantic_only |
| HUM-10 | 功能可理解度：低、中、高；enum | core | inferred / any | semantic_only |

### DNA-M13｜感知语义坐标

所有轴均为 inferred、semantic_only。每个值必须引用至少两个独立观察字段，并使用共同锚点：0=明确左端，25=偏左，50=证据均衡或不明显，75=偏右，100=明确右端。不得凭形容词给出伪精确小数。

| ID | 轴 | 左端 0 | 右端 100 |
| --- | --- | --- | --- |
| SEM-01 | 极简—装饰 | 必要元素、低密度 | 装饰成为主视觉 |
| SEM-02 | 硬朗—柔和 | 锐边、硬转折 | 连续圆润曲面 |
| SEM-03 | 轻盈—厚重 | 纤薄、低体量 | 厚实体块 |
| SEM-04 | 安静—动感 | 稳定、低张力 | 明确方向与能量 |
| SEM-05 | 理性—感性 | 网格、精密秩序 | 情绪化自由表达 |
| SEM-06 | 自然—科技 | 有机与自然表面 | 机械、数字、光学 |
| SEM-07 | 经典—未来 | 传统语法 | 实验未来语法 |
| SEM-08 | 克制—张扬 | 低对比低存在 | 高冲击强表达 |
| SEM-09 | 亲和—权威 | 友好柔和 | 庄重掌控 |
| SEM-10 | 日常—华贵 | 朴素日常 | 华饰与稀有感联想 |
| SEM-11 | 玩趣—成熟 | 活泼游戏感 | 稳重沉着 |
| SEM-12 | 规则—自由 | 严格重复与对齐 | 非规则自由组织 |
| SEM-13 | 熟悉—新奇 | 常见品类语法 | 显著陌生化 |
| SEM-14 | 精致—力量 | 细腻轻巧 | 强壮护甲体量 |

SEM-12 不再把“有机”当作“秩序”的反义词；自然程度只由 SEM-06 表达。

### DNA-M14｜意向、文化与场景推断

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| IMG-03 | 情绪关键词；list / label+ordinal_strength | core | inferred / any | semantic_only |
| IMG-04 | 生活方式场景：居家、通勤、户外、运动、社交、收藏、专业、未来生活、其他；multi_label / controlled_vocab | core | inferred / any | semantic_only |
| IMG-05 | 典型参照物；list / entity_or_free_text | core | inferred / any | semantic_only |
| IMG-06 | 自然母题；multi_label / 植物、矿物、水、天空、地貌、生物、其他 | core | inferred / any | semantic_only |
| IMG-07 | 科技与性能母题；multi_label / 机械、参数化、赛博、光学、航空、速度、护甲、工具 | core | inferred / any | semantic_only |
| IMG-08 | 时代母题；multi_label / 经典、复古、千禧、当代、未来、未知 | core | inferred / any | semantic_only |
| IMG-09 | 文化母题；object / candidate+reference_id+confidence | core | reference_computed / reference_set | semantic_only |
| IMG-10 | 时尚与艺术母题；multi_label / 极简、高定、街头、波普、抽象、装置、其他 | core | inferred / any | semantic_only |

用户指定的目标感知属于 request_context，不是从图片观察得到的 DNA；叙事摘要可由上述字段派生，但 weight=0。

### DNA-M15｜参考集计算关系

M15 仅由带来源版本的参考/趋势扩展工作流激活；当前单图 Skill 中为 `profile_not_applicable`。不得由单图推断，也不得把未激活 profile 写成 `not_computable`。

| ID | 字段与值域 | applicability | E/V | D |
| --- | --- | --- | --- | --- |
| REL-01 | 系列家族相似度；integer / ordinal_0_25_50_75_100 | profile:reference_analysis | reference_computed / reference_set | none |
| REL-02 | 上一代延续度；integer / ordinal_0_25_50_75_100 | profile:reference_analysis | reference_computed / reference_set | none |
| REL-03 | 创新度；integer / ordinal_0_25_50_75_100 | profile:reference_analysis | reference_computed / reference_set | none |
| REL-04 | 品类可识别度；integer / ordinal_0_25_50_75_100 | profile:reference_analysis | reference_computed / reference_set | none |
| REL-05 | 竞品差异化；integer / ordinal_0_25_50_75_100 | profile:reference_analysis | reference_computed / reference_set | none |
| REL-06 | 趋势一致度；integer / ordinal_0_25_50_75_100 | profile:trend_analysis | reference_computed / reference_set | none |
| REL-07 | 趋势生命周期：经典、稳定、上升、短期、实验；enum | profile:trend_analysis | reference_computed / time_series | none |
| REL-08 | 迭代方式：保守、渐进、焕新、跳跃；enum | profile:reference_analysis | reference_computed / reference_set | none |

## 五、别名、合并与派生

下表是兼容映射，不增加规范字段数量。只有 `legacy_alias` 与兼容 `derived` 投影的 `decision_use=none`、`weight=0`；规范字段自身的 `evidence_mode=derived` 仍按注册表参与判定，禁止混为一类。

#### 已迁移：TribeIdentity

`TribeIdentity` 已停用且无替代风格标签。可见文字与图标、身份显性度及参考实体分别写入 `IDG-05`、`IDG-07`、`IDG-09`；若图形本身满足表达机制，仍可独立判定 `ExpressiveMotifs`。旧标签不再参与硬判、混淆或相似度。

| 旧 ID / 旧概念 | 规范来源 | 兼容方式 |
| --- | --- | --- |
| GEO-07 相机模组面积占比 | GEO-07 主组件面积占比 | 同 ID 语义上收敛为通用“主组件”；相机 profile 限定组件类型 |
| CAM-02 | GEO-07 | alias |
| CAM-01 | DEV-01 | alias |
| CAM-05、CAM-06、CAM-07、CAM-11 | DEV-02、DEV-03、DEV-04、DEV-05 | alias |
| CAM-03、CAM-04、CAM-09、CAM-12 | FORM-12、PRT-04、PRT-07、PRT-10 | derived |
| CAM-08、CAM-13、CAM-14、CAM-15、CAM-16、CAM-17 | GEO-07、CLR-15、PRT-01、CLR-04、PRT-13、GEO-11 | derived |
| FRN-01、FRN-02、FRN-06、FRN-09、FRN-12 | DEV-06、DEV-07、DEV-08、DEV-09、DEV-10 | alias |
| FRN-03、FRN-04、FRN-05、FRN-07、FRN-10、FRN-11 | DEV-07、FORM-09、FORM-04、DET-13、CMP-02、DET-06 | derived |
| FRN-08 | FORM-04 | alias |
| DET-05 旧“接缝与天线线” | FORM-08 | alias；线条角色另用 DET-16 |
| DET-12 | OPT-08 | alias |
| DET-15 | DET-13 与 FORM-08 | derived |
| CLR-16 旧“随角变色强度” | CLR-16 | 值域收敛为候选；多视图才能确认 |
| OPT-05、OPT-06 | CLR-16 | derived；需要多视图 |
| OPT-11 | CMF-10 | alias |
| CMF-15 | TEX-05 | alias |
| CMF-16 | HUM-05、CMF-07 | derived |
| TEX-15 | TEX-06 | derived：随机度是规则度的反向映射 |
| GEO-02 | GEO-01 | derived：结合品类基线生成宽窄倾向 |
| CMP-14 | GEO-06 | derived：视觉中心兼容视图 |
| BRD-01～BRD-04、BRD-05、BRD-09 | IDG-01～IDG-04、IDG-06、IDG-07 | alias |
| BRD-06～BRD-08 | IDG-08 | derived |
| BRD-10、BRD-11、BRD-12 | REL-01、REL-02、REL-05 | alias |
| IMG-01、IMG-02 | style_result.style_candidates | 移入扁平候选集合（非字段 alias/compatibility_derived） |
| IMG-12 | IMG-03～IMG-10 | derived narrative，weight=0 |
| IMG-13 | request_context.target_perception | 移出图片 DNA |
| IMG-14 | evidence_refs | 移入通用证据结构 |
| HUM-11 | HUM-01 与 HUM-08 | derived |
| HUM-12 | CMF-07、OPT-03 与 CLR-10 | 仅视觉候选，derived |
| REL-09 | IDG-08 与 REL-02 | derived |
| REL-10 | 100−REL-05 | derived |
| OPT-14 | input_quality.capture_conditions | 移出 DNA |
| 图像质量、裁切、背景、摄影构图 | input_quality | 移出产品 DNA |

## 六、拍摄条件与输入质量（非 DNA）

以下内容只用于降低可靠度，不进入相似度、风格得分或 DNA 索引：

| metadata | 值 |
| --- | --- |
| illumination_direction | front、side、back、mixed、unknown |
| illumination_hardness | hard、medium、soft、unknown |
| white_balance_cast | none、warm、cool、mixed、unknown |
| exposure_clipping | none、shadow、highlight、both |
| reflection_occlusion | 0–1 |
| perspective_distortion | 0–1 |
| motion_blur | 0–1 |
| crop_completeness | 0–1 |
| background_interference | 0–1 |
| color_reliability | 0–1；由曝光、白平衡、反射、遮挡与背景干扰计算 |

M11 只记录物体光学表现；若无法排除灯光或渲染干扰，对应字段写 unknown 或降低 confidence。

## 七、提取与评分规则

| 规则 ID | 规则 |
| --- | --- |
| DNA-R01 | 先识别主体、品类与 profile，再记录 applicability_status；not_applicable 不进入覆盖率分母。 |
| DNA-R02 | 先提取 direct 字段，再派生 derived，最后生成 inferred；禁止用语义字段反向补造观察值。 |
| DNA-R03 | 同一区域、同一物理现象只保留一个规范字段证据；alias 与 derived 权重为 0。 |
| DNA-R04 | direct 字段缺必要视角时写 not_observable；derived、inferred 或 reference_computed 缺依赖时写 not_computable。 |
| DNA-R05 | 主色按主体有效颜色最大面积确定，CLR-19 另记是否超过 50%；低 input_quality.color_reliability 不得作硬排除。 |
| DNA-R06 | 材质和工艺只输出视觉候选与表面效果；真实名称需外部产品资料。 |
| DNA-R07 | M13、M14 只作语义排序，不能单独满足风格硬门槛；每项至少引用两个独立 direct 字段。 |
| DNA-R08 | 当前单图 Skill 不激活 M15；core 内的 IDG-09、IMG-09 缺参考库时写 not_computable，不得补猜实体或文化归属。 |
| DNA-R09 | 数值比较只使用相同 value_type、unit 和 profile；禁止跨品类复用同一 ID 的不同含义。 |
| DNA-R10 | 风格使用的客观锚点必须引用规范 field_id 与 evidence_refs，不接受无字段引用的自由文本。 |
| DNA-R11 | 最多确认 3 个扁平标签；按 tag-relations 仲裁。atomic 权重为 1；只有显式 requires 的 composite 权重为 0。 |

字段得分：

~~~text
observed direct:
  similarity × confidence × field_weight
inferred:
  只参与语义排序，不参与硬门槛
legacy_alias / compatibility projection:
  weight = 0
not_applicable:
  不进入覆盖率分母
not_observable:
  适用的 direct 字段当前不可见，不计分
not_computable:
  适用的 derived / inferred / reference_computed 字段缺依赖，不计分
~~~

## 八、单图 DNA 卡示例

~~~yaml
design_dna_card:
  object_id: object_01
  object_type: vehicle
  active_profiles: [core, profile:contact_surface]
  canonical_dna_fields:
    - field_id: GEO-13
      value: {label: 前倾, vector: [0.82, -0.18]}
      observability: observed
      confidence: 0.91
      evidence_refs: [ev_04]
  legacy_aliases:
    enabled: false
    weight: 0
  reference_modules:
    M15:
      applicability_status: not_applicable
      reason: profile_not_applicable
  input_quality:
    perspective_distortion: 0.18
    motion_blur: 0.08
~~~
