"""预提取阶段逐图生成可见DNA及对象组合情绪侧表；实现复用原路径，不覆盖历史R5。"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
import jsonschema

from design_emotion import (EMOTION_OBSERVATION_INSTRUCTIONS, bind_emotion, emotion_schema,
                            primary_subject_binding, selected_subject_groups, validate_display_contract,
                            SELECTED_OBJECT_VERSION)
from model_runtime import digest, execute_structured, now, ref, write_new

LEGACY_VERSION = "prism.dna_cluster_observation.v1"
SUBJECT_VERSION = "prism.dna_cluster_observation.v2"
VERSION = SELECTED_OBJECT_VERSION
PROMPT_VERSION = "prism-dna-cluster-observation-20261010-v9"
SUBJECT_PROMPT_VERSIONS = {"prism-dna-cluster-observation-20261009-v5",
                           "prism-dna-cluster-observation-20261009-v6",
                           "prism-dna-cluster-observation-20261009-v7",
                           "prism-dna-cluster-observation-20261009-v8", PROMPT_VERSION}
EMOTION_PROMPT_VERSIONS = {"prism-dna-cluster-observation-20261009-v7"}
SELECTED_OBJECT_PROMPT_VERSIONS = {"prism-dna-cluster-observation-20261009-v8", PROMPT_VERSION}

# 以下等级是有语言锚点的图片观察，不是物理测量；null 单独表示没有可靠观察值。
ID_FIELDS = {
    "form": {"contour": "straight curved mixed", "proportion": "slender balanced broad",
             "volume": "flat slim solid open_frame", "symmetry": "symmetric approximate asymmetric"},
    "structure": {"component_count": "few moderate many", "connection_visibility": "hidden partial exposed",
                  "line_density": "sparse moderate dense", "layering": "single few many"},
    "detail": {"edge": "sharp rounded mixed", "detail_density": "sparse moderate dense",
               "composition": "unified segmented repetitive"},
}
CMF_FIELDS = {
    "color": {"hue": "neutral red orange yellow green cyan blue purple pink brown mixed",
              "chroma": "low medium high", "lightness": "dark middle light",
              "color_count": "single few many", "contrast": "low medium high"},
    "material": {"appearance": "metal glass plastic textile wood stone paper ceramic rubber leather brick concrete plaster mixed other",
                 "gloss": "matte satin glossy mirror",
                 "reflection": "diffuse soft_highlight sharp_highlight mirror directional",
                 "transparency": "opaque translucent transparent"},
    "texture": {"family": "none grain linear grid organic figurative geometric fiber mixed",
                "scale": "fine medium large", "density": "sparse moderate dense",
                "regularity": "regular perturbed irregular nonrepeat",
                "direction": "none linear crossed radial curved mixed",
                "edge": "sharp soft irregular mixed",
                "representation": "none geometric organic figurative mixed"},
}

# 这些跨品类字段观察所选主／同级对象的可见上下文；身份和品类不参与距离。
WHOLE_APPEARANCE_FIELDS = {
    "color": CMF_FIELDS["color"],
    "design": {"line_language": "straight curved mixed", "edge": "sharp rounded mixed",
               "detail_density": "sparse moderate dense", "composition": "unified segmented repetitive"},
    "tone": {"visual_weight": "light balanced heavy", "order": "regular mixed irregular",
             "energy": "quiet balanced lively"},
}
SUBJECT_FIELDS = {"target_role", "primary_subject", "evidence_bbox", "display_bbox",
                  "design_quality", "whole_appearance"}
PRIMARY_ROLES = {"primary_object", "primary_object_surface", "primary_architectural_surface"}
DISPLAY_FIELDS = {"display_scope", "crop_reason"}

SYSTEM = """你是产品设计视觉观察员。本次仅逐图记录供混合图库聚类的可见 DNA；没有指定风格，没有上游语义主题，也不判断用户偏好。
对每个附件都实际观察，按 attachment_index/image_id 精确对应，输出每张一次，不漏图，不跨图借特征。
旧 R5 是带位置的候选观察，可能存在遗漏或错误；以本次原图为准。只在当前同一对象/表面仍有支持时引用 reused_fact_ids；不修改旧结果，不因为旧模型写过就同意。
每图仅附最多32条跨部位选取的旧R5候选子集，facts每行为[fact_id,字段ID,值,原位置]；完整旧结果在磁盘留档但未作为本次上下文提供。不能宣称已读全部R5，子集缺项不能证明特征不存在，仍须逐张观察实际附图。

先在原图选择有明确设计表达的对象：可以是照片主物品，也可以是与它同级呈现的其他独立设计物品。不能为凑相似转向偶然背景碎片。primary_subject是兼容历史的键名，现指本单元所选设计对象；identity用中文指明实际物品及位置，bbox保留图中可见该对象的完整定位，whole_visible说明完整轮廓是否可见，evidence必须说明它为何是主物品或同级对象。建筑或室内本身确是设计主题时可作为对象，但墙角、地面或道具不因面积大就自动具备同级资格。没有可辨设计对象时units为空并解释。
同一所选对象的各单元必须复用相同identity和bbox；同图不同同级对象可以各自独立绑定，绝不能将甲物品的形态、乙物品的材质和丙物品的情绪拼接。whole_appearance与design_emotion始终查看原图中该对象的可见上下文，不以局部代表未见整体。对象在原图被遮挡或截断时，whole_visible=false并明确记录限制，不推断画外形态。
每图至多 1 个 ID 和 2 个 CMF 单元，不要求填满，不扩大当前观察预算。ID可以保留完整设计对象，也可以保留有代表性的造型、连接或结构局部；局部时display_scope=representative_detail，whole_object_visible如实为false，limitations明确只观察该局部。ID局部的features只描述实际证据范围，整物比例、整体对称性、完整构件关系看不出则填null，不把局部冒充整件；原图对象上下文另存在whole_appearance。人体自身和拍摄背景不当设计DNA。
target_role=primary_object/primary_object_surface表示主物品及其代表性表面；peer_object/peer_object_surface表示有明确同级设计呈现依据的其他物品及其表面；primary_architectural_surface表示建筑或室内设计本身的代表表面。secondary_object/background/incidental_detail/unknown分别表示仅辅助布景的次要物品、背景、偶然碎片或角色未明，只能作为不可用诊断。设计化把手、接缝等局部可以是代表性细节，但需说明实际设计表达，不能因同色便随意截一点。身份和角色不能从旧R5顺序、品类或名称猜测。
CMF观察所选对象上真实连续表面或明确相邻界面；不能拼接不相邻物品表面，也不为填满两个单元搜索背景。三个框使用原图归一化[x,y,width,height]，旧bbox必须等于evidence_bbox且事实属于primary_subject框；事实框只定位本单元实际依据。display_bbox是真实裁片，必须包含事实；display_scope=whole_object时也包含所选对象框，representative_detail时无需包含整个对象，但在最终板上须能读懂有代表性的材质、纹理、接缝或造型表达，不限裁框面积。
crop_reason须写清当前选整物/局部的设计表达、范围理由与必要上下文；局部必须如实核对原图对象整体组合，不能裁掉相矛盾的配色、细节或材质关系来制造协调。无需把整件对象硬塞进每个局部裁片，原图始终保留供核对。若局部无法独立传达可读设计、归属不明或只有藏掉冲突才显得统一，usable=false。文字称排除某物不等于实际框内已无其像素。scope/evidence说明实际位置和依据；usable只表示当前目标与表达可读，不等于整板通过。
对每个规定字段实际判断：未知填 null；none 仅表示确认不存在，不能用来代替看不清。不编真实材质、制造工艺、触感、价格和风格名。

