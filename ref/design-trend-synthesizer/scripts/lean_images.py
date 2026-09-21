"""读取用户 JSON 声明的本地图片关联；仅处理路径元数据，不读取图片内容。"""

from pathlib import Path

from prepare import image_ref


POSITIVE_USER_IMAGE_TAGS = frozenset({"LIKE", "ENJOY"})


def normalized_emotion_tag(value):
    """统一情绪标记；仅 LIKE / ENJOY 表示用户明确喜欢。"""
    return value.strip().upper() if isinstance(value, str) else ""


def is_positive_user_image(row):
    """判断图片关系是否明确标记为喜欢，兼容单值和汇总后的多值字段。"""
    values = [row.get("emotion_tag")]
    tags = row.get("emotion_tags", [])
    if isinstance(tags, list):
        values.extend(tags)
    return any(normalized_emotion_tag(value) in POSITIVE_USER_IMAGE_TAGS for value in values)


def linked_image_refs(child, root, record_id):
    """只保留明确 LIKE / ENJOY 的显式图片关系。"""
    refs = []
    for link in child.get("ref_pic_links", []):
        if not is_positive_user_image(link):
            continue
        ids = link.get("image_ids", [])
        for index, local in enumerate(link.get("local_paths", [])):
            if not isinstance(local, str) or not local.strip():
                continue
            ref = image_ref({"image_id": ids[index] if index < len(ids) else None,
                             "local_path": local}, Path(root), record_id,
                            link.get("code"), link.get("emotion_tag"))
            ref["association_level"] = "explicit_record_link"
            refs.append(ref)
    return refs


def selected_user_images(users, root):
    """递归收集 LIKE / ENJOY 图片路径，按绝对路径去重并保留定位。

    DISLIKE、REFERENCE 和未标注图片不进入最终图片清单；图片路径不进入
    模型文本，也不因文件存在而自动成为结论证据。
    """
    root = Path(root).resolve()
    entries = {}

    def add(local, row, pointer, uid):
        if not isinstance(local, str) or not local.strip() or not is_positive_user_image(row):
            return
        ref = image_ref({"local_path": local}, root, f"user:{uid}")
        absolute = str((root / ref["local_path"]).resolve())
        entry = entries.setdefault(absolute, {
            "path": absolute, "file_exists": Path(absolute).is_file(),
            "user_ids": [], "image_ids": [], "codes": [], "source_locations": [],
            "emotion_tags": [],
            "association_level": "selected_user_attachment", "visual_verified": False,
        })
        for key, value in (("user_ids", uid), ("image_ids", row.get("image_id")),
                           ("codes", row.get("code") or row.get("ref_pic_code"))):
            if value is not None and value not in entry[key]:
                entry[key].append(value)
        emotion = normalized_emotion_tag(row.get("emotion_tag"))
        if emotion and emotion not in entry["emotion_tags"]:
            entry["emotion_tags"].append(emotion)
        location = {"user_id": uid, "json_pointer": pointer}
        if location not in entry["source_locations"]:
            entry["source_locations"].append(location)

    def walk(value, pointer, uid):
        if isinstance(value, dict):
            for key, child in value.items():
                child_pointer = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
                if key == "local_path":
                    add(child, value, child_pointer, uid)
                elif key == "local_paths" and isinstance(child, list):
                    for index, local in enumerate(child):
                        ids = value.get("image_ids", [])
                        row = {**value, "image_id": ids[index] if index < len(ids) else value.get("image_id")}
                        add(local, row, child_pointer + f"/{index}", uid)
                else:
                    walk(child, child_pointer, uid)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, pointer + f"/{index}", uid)

    for index, user in enumerate(users):
        walk(user, f"/users/{index}", str(user["id"]))
    return list(entries.values())
