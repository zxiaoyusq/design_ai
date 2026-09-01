# 跨品类 DNA Profile

规范字段语义全局固定；品类只决定“哪些字段启用”，不改变字段名称、值域或判定方式。字段定义以 design-dna-knowledge-base.zh-CN.md 与 field-registry.json 为准。

## 1. 适配原则

1. 先识别单一主物品与 object_type，再激活 profile，最后逐字段生成 applicable_field_ids。
2. 适用性、可观察性、可计算性分轴记录：不适用写 not_applicable；direct 字段缺视角写 not_observable；计算字段缺依赖写 not_computable。
3. 同一 field_id 在所有品类中必须同义。不得把口袋当相机岛、把家具把手当镜头环，或以改名方式复用设备字段。
4. 通用形态、构图、色彩、视觉 CMF、纹理、组件和标识字段可跨品类；专属字段只在对应 profile 激活。
5. 材质、工艺、人因、文化和品牌结论遵循字段自身 evidence_mode，不因品类常识升级为直接事实。
6. 新维度先进入 novel_dna_elements；经多样本、人审、冲突检查后再分配稳定 ID。

## 2. Profile 激活

| profile | 激活条件 | 主要字段 |
| --- | --- | --- |
| core | 所有可辨认主物品 | GEO、FORM、CMP、PRT、CLR、CMF、TEX 及适用的 DET、IDG、OPT、SEM、IMG |
| profile:device_controls | 存在可见按键、旋钮、端口或操作件 | DEV-09、DET-01～04、HUM-08 |
| profile:imaging_device | 物品本体含明确镜头或成像模组 | DEV-01～05 |
| profile:screen_device | 物品本体含主要显示面 | DEV-06～08 |
| profile:multi_face_device | 保留给复合多视图扩展；当前单图 Skill 不激活 | DEV-10 |
| profile:handled_object | 设计包含明确手持或握持界面 | HUM-01、HUM-02 |
| profile:portable_object | 物品通常由人携带，且图像支持体量判断 | HUM-03 |
| profile:contact_surface | 可见稳定接触面、底座、支脚或轮组 | HUM-07 |
| profile:reference_analysis | 保留扩展；当前单图 Skill 不激活 | REL-01～05、REL-08 |
| profile:trend_analysis | 保留扩展；当前单图 Skill 不激活 | REL-06、REL-07 |

profile 只控制字段适用性，不自动提供证据。结果必须把启用项写入 `module_applicability.active_profiles`；当前单图不激活 multi-face、reference 或 trend profile，core 中的参考计算字段若被输出，必须写 `not_computable`。

## 3. 常见品类路由

| object_type | 默认 profile | 重点 | 条件字段 |
| --- | --- | --- | --- |
| smartphone / tablet | core、profile:device_controls、profile:imaging_device、profile:screen_device、profile:handled_object、profile:portable_object | 多面体量、成像/屏幕、边框与控件 | DEV-10 仅多视图 |
| camera / wearable_device | core、profile:device_controls、profile:imaging_device、profile:handled_object、profile:portable_object | 镜头层级、握持面、操作节奏 | profile:screen_device 仅有主显示面时 |
| apparel | core | 廓形、裁片关系、色彩、纹理、文字图形 | HUM 默认不启用；真实面料与工艺不从图像断言 |
| footwear | core、profile:portable_object、profile:contact_surface | 鞋体分区、开口、底部体量、接地姿态 | profile:handled_object 不启用 |
| bag / accessory | core、profile:portable_object、profile:handled_object | 包体、开合、背负组件、五金和图案 | profile:device_controls 仅真实操作件 |
| furniture / homeware | core、profile:contact_surface | 支撑、连接、负空间、表面分区 | profile:portable_object 仅明确便携物品 |
| vehicle / mobility_equipment | core、profile:device_controls、profile:contact_surface | 姿态、接地、开口、灯组、体量与动势 | profile:imaging_device 仅真实成像件 |
| graphic / packaging | core | 平面构图、色彩、纹理、文字图标 | 3D 厚度、接地和人因通常不适用 |

类别无法可靠确认时，只启用 core 中直接可见字段，并把 profile_confidence 降低；不得通过强行选品类换取更多字段。

## 4. 品类专属候选

以下维度用于发现缺口，不属于当前 183 个规范字段，不能写进 canonical_dna_fields。

| candidate namespace | 候选维度 |
| --- | --- |
| NEW:apparel:* | 廓形型、合体度、肩线、领袖结构、裁片/褶裥、省道、垂坠感 |
| NEW:footwear:* | 鞋楦、鞋头、鞋帮、闭合系统、中底/外底分区、翘度、底纹 |
| NEW:bag:* | 开合、提携/背负系统、隔层、软硬支撑、肩带/链条关系 |
| NEW:furniture:* | 支撑与腿型、悬挑、连接方式、软包体量、坐靠关系 |
| NEW:mobility:* | 轴长/悬垂、舱体比例、前脸/灯组、轮拱、空气动力开口 |
| NEW:graphic:* | 版式网格、阅读路径、字图比例、印刷层次候选 |

候选必须记录 `proposed_field_name`、`definition`、`recommended_value_type`、`applicable_categories`、`evidence_refs`、`distinct_from_existing_fields` 与 `confidence`；`new_enum_value` 还必须引用规范 `existing_field_id`。与现有字段可表达的内容不得重复立项。

## 5. 路由约束

以下是 profile 路由示意；结果 Schema 直接保留 `active_profiles`，其余字段清单是宿主中间状态：

~~~yaml
category_profile:
  object_type: footwear
  profile_confidence: 0.94
  active_profiles: [core, profile:portable_object, profile:contact_surface]
  applicable_field_ids: [GEO-01, GEO-03, GEO-13, GEO-14, PRT-11]
  not_applicable_field_ids: [DEV-01, DEV-06]
  not_observable_field_ids: [GEO-03, CLR-04]
  not_computable_field_ids: [CLR-19]
~~~

- applicable_field_ids 必须来自 field-registry.json。
- not_applicable 不进入覆盖率分母，也不能满足或违反风格规则。
- not_observable 仅表示适用的 direct 字段当前不可见，可降低覆盖率，但不能用常识补全。
- not_computable 表示适用的派生、推断或参考计算字段缺输入；补齐依赖后可重新计算。
- 品类专属术语只写入 region、component_name 或 novel_dna_elements；不重定义规范字段。
- profile 发生人工修订时，保留修订前值、原因、操作者与时间。