whole_appearance仅记录原图所选对象的可见整体上下文，不含别的对象和背景，也不能用CMF小事实框颜色代替整体。color沿用下述颜色锚点但范围改为所选对象；design.line_language记录主导设计线条为直线/曲线/混合，edge为主要设计边缘锐利/圆润/混合，detail_density为整物同尺度设计细节疏/中/密，composition为一体连贯/分段分块/重复组织。不同类别例如手机、手表、汽车、服装、家具可以拥有相同这些关系；不要输出品类相似度、风格名或为了跨类强行同值。
tone.visual_weight是可见视觉轻重：light为细薄、轻盈、开敞或留空占主导，heavy为饱满厚重、密实体量占主导，balanced为两者均无显著主导；不能按真实重量或品类猜。tone.order为主要线条/分区排列：regular有清楚对齐或有序重复，irregular以不规则走向与分布为主，mixed为两者并存。tone.energy=quiet指整物以连续稳定轮廓、克制细节与低视觉起伏为主，lively指强方向变化、显著撞色/对比或密集跳变组织占主导，balanced为无明显一端主导；单一颜色不能决定energy。这些是有图像锚点的定性观察，不是心理结论，无法可靠判断填null。whole_appearance.evidence写实际决定整体颜色、设计关系和调性的主要可见特征。
design_quality评价当前所选设计对象是否有可见的设计组织，不是照片分辨率或昂贵感：distinctive须有至少两项清楚、相互配合且有辨识度的比例/轮廓/构件/配色/材料光学或细节组织；considered须至少一项清楚、有意图且对象上下文协调的设计处理；ordinary表示可读但没有足够具体可见设计处理支持；unresolved表示看不清或依据不足。evidence必须指出实际处理及位置，不能只写“高级、好看、品牌、工业风”等标签。不以类别、真实价格、材质贵贱、背景整洁或拍照精美代替设计证据，不为凑板抬高等级。设计优先级与usable分开，普通设计可以被观察但后续选图优先有明确设计证据的候选。

ID锚点先看display_scope：whole_object按整件对象描述，representative_detail只按evidence_bbox中明确声明的造型/结构局部描述，不把裁框边缘当设计轮廓，不从局部外推整物。contour看当前实际设计轮廓路径；proportion为可见设计范围显著细长slender/长宽较均衡balanced/显著横向宽展broad；volume为以面片为主flat/细薄连贯体slim/饱满实体solid/开敞骨架open_frame。局部无法支持独立的比例或对称关系时proportion/symmetry填null，不能用裁框长宽假造。component_count只计当前声明范围可辨的设计构件1–3=few、4–8=moderate、9以上=many；局部看不清完整连接或分件关系就null，不把颜色分区/纹样计为结构部件。line_density、detail_density比较当前真实设计范围同尺度的结构线及细节疏密；layering看实际前后结构层single/2–3层few/更多many，不把纹理重复数当层数。composition描述当前范围内连贯/分段/重复组织。整物与局部范围由字段明确保存，局部计数不是整物BOM，缺失的整物比例/对称/完整构件事实保持未知。
CMF锚点：color只描述当前目标表面：hue为主导可见色族，若无主导且多色并重用mixed；neutral包括黑白灰，brown包括暖褐木色。chroma low=近灰或明显柔淡、medium=有色但不鲜艳、high=强鲜艳；lightness为画面观察下深/中/浅；color_count为single单色、few约2–3个可辨色族、many更多，不把光照起伏切成新颜色；contrast是表面颜色/图案与底色的强弱。
material.appearance只表示像某种材料的外观，不能证明真实成分；选择metal/glass/plastic/textile/wood/stone/paper/ceramic/rubber/leather/brick/concrete/plaster（后四项仅皮革样/砖块样/混凝土样/抹灰样外观），确有同区域混合才mixed，不能判断填null，不靠物品类别猜。gloss为哑光/柔缎半光/明显亮面/镜面；reflection为漫散无明确高光diffuse/宽软高光soft_highlight/清楚集中高光sharp_highlight/可辨镜像mirror/明显沿纹理方向directional。透明要能看到实体内部透过，网孔透视不算透明。
texture.family描述主要可见纹理组织；none=在可读尺度确实平整无可辨纹样，grain颗粒，linear线槽/条纹，grid网格，organic有机斑纹，figurative具象花草物象，geometric几何图形，fiber纤维/编织，mixed多个组织并重。scale相对当前目标表面为细fine/中medium/大large；density为疏/中/密，regularity为规则/轻扰动/不规则/非重复；direction为无主方向/单向/交叉/放射/曲向/混合；edge为纹理单元边界清楚sharp/柔糊soft/破碎不规则irregular/mixed。representation看装饰纹样是否几何、自然抽象organic或可认物象figurative，不用来推风格。
没有可见纹理时 family=none、representation=none，其他纹理属性填null；分辨率不足时family=null，不能宣称无纹理。颜色和纹理等级均为定性视觉观察，不是色度或尺寸实测。

runway独立记录：yes需当前图明确走秀/秀场呈现场景，no需当前图足以明确为非秀场场景，无法排除则unknown。穿衣/织物/人物本身不等于秀场。此字段不影响任何DNA取值。不要根据文件名猜品牌、项目或来源身份。每项不确定性和拍摄干扰保留在limitations，不能改变照片补证据。
只返回符合schema的JSON，不输出工具操作、预设风格标签、分组建议或多图之间的相似度。"""

SYSTEM += """
具体关系优先：whole_appearance.evidence记录当前所选对象上下文中的主导色、辅助色、点缀色及其组织关系；design_emotion.visible_basis.color引用这些实际关系，不只写“暖色/亲和”。区分大面积深灰与少量暖色、浅暖底与高饱和点缀、多色并重与单一浅色，不编造颜色面积百分比。局部features.color仍只描述evidence_bbox中的真实表面，不能把局部浅色替代整物大面积暗色，也不能把画外未知补为已知。
材料质感依据可见光泽、反光宽窄、表面组织与软硬视觉线索，不只列材料类别或声称真实触感。形态/比例/细节语言说明当前可辨的组合：如连贯体量与清楚接缝、蓬松体量与深皱，宏观褶皱/分块和细微织纹分别说明，不能都概括为柔和或纹理。相反信号和未知写入limitations与情绪解释，不按预想成板方向忽略差异。
实际display_bbox含有突出的相邻颜色/物品或背景时，在limitations说明其对展示的影响；whole_appearance只归属所选对象，不把邻物特征借给它。不能因为事实框里一小片颜色协调，就宣称包含其它主导关系的整个裁片协调。此阶段不判断多图能否同板，也不输出分组建议。
每个unit输出design_emotion，绑定该单元所选对象的原图整体可见上下文。同对象多个单元原样复用同一份组合情绪；不同对象分别观察，不能共享另一对象情绪。不可用单元design_emotion=null；可用单元须给出完整对象级解释，局部图板是否真正表达它留给实际裁片独立评审。旧whole_appearance.tone和历史DNA不等于该组合解释，不能直接复制。
""" + EMOTION_OBSERVATION_INSTRUCTIONS

# 只压缩模型传输格式，字段顺序冻结；程序解码后仍输出相同分块特征，绝不补值。
FEATURE_ORDERS = {branch: [f"{block}.{field}" for block, fields in definitions.items() for field in fields]
                  for branch, definitions in (("ID", ID_FIELDS), ("CMF", CMF_FIELDS))}
SYSTEM += ("\n输出压缩规则：每个unit.features输出短键对象f0,f1等，unknown键必须保留null，不能省项。"
           "ID顺序=" + json.dumps(FEATURE_ORDERS["ID"], ensure_ascii=False) +
           "；CMF顺序=" + json.dumps(FEATURE_ORDERS["CMF"], ensure_ascii=False) +
           "。f0对应第一个字段，以此类推；每个键严格用该位置schema的enum，color.contrast中等必须用medium。"
           "evidence用约40字的事实短句；limitations只保留必要差异/不确定性，不重复通用免责声明或字段定义。"
           "无需重复解释枚举，未有必要限制时limitations用空数组。")


def obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def enum(values: str, nullable: bool = True) -> dict:
    return {"type": ["string", "null"] if nullable else "string", "enum": values.split() + ([None] if nullable else [])}


def batch_count_for(image_count: int, batch_size: int) -> int:
    """按本次冻结图片数向上取整，最后不足整批也占用一次调用。"""
    if image_count < 0 or batch_size <= 0:
        raise ValueError("图片数不能为负，批次容量必须为正")
    return (image_count + batch_size - 1) // batch_size


def bbox_schema() -> dict:
    """事实范围与展示范围使用同一坐标系，几何关系另作显式校验。"""
    return {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
            "minItems": 4, "maxItems": 4}


def unit_schema(branch: str, fields: dict, *, wire: bool = True, version: str = VERSION) -> dict:
    """新请求严格要求主体协议；旧答案只能按旧版解码，不能补造新观察。"""
    if version not in {VERSION, SUBJECT_VERSION, LEGACY_VERSION}:
        raise ValueError(f"不支持的观察版本: {version}")
    feature_schema = obj({block: obj({field: enum(values) for field, values in entries.items()})
                          for block, entries in fields.items()})
    if wire:
        feature_schema = obj({f"f{index}": enum(fields[key.split('.')[0]][key.split('.')[1]])
                              for index, key in enumerate(FEATURE_ORDERS[branch])})
    properties = {"branch": enum(branch, False), "scope": {"type": "string"},
                "bbox": bbox_schema(),
                "whole_object_visible": {"type": "boolean"}, "usable": {"type": "boolean"},
                "features": feature_schema,
                "evidence": {"type": "string"},
                "limitations": {"type": "array", "items": {"type": "string"}},
                "reused_fact_ids": {"type": "array", "items": {"type": "string"}}}
    if version in {VERSION, SUBJECT_VERSION}:
        evidence = {"type": "string", "minLength": 1}
        properties.update({
            "target_role": enum("primary_object primary_object_surface primary_architectural_surface "
                                + ("peer_object peer_object_surface " if version == VERSION else "") +
                                "secondary_object background incidental_detail unknown", False),
            "primary_subject": obj({"identity": evidence, "bbox": bbox_schema(),
                                    "whole_visible": {"type": "boolean"}, "evidence": evidence}),
            "evidence_bbox": bbox_schema(), "display_bbox": bbox_schema(),
            "design_quality": obj({"level": enum("distinctive considered ordinary unresolved", False),
                                   "evidence": evidence}),
            "whole_appearance": obj({
                **{block: obj({field: enum(values) for field, values in entries.items()})
                   for block, entries in WHOLE_APPEARANCE_FIELDS.items()}, "evidence": evidence}),
        })
    if version == VERSION:
        properties.update({"display_scope": enum("whole_object representative_detail", False),
                           "crop_reason": {"type": "string", "minLength": 1},
                           "design_emotion": {"anyOf": [emotion_schema(), {"type": "null"}]}})
    return obj(properties)


def observed_version(unit: dict) -> str:
    """按真正出现的新字段判协议；旧v5/6/7不因脚本升版而改写为v3。"""
    if DISPLAY_FIELDS.intersection(unit):
        return VERSION
    return SUBJECT_VERSION if SUBJECT_FIELDS.intersection(unit) else LEGACY_VERSION


def validate_bbox(bbox: list[float], label: str) -> None:
    x, y, width, height = bbox
    if width <= 0 or height <= 0 or x + width > 1.00001 or y + height > 1.00001:
        raise ValueError(f"非法归一化{label}")


def contains_bbox(outer: list[float], inner: list[float]) -> bool:
    """仅容忍坐标浮点尾差，不能以几何容差裁掉主物品。"""
    x, y, width, height = outer
    ix, iy, iw, ih = inner
    return (x <= ix + 0.00001 and y <= iy + 0.00001 and
            x + width >= ix + iw - 0.00001 and y + height >= iy + ih - 0.00001)


def has_partial_subject_limitation(unit: dict, image_limitations: list[str] | None = None) -> bool:
    """只认已有的明确截断陈述，不从框面积或物品类别推断特写成立。"""
    statements = [*unit.get("limitations", []), *(image_limitations or [])]
    return any(re.search(r"截断|裁切|裁掉|出框|超出(?:画面|镜头)|画外|未完整|不完整|局部(?:可见|呈现)|cropped|partial|cut[ -]?off|(?:不能|无法)(?:确认|观察|看清|判断)(?:其|主体的?|物品的?)?完整|(?:不能|无法)推断[^，。；]{0,12}完整(?:轮廓|形态|形状|结构|比例)",
                         statement, re.I) for statement in statements)


def validate_subject_geometry(unit: dict, image_limitations: list[str] | None = None) -> None:
    """局部事实可小于主物品，但展示必须保留其身份；次要目标不授予可用。"""
    validate_bbox(unit["bbox"], "bbox")
    if observed_version(unit) == VERSION:
        # 显式局部协议才放开整物门，旧记录不能靠改脚本获得新取景资格。
        scoped = {**unit, "subject_visibility_limitations": {"image": image_limitations or []}}
        validate_display_contract(scoped)
        return
    if unit["branch"] == "ID" and unit["usable"] and not unit["whole_object_visible"]:
        raise ValueError("完整ID不可由截断局部冒充")
    if observed_version(unit) == LEGACY_VERSION:
        return
    for key in ("evidence_bbox", "display_bbox"):
        validate_bbox(unit[key], key)
    subject = unit["primary_subject"]
    validate_bbox(subject["bbox"], "primary_subject.bbox")
    if unit["bbox"] != unit["evidence_bbox"]:
        raise ValueError("旧bbox必须保留为事实框evidence_bbox，不能混成展示框")
    if not contains_bbox(unit["display_bbox"], subject["bbox"]):
        raise ValueError("display_bbox必须完整包含primary_subject.bbox")
    if unit["target_role"] in PRIMARY_ROLES and not contains_bbox(subject["bbox"], unit["evidence_bbox"]):
        raise ValueError("当前事实框必须属于已声明主物品，不能借用背景")
    if unit["usable"] and unit["target_role"] not in PRIMARY_ROLES:
        raise ValueError("可用单元必须是完整可辨主物品或其主要表面")
    if unit["branch"] == "ID" and unit["usable"]:
        if not subject["whole_visible"]:
            raise ValueError("可用ID必须是完整可辨主物品")
        if unit["target_role"] != "primary_object" or not contains_bbox(unit["bbox"], subject["bbox"]):
            raise ValueError("可用ID的事实范围必须保留整件主物品")
    if unit["branch"] == "CMF" and unit["usable"] and unit["target_role"] == "primary_object":
        raise ValueError("CMF必须声明主物品主要表面角色，不能用整物身份代替表面")
    if (unit["branch"] == "CMF" and unit["usable"] and not subject["whole_visible"]
            and not has_partial_subject_limitation(unit, image_limitations)):
        raise ValueError("CMF主物品特写须明确记录原图截断及整体观察限制")


def validate_primary_binding(units: list[dict]) -> None:
    """v3逐对象绑定，历史v2仍遵守原单主体合同，不按品类或名称相近合并。"""
    if any(observed_version(unit) == VERSION for unit in units):
        if any(observed_version(unit) != VERSION for unit in units):
            raise ValueError("同一新回答不能混入未声明局部协议的历史单元")
        grouped = selected_subject_groups([{**unit, "unit_id": unit.get("unit_id", str(index))}
                                          for index, unit in enumerate(units)])
        by_id = {unit.get("unit_id", str(index)): unit for index, unit in enumerate(units)}
        for group in grouped:
            values = [by_id[uid].get("design_emotion") for uid in group["unit_ids"]]
            if any(value != values[0] for value in values[1:]):
                raise ValueError("同一所选对象的单元须复用同一设计情绪，不按表面制造不同结论")
        return
    claimed = [unit["primary_subject"] for unit in units if observed_version(unit) == SUBJECT_VERSION
               and unit.get("usable") and unit.get("target_role") in PRIMARY_ROLES]
    if not claimed:
        return
    first = claimed[0]
    for subject in claimed[1:]:
        if (subject["identity"].strip() != first["identity"].strip()
                or any(abs(left - right) > 1e-5 for left, right in zip(subject["bbox"], first["bbox"], strict=True))):
            raise ValueError("同图可用单元的primary_subject身份或主体框冲突，不能跨物品拼接")


def decode_unit(unit: dict, *, version: str | None = None,
                image_limitations: list[str] | None = None) -> dict:
    """固定顺序数组只做无损解码；按每个字段自身值域拒绝移位或补造值。"""
    definitions = ID_FIELDS if unit["branch"] == "ID" else CMF_FIELDS
    normalizations = []
    if isinstance(unit["features"], dict) and "f0" in unit["features"]:
        keys = [f"f{i}" for i in range(len(FEATURE_ORDERS[unit["branch"]]))]
        if set(unit["features"]) != set(keys):
            raise ValueError("短键集合与当前分支不一致")
        unit = {**unit, "features": [unit["features"][key] for key in keys]}
    if isinstance(unit["features"], list):
        if len(unit["features"]) != len(FEATURE_ORDERS[unit["branch"]]):
            raise ValueError("特征数组长度与当前分支不一致")
        features = {block: {} for block in definitions}
        for key, value in zip(FEATURE_ORDERS[unit["branch"]], unit["features"], strict=True):
            block, field = key.split(".")
            # 仅修复已真实出现、且方法决策明确批准的同义wire词；其他字段不通配改值。
            if unit["branch"] == "CMF" and key == "color.contrast" and value == "moderate":
                normalizations.append({"field": key, "raw_value": "moderate", "canonical_value": "medium",
                                       "rule": "cmf-color-contrast-moderate-to-medium-v1",
                                       "basis": "两词在当前定性锚点均为中等；仅传输归一化，无新增视觉推断"})
                value = "medium"
            if value is not None and value not in definitions[block][field].split():
                raise ValueError(f"{key}取值不合法，未自动改值：{value}")
            features[block][field] = value
        unit = {**unit, "features": features}
    jsonschema.Draft202012Validator(unit_schema(unit["branch"], definitions, wire=False,
                                               version=version or observed_version(unit))).validate(unit)
    validate_subject_geometry(unit, image_limitations)
    if normalizations:
        unit = {**unit, "feature_normalizations": normalizations}
    return unit


def schema(image_ids: list[str]) -> dict:
    image_schema = obj({
        "image_id": {"type": "string", "enum": image_ids},
        "runway": obj({"classification": enum("yes no unknown", False), "evidence": {"type": "string"}}),
        "limitations": {"type": "array", "items": {"type": "string"}},
        "units": {"type": "array", "maxItems": 3, "items": {
            "anyOf": [unit_schema("ID", ID_FIELDS), unit_schema("CMF", CMF_FIELDS)]}},
    })
    return obj({"images": {"type": "array", "minItems": len(image_ids), "maxItems": len(image_ids), "items": image_schema}})


def original_facts(row: dict) -> dict:
    """只传位置绑定的事实，不传历史风格、标题、H01规则或用户语义。"""
    primary_ref = row.get("dna_primary_ref") or next((x for x in row.get("dna_refs", []) if x.get("selected")), None)
    if primary_ref is None:
        return {"source_ref": None, "facts": [], "pending_count": None, "unknown_reason": "没有可复用R5，直接观察当前原图"}
    path = Path(primary_ref["path"])
    if digest(path) != primary_ref["sha256"]:
        raise ValueError(f"旧DNA SHA不一致: {row['image_id']}")
    data = json.loads(path.read_text(encoding="utf-8"))
    source_sha = (data.get("source") or {}).get("image_sha256") or data.get("image_sha256")
    if source_sha is not None and source_sha != row["sha256"]:
        raise ValueError(f"旧DNA不属于当前原图: {row['image_id']}")
    root = data.get("r5_result", data)
    prefix = "/r5_result" if "r5_result" in data else ""
    facts = []
    for index, fact in enumerate(root.get("local_features", [])):
        if str(fact.get("p", "")).startswith(("GEO-", "STR-", "COL-", "TEX-", "OPT-", "REL-")):
            facts.append({"fact_id": f"F{index:03d}", "p": fact["p"], "v": fact["v"], "at": fact["at"],
                          "pointer": f"{prefix}/local_features/{index}"})
    return {"source_ref": primary_ref, "facts": facts, "pending_count": root.get("pending_count"),
            "is_candidate_observation_not_ground_truth": True}


def balanced_fact_subset(facts: list[dict], limit: int = 32) -> list[dict]:
    """按分支和声明部位轮转选上下文，避免首个大表面占满；不改变原DNA台账。"""
    priorities = {
        "ID": ["STR-003", "STR-002", "STR-005", "GEO-001", "GEO-011", "GEO-012", "REL-008", "REL-009",
               "REL-017", "REL-023", "GEO-009", "GEO-010", "GEO-015", "GEO-020"],
        "CMF": ["OPT-001", "COL-006", "OPT-002", "TEX-002", "TEX-001", "OPT-003", "OPT-004", "OPT-006",
                "OPT-007", "COL-003", "COL-004", "TEX-007", "TEX-010", "TEX-011", "TEX-014", "TEX-018"],
    }
    queues = {}
    for branch in ("ID", "CMF"):
        by_location = {}
        for fact in facts:
            belongs = fact["p"].startswith(("COL-", "TEX-", "OPT-"))
            if belongs != (branch == "CMF"):
                continue
            by_location.setdefault(fact["at"], []).append(fact)
        rank = {pid: index for index, pid in enumerate(priorities[branch])}
        for rows in by_location.values():
            rows.sort(key=lambda item: (rank.get(item["p"], len(rank)), item["fact_id"]))
        queue = []
        while any(by_location.values()):
            for rows in by_location.values():
                if rows:
                    queue.append(rows.pop(0))
        queues[branch] = queue
    selected = queues["ID"][:12] + queues["CMF"][:20]
    remaining = queues["CMF"][20:] + queues["ID"][12:]
    return (selected + remaining[:max(0, limit - len(selected))])[:limit]


def prepare_payload(rows: list[dict]) -> tuple[dict, list[dict]]:
    inputs, images = [], []
    for index, row in enumerate(rows, 1):
        path = str(Path(row["local_path"]).resolve())
        if digest(path) != row["sha256"]:
            raise ValueError(f"原图SHA不一致: {row['image_id']}")
        images.append({"path": path, "sha256": row["sha256"], "candidate_id": row["image_id"], "role": "original_image"})
        original = original_facts(row)
        subset = balanced_fact_subset(original["facts"])
        inputs.append({"attachment_index": index, "image_id": row["image_id"], "image_sha256": row["sha256"],
                       "r5": {**original, "facts": subset, "original_known_fact_count": len(original["facts"]),
                              "attached_fact_count": len(subset), "full_original_in_model_context": False}})
    return {"prompt_version": PROMPT_VERSION, "images": inputs}, images


def compact_model_payload(payload: dict) -> dict:
    """原路径、旧模型元数据与JSON Pointer由侧表保存，模型仅收真正参与观察的短事实。"""
    images = []
    for row in payload["images"]:
        facts = row["r5"]
        images.append({"attachment_index": row["attachment_index"], "image_id": row["image_id"],
                       "r5": {"original_known_fact_count": facts["original_known_fact_count"],
                              "attached_fact_count": facts["attached_fact_count"],
                              "full_original_in_model_context": False,
                              "facts": [[item["fact_id"], item["p"], item["v"], item["at"]] for item in facts["facts"]]}})
    return {**payload, "images": images}


def script_snapshot(runroot: Path) -> dict:
    """代码按字节另存版本，派生统计调整后仍能找到旧请求使用的程序。"""
    path = Path(__file__).resolve()
    snapshot = runroot / "code-snapshots" / f"{path.stem}.{digest(path)}.py"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    try:
        with snapshot.open("xb") as stream:
            stream.write(path.read_bytes())
    except FileExistsError:
        pass
    return ref(snapshot)


def field_states(unit: dict) -> dict:
    """只从明确的无纹理状态推出不适用；其余空值不猜测缺项原因。"""
    states = {}
    texture_absent = unit["features"].get("texture", {}).get("family") == "none"
    for block, fields in unit["features"].items():
        states[block] = {}
        for name, value in fields.items():
            not_applicable = (texture_absent and block == "texture" and
                              name in {"scale", "density", "regularity", "direction", "edge"} and value is None)
            states[block][name] = "not_applicable" if not_applicable else "known" if value is not None else "unknown"
    return states


def update_derived_coverage(record: dict) -> dict:
    """汇总时可复算状态和覆盖；模型原始答案、已保存的旧编译结果不被反写。"""
    updated = []
    for unit in record["units"]:
        states = field_states(unit)
        flat = {f"{block}.{name}": state for block, fields in states.items() for name, state in fields.items()}
        updated.append({**unit, "field_states": states, "coverage": {
            "known_fields": sum(state == "known" for state in flat.values()), "total_fields": len(flat),
            "applicable_fields": sum(state != "not_applicable" for state in flat.values()),
            "not_applicable_fields": [name for name, state in flat.items() if state == "not_applicable"],
            "missing_fields": [name for name, state in flat.items() if state == "unknown"],
            "null_reason_policy": "仅明确无纹理派生不适用，其余null均unknown，不猜已检查或不可见"}})
    return {**record, "units": updated}


def validate_and_enrich(answer: dict, rows: list[dict], payload: dict, folder: Path,
                        image_offsets: dict[str, int] | None = None) -> list[dict]:
    actual = [x["image_id"] for x in answer["images"]]
    if len(set(actual)) != len(actual) or set(actual) != {x["image_id"] for x in rows}:
        raise ValueError("模型图像ID必须与本批一一对应")
    # 图片索引与后续情绪出处分开命名，避免首图处理后覆盖索引、整批误入逐图恢复。
    images_by_id = {x["image_id"]: x for x in rows}
    input_by_id = {x["image_id"]: x for x in payload["images"]}
    records = []
    for observed in answer["images"]:
        row = images_by_id[observed["image_id"]]
        facts = {x["fact_id"]: x for x in input_by_id[row["image_id"]]["r5"]["facts"]}
        counts = {"ID": 0, "CMF": 0}
        units = []
        for index, item in enumerate(observed["units"], 1):
            expected_version = (VERSION if payload["prompt_version"] in SELECTED_OBJECT_PROMPT_VERSIONS
                                else SUBJECT_VERSION if payload["prompt_version"] in SUBJECT_PROMPT_VERSIONS else None)
            item = decode_unit(item, version=expected_version, image_limitations=observed.get("limitations", []))
            branch = item["branch"]
            counts[branch] += 1
            if counts["ID"] > 1 or counts["CMF"] > 2:
                raise ValueError("每图至多1个ID和2个CMF单元")
            x, y, width, height = item["bbox"]
            if width <= 0 or height <= 0 or x + width > 1.00001 or y + height > 1.00001:
                raise ValueError(f"非法归一化bbox: {row['image_id']}")
            if not set(item["reused_fact_ids"]) <= set(facts):
                raise ValueError("模型引用了不存在的旧事实")
            values = [value for block in item["features"].values() for value in block.values()]
            unit = {**item, "unit_id": f"{row['image_id']}:{branch}:{counts[branch]}", "image_id": row["image_id"],
                    "image_sha256": row["sha256"], "local_path": row["local_path"],
                    "coverage": {"known_fields": sum(v is not None for v in values), "total_fields": len(values),
                                 "missing_fields": [f"{block}.{key}" for block, fields in item["features"].items()
                                                    for key, value in fields.items() if value is None]},
                    "reused_fact_refs": [{"source_ref": input_by_id[row["image_id"]]["r5"]["source_ref"],
                                          "pointer": facts[fid]["pointer"], "fact_id": fid} for fid in item["reused_fact_ids"]],
                    "observation_ref": ref(folder / "answer.json"),
                    "observation_pointer": f"/images/{(image_offsets or {}).get(row['image_id'], actual.index(row['image_id']))}/units/{index - 1}",
                    "receipt_ref": ref(folder / "receipt.json"), "model_requested": "gpt-6.1-sol",
                    "reasoning_effort_requested": "high", "feature_definition_version": observed_version(item)}
            units.append(unit)
            if observed_version(item) != LEGACY_VERSION and not item["primary_subject"]["whole_visible"]:
                unit["subject_visibility_limitations"] = {"unit": item["limitations"],
                                                          "image": observed.get("limitations", [])}
        validate_primary_binding(units)
        emotion_fields = {}
        if payload["prompt_version"] in SELECTED_OBJECT_PROMPT_VERSIONS:
            for unit in units:
                subject = primary_subject_binding([unit])
                value = unit.get("design_emotion")
                if subject is None:
                    if value is not None:
                        raise ValueError("无可用设计对象的诊断单元不能制造设计情绪")
                    continue
                if value is None:
                    raise ValueError("所选对象协议的可用单元须有独立绑定的设计情绪")
                source = {"observation_ref": unit["observation_ref"],
                          "observation_pointer": unit["observation_pointer"] + "/design_emotion",
                          "receipt_ref": unit["receipt_ref"], "prompt_version": payload["prompt_version"],
                          "model_requested": "gpt-6.1-sol", "reasoning_effort_requested": "high",
                          "assessed_at": json.loads((folder / "receipt.json").read_text(encoding="utf-8")).get("started_at"),
                          "assessment_scope": "selected_object_context_shared_only_with_same_object"}
                unit.update(bind_emotion(value, row, subject, source))
        if payload["prompt_version"] in EMOTION_PROMPT_VERSIONS:
            emotion = observed["design_emotion"]
            subject = primary_subject_binding(units)
            if subject is None:
                if emotion is not None:
                    raise ValueError("没有可用主物品时设计情绪必须为null")
                emotion_fields = {"design_emotion": None}
            else:
                if emotion is None:
                    raise ValueError("新版有主物品的图必须有一次图级设计情绪观察")
                source = {"observation_ref": ref(folder / "answer.json"),
                          "observation_pointer": f"/images/{(image_offsets or {}).get(row['image_id'], actual.index(row['image_id']))}/design_emotion",
                          "receipt_ref": ref(folder / "receipt.json"), "prompt_version": payload["prompt_version"],
                          "model_requested": "gpt-6.1-sol", "reasoning_effort_requested": "high",
                          "assessed_at": json.loads((folder / "receipt.json").read_text(encoding="utf-8")).get("started_at"),
                          "assessment_scope": "one_joint_interpretation_per_image_primary_subject"}
                emotion_fields = bind_emotion(emotion, row, subject, source)
                for unit in units:
                    if primary_subject_binding([unit]) is not None:
                        unit.update(emotion_fields)
        records.append({**row, "status": "observed", "runway": observed["runway"],
                        **emotion_fields,
                        "recovery_status": "recovered_wire_alias" if any(u.get("feature_normalizations") for u in units) else None,
                        "observation_prompt_version": payload["prompt_version"],
                        "r5_context": {"original_known_fact_count": input_by_id[row["image_id"]]["r5"].get("original_known_fact_count"),
                                       "attached_fact_count": len(facts), "full_original_in_model_context": False},
                        "runway_classification_basis": "本轮原图可见场景观察，来源登记尚需独立核验",
                        "observation_limitations": observed["limitations"], "units": units,
                        "observation_ref": ref(folder / "answer.json"), "receipt_ref": ref(folder / "receipt.json")})
    return records


def compile_answer_rows(answer: dict, rows: list[dict], payload: dict, folder: Path) -> list[dict]:
    """只有实际派生错误时按图拆开；同批合法结果仍保留，不重发整批模型。"""
    try:
        return validate_and_enrich(answer, rows, payload, folder)
    except (ValueError, KeyError, jsonschema.ValidationError):
        records, failures = [], []
        by_id = {}
        for index, item in enumerate(answer["images"]):
            by_id.setdefault(item["image_id"], []).append((index, item))
        for row in rows:
            try:
                matches = by_id.get(row["image_id"], [])
                if len(matches) != 1:
                    raise ValueError("该图在模型答案中缺失或重复")
                index, item = matches[0]
                records.extend(validate_and_enrich({"images": [item]}, [row], payload, folder,
                                                    image_offsets={row["image_id"]: index}))
            except (ValueError, KeyError, jsonschema.ValidationError) as exc:
                failure = {"image_id": row["image_id"], "failure_type": "derived_compilation",
                           "error": str(exc), "raw_answer_ref": ref(folder / "answer.json"),
                           "receipt_ref": ref(folder / "receipt.json"), "automatic_retry": False}
                failures.append(failure)
                records.append({**row, "status": "failed", "units": [], "observation_error": failure})
        write_new(folder / f"compile-failures.{PROMPT_VERSION}.json", failures)
        return records


def load_recompiled_subject_batch(folder: Path, rows: list[dict]) -> list[dict]:
    """只复用已另存的离线重编译，核原请求身份与真实Prompt，不把旧调用标为新模型。"""
    records = json.loads((folder / "observations.accepted.subject-v2.json").read_text(encoding="utf-8"))
    payload = json.loads((folder / "payload.json").read_text(encoding="utf-8"))
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    expected = {row["image_id"]: row["sha256"] for row in rows}
    if (len(records) != len(rows) or {row["image_id"]: row["sha256"] for row in records} != expected
            or len(payload["images"]) != len(rows)
            or {item["image_id"] for item in payload["images"]} != set(expected)
            or len(request["images"]) != len(rows)
            or {item["candidate_id"]: item["sha256"] for item in request["images"]} != expected):
        raise ValueError("主体重编译侧表与本批原请求图片身份不一致")
    if payload.get("prompt_version") not in SUBJECT_PROMPT_VERSIONS:
        raise ValueError("主体重编译须保留受支持的实际观察请求版本，不能补造旧协议字段")
    answer_reference, receipt_reference = ref(folder / "answer.json"), ref(folder / "receipt.json")
    for record in records:
        if record["status"] == "observed":
            if (record.get("observation_prompt_version") != payload["prompt_version"]
                    or record.get("observation_ref") != answer_reference
                    or record.get("receipt_ref") != receipt_reference):
                raise ValueError("主体重编译侧表误标了原Prompt、答案或回执")
            for unit in record["units"]:
                if (unit.get("image_id") != record["image_id"] or unit.get("image_sha256") != record["sha256"]
                        or unit.get("feature_definition_version") != (
                            VERSION if payload["prompt_version"] in SELECTED_OBJECT_PROMPT_VERSIONS else SUBJECT_VERSION)):
                    raise ValueError("主体重编译单元身份或字段协议不符")
        elif record["status"] != "failed" or record.get("units"):
            raise ValueError("主体重编译侧表含不支持的执行状态")
    return records


def process_batch(runroot: Path, rows: list[dict], number: int, timeout: int,
                  amendment_ref: dict | None = None) -> dict:
    folder = runroot / "model-calls" / f"batch-{number:03d}"
    accepted = folder / "observations.accepted.json"
    recovered = folder / "observations.accepted.wire-v4.json"
    if (folder / "observations.accepted.subject-v2.json").exists():
        return {"number": number, "status": "reused_recompiled_subject_batch",
                "records": load_recompiled_subject_batch(folder, rows)}
    if recovered.exists():
        return {"number": number, "status": "reused_recovered_batch", "records": json.loads(recovered.read_text())}
    if accepted.exists():
        actual_payload = json.loads((folder / "payload.json").read_text(encoding="utf-8"))
        if actual_payload.get("prompt_version") == "prism-dna-cluster-observation-20261009-v3":
            context = json.loads((runroot / "batch-inputs" / f"batch-{number:03d}.r5-context.json").read_text(encoding="utf-8"))
            answer = json.loads((folder / "answer.json").read_text(encoding="utf-8"))
            records = compile_answer_rows(answer, rows, context, folder)
            previous = json.loads(accepted.read_text(encoding="utf-8"))
            old_units = {u["unit_id"]: u for row in previous for u in row["units"]}
            for row in records:
                for unit in row["units"]:
                    if unit["unit_id"] in old_units and unit["features"] != old_units[unit["unit_id"]]["features"]:
                        raise ValueError("规范化不得改变已成功编译单元的特征")
            ledger = [{"image_id": row["image_id"], "unit_id": unit["unit_id"],
                       "raw_answer_ref": ref(folder / "answer.json"), "raw_unit_pointer": unit["observation_pointer"], **change}
                      for row in records for unit in row["units"] for change in unit.get("feature_normalizations", [])]
            write_new(folder / "normalization-ledger.wire-v4.json", {"created_at": now(),
                      "compiler_ref": script_snapshot(runroot), "model_calls": 0, "entries": ledger,
                      "original_failure_and_answer_preserved": True})
            write_new(recovered, records)
            return {"number": number, "status": "recovered_existing_wire", "records": records}
        return {"number": number, "status": "reused_completed_batch", "records": json.loads(accepted.read_text())}
    if folder.exists():
        return {"number": number, "status": "previous_failure_retained", "records": [
            {**row, "status": "failed", "units": [], "observation_error": "已有未完成或失败调用，未自动重发",
             "failure_directory": str(folder)} for row in rows]}
    try:
        payload, images = prepare_payload(rows)
        # 执行批准、随机样本与程序均按本轮实际字节绑定；方向标题不进入观察请求。
        payload["run_contract_ref"] = ref(runroot / "run-contract.json")
        payload["sample_ref"] = ref(runroot / "sample.json")
        payload["observer_script_ref"] = script_snapshot(runroot)
        payload["design_emotion_contract_ref"] = ref(Path(__file__).with_name("design_emotion.py"))
        emotion_amendment = runroot / "contract-amendments" / "design-emotion-v3.json"
        if emotion_amendment.exists():
            payload["design_emotion_amendment_ref"] = ref(emotion_amendment)
        if amendment_ref:
            payload["concurrency_amendment_ref"] = amendment_ref
        context_path = runroot / "batch-inputs" / f"batch-{number:03d}.r5-context.json"
        write_new(context_path, payload)
        model_payload = compact_model_payload(payload)
        model_payload["r5_context_sidecar_ref"] = ref(context_path)
        answer = execute_structured(folder, system=SYSTEM, payload=model_payload, images=images,
                                    schema=schema([x["image_id"] for x in rows]), timeout=timeout)
        records = compile_answer_rows(answer, rows, payload, folder)
        write_new(accepted, records)
        state = "partial_compilation" if any(row["status"] == "failed" for row in records) else "completed"
        return {"number": number, "status": state, "records": records}
    except Exception as exc:
        folder.mkdir(parents=True, exist_ok=True)
        failure = {"created_at": now(), "error": f"{type(exc).__name__}: {exc}", "automatic_retry": False}
        if not (folder / "observation-failure.json").exists():
            write_new(folder / "observation-failure.json", failure)
        return {"number": number, "status": "failed", "records": [
            {**row, "status": "failed", "units": [], "observation_error": failure["error"],
             "failure_directory": str(folder)} for row in rows]}


def observation_scope_summary(units: list[dict]) -> dict:
    """范围按已编译单元真实协议说明，当前汇总器版本不能升级历史观察资格。"""
    purposes = {
        LEGACY_VERSION: "历史局部DNA观察；未核对新对象资格、代表性取景或对象设计情绪",
        SUBJECT_VERSION: "历史唯一主物品及其至多两个主要表面；事实框与整物展示框分开",
        VERSION: "主物品或同级设计对象的整体及代表性局部；事实、对象与真实展示范围分别绑定",
    }
    versions = sorted({unit.get("feature_definition_version", observed_version(unit)) for unit in units})
    protocol_scopes = [{"feature_definition_version": version, "purpose": purposes.get(version, "未知历史协议，范围未核"),
                        "units": sum(unit.get("feature_definition_version", observed_version(unit)) == version for unit in units)}
                       for version in versions]
    purpose = (protocol_scopes[0]["purpose"] if len(protocol_scopes) == 1 else
               "多种真实观察协议并存，逐协议范围见protocol_scopes；旧单元未自动升级" if protocol_scopes else
               "尚无已编译单元，不以当前脚本版本推断已完成的观察范围")
    return {"maximum_ID_units_per_image": 1, "maximum_CMF_units_per_image": 2,
            "all_legacy_R5_surfaces_reextracted": False, "purpose": purpose,
            "protocol_scopes": protocol_scopes, "legacy_units_not_backfilled": True}


def save_summary(runroot: Path, sample: dict, results: dict[int, dict], batch_size: int) -> dict:
    indexed = {row["image_id"]: row for result in results.values() for row in result["records"]}
    images = [update_derived_coverage(indexed.get(row["image_id"], {**row, "status": "pending", "units": []}))
              for row in sample["images"]]
    units = [unit for row in images for unit in row["units"]]
    statuses = {state: sum(x["status"] == state for x in images) for state in ("observed", "failed", "pending")}
    used_versions = set()
    for number in results:
        actual_payload = runroot / "model-calls" / f"batch-{number:03d}" / "payload.json"
        if actual_payload.exists():
            used_versions.add(json.loads(actual_payload.read_text(encoding="utf-8")).get("prompt_version", "unknown"))
    original_compile_failures = []
    for file in (runroot / "model-calls").glob("batch-*/compile-failures*.json"):
        original_compile_failures.extend(json.loads(file.read_text(encoding="utf-8")))
    summary = {"schema_version": VERSION, "prompt_version": PROMPT_VERSION, "updated_at": now(),
               "prompt_versions_used": sorted(used_versions),
               "feature_definition_versions_used": sorted({u["feature_definition_version"] for u in units}),
               "sample_ref": ref(runroot / "sample.json"), "script_ref": script_snapshot(runroot),
               "run_contract_ref": ref(runroot / "run-contract.json"),
               "scope": f"当前{len(images)}图全图观察台账；未按语义方向或风格筛除", "batch_size": batch_size,
               "images": images, "units": units, "counts": {**statuses, "images": len(images), "units": len(units),
                                                             "ID": sum(u["branch"] == "ID" for u in units),
                                                             "CMF": sum(u["branch"] == "CMF" for u in units),
                                                             "original_compilation_failed_images": len({r["image_id"] for r in original_compile_failures}),
                                                             "recovered_wire_alias_images": sum(r.get("recovery_status") == "recovered_wire_alias" for r in images)},
               "batches": [{"number": n, "status": r["status"], "image_count": len(r["records"])}
                           for n, r in sorted(results.items())],
               "feature_observations_are_qualitative": True, "legacy_r5_modified": False,
               "observation_scope": observation_scope_summary(units),
               "model_policy": {"model": "gpt-6.1-sol", "reasoning_effort": "high", "framework": "DeepAgents"},
               "human_approved": False, "visual_board_approved": False}
    # 仅当前汇总索引原子更新；原始调用、图片和历史DNA文件永不覆盖。
    temporary = runroot / "observations.json.tmp"
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, runroot / "observations.json")
    return summary


def recovery_spec(runroot: Path, amendment_path: Path) -> dict:
    """从显式传入的授权核验已诊断失败请求；不扫描失败列表自动推断恢复许可。"""
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    if amendment.get("kind") != "bounded_technical_recovery":
        raise ValueError("必须提供独立技术恢复授权")
    if amendment["parent_contract_ref"]["sha256"] != digest(runroot / "run-contract.json"):
        raise ValueError("恢复授权不属于当前冻结合同")
    folders = []
    for evidence in amendment["evidence_refs"]:
        path = Path(evidence["path"]).resolve()
        if digest(path) != evidence["sha256"]:
            raise ValueError("原失败证据 SHA 已改变")
        if path.name == "receipt.json":
            if path.parent.parent != (runroot / "model-calls").resolve():
                raise ValueError("本次恢复只能引用主队列原始失败回执")
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if receipt.get("status") != "failed":
                raise ValueError("恢复引用的原始调用并未失败")
            if path.parent not in folders:
                folders.append(path.parent)
    original_images, folder_by_id = [], {}
    for folder in folders:
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        for item in request["images"]:
            if item["candidate_id"] in folder_by_id:
                raise ValueError("原始失败调用出现重复图像身份")
            original_images.append(item)
            folder_by_id[item["candidate_id"]] = folder
    authorized = amendment["authorized_image_ids"]
    if not authorized or len(set(authorized)) != len(authorized) or authorized != [item["candidate_id"] for item in original_images]:
        raise ValueError("授权图像必须与失败回执对应的原请求附件按序一致")
    policy = amendment["execution"]
    expected = {"maximum_recovery_calls": batch_count_for(len(authorized), 5), "images_per_call": 5,
                "maximum_recovery_attempts_per_image": 1, "model": "gpt-6.1-sol",
                "reasoning_effort": "high", "global_maximum_concurrent_requests": 5,
                "automatic_additional_retries": False}
    if any(policy.get(key) != value for key, value in expected.items()):
        raise ValueError("恢复仅按已冻结的每组至多五图、最后可不足五图、每图一次执行")
    sample = json.loads((runroot / "sample.json").read_text(encoding="utf-8"))
    sample_by_id = {row["image_id"]: row for row in sample["images"]}
    rows = [sample_by_id[image_id] for image_id in authorized]
    if any(row["sha256"] != image["sha256"] for row, image in zip(rows, original_images, strict=True)):
        raise ValueError("恢复图片字节身份与原请求不同")
    return {"amendment_ref": ref(amendment_path), "rows": rows, "folder_by_id": folder_by_id,
            "original_request_refs": [ref(folder / "request.json") for folder in folders],
            "maximum_recovery_calls": policy["maximum_recovery_calls"]}


def recover_authorized_case(runroot: Path, spec: dict, base_path: Path, timeout: int) -> Path:
    """单份授权独立存档；已经投递的分组无论成败均不自动重新提交。"""
    base = json.loads(base_path.read_text(encoding="utf-8"))
    rows = spec["rows"]
    source_by_id = {row["image_id"]: row for row in base["images"]}
    case_root = runroot / "bounded-recovery" / Path(spec["amendment_ref"]["path"]).stem
    effective_path = case_root / "observations.effective.json"
    if effective_path.exists():
        previous = json.loads(effective_path.read_text(encoding="utf-8"))
        if previous["bounded_recovery_cases"][-1]["amendment_ref"] != spec["amendment_ref"]:
            raise ValueError("已有恢复版本与当前授权不一致")
        return effective_path
    if any(source_by_id[row["image_id"]]["status"] != "failed" for row in rows):
        raise ValueError("技术恢复只能补查本次原失败图像；授权间不可重复")
    case_root.mkdir(parents=True, exist_ok=True)
    plan_path = case_root / "recovery-plan.json"
    if not plan_path.exists():
        write_new(plan_path, {"created_at": now(), "base_observations_ref": ref(base_path),
                  "amendment_ref": spec["amendment_ref"], "original_request_refs": spec["original_request_refs"],
                  "authorized_image_ids": [row["image_id"] for row in rows],
                  "observer_script_ref": script_snapshot(runroot), "automatic_additional_retries": False})

    def recover_chunk(index: int, chunk: list[dict]) -> dict:
        folder = case_root / f"call-{index:02d}"
        accepted = folder / "observations.accepted.json"
        if accepted.exists():
            return {"number": index, "status": "reused_completed_recovery", "folder": str(folder),
                    "records": json.loads(accepted.read_text(encoding="utf-8"))}
        if folder.exists():
            return {"number": index, "status": "previous_recovery_failure_retained", "folder": str(folder), "records": [
                {**row, "status": "failed", "units": [], "failure_directory": str(folder),
                 "observation_error": "已有恢复调用但无可用结果，未再次重发"} for row in chunk]}
        try:
            payload, images = prepare_payload(chunk)
            original_dirs = list(dict.fromkeys(spec["folder_by_id"][row["image_id"]] for row in chunk))
            payload.update({"run_contract_ref": ref(runroot / "run-contract.json"),
                            "sample_ref": ref(runroot / "sample.json"),
                            "observer_script_ref": script_snapshot(runroot),
                            "bounded_recovery_amendment_ref": spec["amendment_ref"],
                            "original_failed_request_refs": [ref(path / "request.json") for path in original_dirs],
                            "recovery_plan_ref": ref(plan_path)})
            context_path = case_root / f"call-{index:02d}.r5-context.json"
            write_new(context_path, payload)
            model_payload = compact_model_payload(payload)
            model_payload["r5_context_sidecar_ref"] = ref(context_path)
            answer = execute_structured(folder, system=SYSTEM, payload=model_payload, images=images,
                                        schema=schema([row["image_id"] for row in chunk]), timeout=timeout)
            records = compile_answer_rows(answer, chunk, payload, folder)
            write_new(accepted, records)
            return {"number": index, "status": "completed" if all(row["status"] == "observed" for row in records)
                    else "partial_compilation", "folder": str(folder), "records": records}
        except Exception as exc:
            folder.mkdir(parents=True, exist_ok=True)
            error = {"created_at": now(), "error": f"{type(exc).__name__}: {exc}",
                     "automatic_retry": False, "recovery_attempts_remaining": 0}
            if not (folder / "observation-failure.json").exists():
                write_new(folder / "observation-failure.json", error)
            return {"number": index, "status": "failed", "folder": str(folder), "records": [
                {**row, "status": "failed", "units": [], "observation_error": error,
                 "failure_directory": str(folder)} for row in chunk]}

    chunks = [rows[offset:offset + 5] for offset in range(0, len(rows), 5)]
    def resource_diagnostic(result: dict) -> bool:
        if result["status"] in {"completed", "partial_compilation", "reused_completed_recovery"}:
            return False
        folder = Path(result["folder"])
        diagnostics = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in
                                 (folder / "observation-failure.json", folder / "stderr.txt", folder / "receipt.json") if path.exists())
        return bool(re.search(r"rate.limit|quota|usage.limit|authentication|unauthorized|too many requests|\b429\b|\b401\b", diagnostics, re.I))

    # 一份显式授权可包含多批失败；分波最多五个并行请求，资源错误后不再投递下一波。
    results = []
    for offset in range(0, len(chunks), 5):
        wave = chunks[offset:offset + 5]
        with ThreadPoolExecutor(max_workers=len(wave)) as executor:
            futures = [executor.submit(recover_chunk, offset + number, chunk) for number, chunk in enumerate(wave, 1)]
            completed_wave = [future.result() for future in futures]
        results.extend(completed_wave)
        if any(resource_diagnostic(result) for result in completed_wave):
            break
    recovered = {row["image_id"]: row for result in results for row in result["records"]}
    images = []
    for previous in base["images"]:
        if previous["image_id"] not in recovered:
            images.append(previous)
            continue
        current = recovered[previous["image_id"]]
        original_folder = spec["folder_by_id"][previous["image_id"]]
        current = {**current, "execution_recovery": {
            "status": "recovered" if current["status"] == "observed" else "recovery_failed",
            "original_failure_ref": ref(original_folder / "observation-failure.json"),
            "original_receipt_ref": ref(original_folder / "receipt.json"),
            "amendment_ref": spec["amendment_ref"], "maximum_additional_attempts": 0}}
        images.append(update_derived_coverage(current))
    units = [unit for row in images for unit in row["units"]]
    initial_execution_failures = [row for row in base["images"] if row["status"] == "failed" and not (
        isinstance(row.get("observation_error"), dict) and row["observation_error"].get("failure_type") == "derived_compilation")]
    counts = {**base["counts"], **{status: sum(row["status"] == status for row in images)
              for status in ("observed", "failed", "pending")}, "units": len(units),
              "ID": sum(unit["branch"] == "ID" for unit in units),
              "CMF": sum(unit["branch"] == "CMF" for unit in units),
              "original_execution_failed_images": base["counts"].get("original_execution_failed_images", len(initial_execution_failures)),
              "authorized_execution_recovery_images": base["counts"].get("authorized_execution_recovery_images", 0) + len(rows),
              "execution_recovery_attempted_images": sum("execution_recovery" in row for row in images),
              "recovered_execution_images": sum(row.get("execution_recovery", {}).get("status") == "recovered" for row in images)}
    stop_reasons = [{"folder": result["folder"], "reason": "恢复调用出现明确限流/鉴权/配额诊断，停止后续授权投递"}
                    for result in results if resource_diagnostic(result)]
    case = {"amendment_ref": spec["amendment_ref"], "plan_ref": ref(plan_path), "original_usage_unknown": True,
            "calls": [{key: result[key] for key in ("number", "status", "folder")} for result in results],
            "not_submitted_image_ids": [row["image_id"] for row in rows if row["image_id"] not in recovered],
            "resource_stop_reasons": stop_reasons}
    effective = {**base, "updated_at": now(), "images": images, "units": units, "counts": counts,
                 "base_observations_ref": ref(base_path), "script_ref": script_snapshot(runroot),
                 "main_observations_overwritten": False,
                 "bounded_recovery_cases": base.get("bounded_recovery_cases", []) + [case]}
    write_new(effective_path, effective)
    return effective_path


def bounded_recovery(runroot: Path, amendment_paths: list[Path], timeout: int, execute: bool,
                     base_observations_path: Path | None = None) -> dict:
    """主队列结束后，执行显式列出的少量技术恢复；最后另存有效观察台账。"""
    specs = [recovery_spec(runroot, path) for path in amendment_paths]
    authorized_ids = [row["image_id"] for spec in specs for row in spec["rows"]]
    if len(authorized_ids) != len(set(authorized_ids)):
        raise ValueError("恢复授权之间的图像不可重复")
    main_path = runroot / "observations.json"
    main = json.loads(main_path.read_text(encoding="utf-8"))
    requested_base = base_observations_path.resolve() if base_observations_path else main_path
    baseline = json.loads(requested_base.read_text(encoding="utf-8"))
    frozen_sample = json.loads((runroot / "sample.json").read_text(encoding="utf-8"))
    expected_identity = {row["image_id"]: row["sha256"] for row in frozen_sample["images"]}
    actual_identity = {row["image_id"]: row["sha256"] for row in baseline["images"]}
    if actual_identity != expected_identity or len(baseline["images"]) != len(expected_identity):
        raise ValueError(f"恢复基线必须保留冻结{len(frozen_sample['images'])}张样本的每张身份与图SHA")
    if baseline["sample_ref"]["sha256"] != digest(runroot / "sample.json") or baseline["counts"]["pending"]:
        raise ValueError("恢复基线未冻结当前完整样本")
    if not execute:
        return {"created_at": now(), "model_calls": 0, "planned_recovery_calls": sum(spec["maximum_recovery_calls"] for spec in specs),
                "authorized_image_ids": authorized_ids, "amendment_refs": [spec["amendment_ref"] for spec in specs],
                "main_counts": main["counts"], "base_counts": baseline["counts"], "base_observations_ref": ref(requested_base),
                "automatic_additional_retries": False}
    expected_batches = batch_count_for(len(frozen_sample["images"]), main["batch_size"])
    if main["counts"]["pending"] or len(main["batches"]) != expected_batches:
        raise ValueError(f"主队列尚未完成：冻结{len(frozen_sample['images'])}图、每批{main['batch_size']}图应有{expected_batches}批；恢复入口不抢占活动队列")
    final_path = runroot / "observations.effective.json"
    if final_path.exists():
        raise FileExistsError("effective 台账已存在；禁止再次恢复或覆盖")
    base_path = runroot / "bounded-recovery" / "observations.main-final.json"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    if base_path.exists():
        if digest(base_path) != digest(main_path):
            raise ValueError("主队列台账与首次恢复冻结版本不同")
    else:
        with base_path.open("xb") as stream:
            stream.write(main_path.read_bytes())
    if requested_base != main_path:
        base_path = requested_base
    for spec in specs:
        base_path = recover_authorized_case(runroot, spec, base_path, timeout)
        effective = json.loads(base_path.read_text(encoding="utf-8"))
        if effective["bounded_recovery_cases"][-1]["resource_stop_reasons"]:
            raise RuntimeError(f"已保留恢复结果并停止后续投递：{base_path}")
    write_new(final_path, effective)
    return {"effective_observations_ref": ref(final_path), "counts": effective["counts"], "additional_retries": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runroot", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--concurrency-amendment", type=Path)
    parser.add_argument("--recovery-amendment", type=Path, action="append")
    parser.add_argument("--recovery-base", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    runroot = args.runroot.resolve()
    if args.recovery_amendment:
        print(json.dumps(bounded_recovery(runroot, args.recovery_amendment, args.timeout, args.execute, args.recovery_base), ensure_ascii=False), flush=True)
        return
    maximum_workers, amendment_ref = 3, None
    if args.concurrency_amendment:
        amendment = json.loads(args.concurrency_amendment.read_text(encoding="utf-8"))
        if amendment["parent_contract_ref"]["sha256"] != digest(runroot / "run-contract.json"):
            raise ValueError("并发修订不属于当前冻结合同")
        maximum_workers = amendment["changes"]["model_execution.maximum_concurrent_requests"]["current"]
        if maximum_workers != 5:
            raise ValueError("本次仅识别明确登记的并发5修订")
        amendment_ref = ref(args.concurrency_amendment)
    if not 1 <= args.batch_size <= 10 or not 1 <= args.workers <= maximum_workers:
        raise ValueError(f"本次有界授权每批至多10图，并发至多{maximum_workers}")
    sample = json.loads((runroot / "sample.json").read_text(encoding="utf-8"))
    batches = [sample["images"][i:i + args.batch_size] for i in range(0, len(sample["images"]), args.batch_size)]
    count = min(args.max_batches, len(batches)) if args.max_batches else len(batches)
    if not args.execute:
        print(json.dumps({"images": len(sample["images"]), "planned_batches": count, "workers": args.workers,
                          "model_calls": 0, "schema_version": VERSION}, ensure_ascii=False))
        return
    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = iter(enumerate(batches[:count], 1))
        active, exhausted, stop_new = {}, False, False
        while active or not exhausted:
            while not exhausted and not stop_new and len(active) < args.workers:
                try:
                    number, rows = next(pending)
                except StopIteration:
                    exhausted = True
                    break
                active[executor.submit(process_batch, runroot, rows, number, args.timeout, amendment_ref)] = number
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                active.pop(future)
                result = future.result()
                results[result["number"]] = result
                if result["status"] == "failed":
                    folder = runroot / "model-calls" / f"batch-{result['number']:03d}"
                    diagnostics = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                                             for path in (folder / "observation-failure.json", folder / "stderr.txt") if path.exists())
                    if re.search(r"rate.limit|quota|usage.limit|authentication|unauthorized|too many requests|\b429\b|\b401\b", diagnostics, re.I):
                        stop_new = True
                        write_new(runroot / f"resource-stop.batch-{result['number']:03d}.json",
                                  {"at": now(), "reason": "明确限流/鉴权/配额诊断，停止新增提交，当前请求保留且不重发",
                                   "failure_ref": ref(folder / "observation-failure.json"), "amendment_ref": amendment_ref})
                summary = save_summary(runroot, sample, results, args.batch_size)
                print(json.dumps({"batch": result["number"], "status": result["status"], "counts": summary["counts"],
                                  "stop_new_submissions": stop_new}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
