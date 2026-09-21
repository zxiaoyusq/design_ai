"""从本地用研资料生成 50 人的前端演示快照，不调用模型或写回源数据。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/userreseach_data"
OUTPUT = ROOT / "frontend/src/data/userResearch.ts"
USER_LIMIT = 50


def js(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def snippet(value: object, limit: int = 220) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def liked_ids(user: dict) -> set[str]:
    return {
        item["image_id"]
        for item in user["image_preferences"]
        if str(item["emotion_tag"]).upper() == "ENJOY"
    }


def similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def split_by_likes(users: list[dict], likes: dict[str, set[str]]) -> list[list[dict]]:
    """用喜欢图片的 Jaccard 重叠做两簇 medoid 演示分组，固定输入顺序保证可重建。"""
    first = max(users, key=lambda user: sum(similarity(likes[user["id"]], likes[peer["id"]]) for peer in users))
    second = min((user for user in users if user != first), key=lambda user: similarity(likes[user["id"]], likes[first["id"]]))
    seeds = [first, second]
    groups: list[list[dict]] = [[], []]
    for _ in range(5):
        groups = [[], []]
        for user in users:
            index = max(range(2), key=lambda i: (similarity(likes[user["id"]], likes[seeds[i]["id"]]), -i))
            groups[index].append(user)
        if any(not group for group in groups):
            raise ValueError("图片偏好无法形成两个非空分组")
        seeds = [
            max(group, key=lambda user: sum(similarity(likes[user["id"]], likes[peer["id"]]) for peer in group))
            for group in groups
        ]
    return groups


def excerpt_for(user: dict) -> list[dict]:
    terms = ("手机", "外观", "设计", "颜色", "质感", "摄像头", "后盖")
    answers = sorted(
        user["aesthetic_research"],
        key=lambda item: (
            -sum(term in f'{item.get("question", "")}{item.get("ai_analysis", "")}' for term in terms),
            -len(str(item.get("ai_analysis") or "")),
        ),
    )
    result = []
    for item in answers:
        answer = str(item.get("ai_analysis") or "").strip()
        if not answer or "无明确提及" in answer:
            continue
        result.append({"id": item["id"], "kind": "问答分析", "question": str(item.get("question") or ""), "answer": snippet(answer)})
        if len(result) == 2:
            break
    demands = [item for item in user["demand_research"] if item.get("ai_index")]
    if demands:
        item = max(demands, key=lambda row: sum(term in str(row.get("scenario") or "") for term in terms))
        result.append({"id": item["id"], "kind": "需求记录", "question": str(item.get("scenario") or "需求记录"), "answer": snippet(item["ai_index"])})
    return result


def main() -> None:
    user_source = SOURCE / "users.json"
    image_source = SOURCE / "images.json"
    users = json.loads(user_source.read_text(encoding="utf-8"))["users"]
    images = {item["id"]: item for item in json.loads(image_source.read_text(encoding="utf-8"))["images"]}
    downloaded = {image_id for image_id, item in images.items() if item.get("status") == "downloaded" and item.get("local_path") and (SOURCE / item["local_path"]).is_file()}
    likes = {user["id"]: liked_ids(user) & downloaded for user in users}

    # 图片反馈优先，剩余名额各取巴基斯坦、印度的访谈记录；总数严格为 50 人。
    selected = [user for user in users if likes[user["id"]]]
    photo_user_count = len(selected)
    remaining = USER_LIMIT - len(selected)
    if remaining < 0 or remaining % 2:
        raise ValueError("源资料变化后请重新核对 50 人抽样规则")
    for country in ("Pakistan", "India"):
        candidates = [user for user in users if user["profile"]["country"] == country and not likes[user["id"]]]
        selected.extend(sorted(candidates, key=lambda user: (-len(user["aesthetic_research"]), user["id"]))[: remaining // 2])
    if len(selected) != USER_LIMIT or len({user["id"] for user in selected}) != USER_LIMIT:
        raise ValueError("无法组成 50 位互异用户")

    groups: list[tuple[str, str, str, list[dict]]] = []
    for country, label in (("Indonesia", "印尼"), ("Malaysia", "马来西亚")):
        people = [user for user in selected if user["profile"]["country"] == country]
        for index, group in enumerate(split_by_likes(people, likes), start=1):
            groups.append((f"{country.lower()}-{index}", f"{label}偏好簇 {index:02d}", country, group))
    no_feedback = [user for user in selected if not likes[user["id"]]]
    groups.append(("interview", "访谈待配图", "Pakistan / India", no_feedback))

    group_image_ids = []
    group_votes: dict[str, Counter] = {}
    for group_id, _, _, members in groups:
        votes = Counter(image_id for user in members for image_id in likes[user["id"]])
        group_votes[group_id] = votes
        group_image_ids.append([image_id for image_id, _ in sorted(votes.items(), key=lambda item: (-item[1], item[0]))[:6]])

    all_votes = Counter(image_id for user in selected for image_id in likes[user["id"]])
    rendered_users = []
    used_images = set(image_id for ids in group_image_ids for image_id in ids)
    cohort_of = {user["id"]: group_id for group_id, _, _, members in groups for user in members}
    for user in selected:
        profile = user["profile"]
        votes = group_votes[cohort_of[user["id"]]]
        top_images = sorted(likes[user["id"]], key=lambda image_id: (-votes[image_id], image_id))[:4]
        used_images.update(top_images)
        def plain(value: object) -> str:
            if isinstance(value, list):
                return "、".join(str(item).removeprefix("ID_") for item in value)
            return str(value or "")
        rendered_users.append({
            "id": user["id"], "bid": user["bid"], "cohortId": cohort_of[user["id"]],
            "country": profile["country"], "age": profile.get("age"), "gender": plain(profile.get("gender")),
            "profession": plain(profile.get("profession")), "phoneBrand": plain(profile.get("using_mobile_phone_brand")),
            "enjoyCount": sum(str(item["emotion_tag"]).upper() == "ENJOY" for item in user["image_preferences"]),
            "dislikeCount": sum(str(item["emotion_tag"]).upper() == "DISLIKE" for item in user["image_preferences"]),
            "images": top_images, "excerpts": excerpt_for(user),
        })

    rendered_groups = []
    for group_id, name, country, members in groups:
        overlaps = [sum(bool(likes[user["id"]] & set(topic)) for user in members) for topic in group_image_ids[:4]]
        rendered_groups.append({
            "id": group_id, "name": name, "country": country, "userIds": [user["id"] for user in members],
            "enjoyCount": sum(sum(str(item["emotion_tag"]).upper() == "ENJOY" for item in user["image_preferences"]) for user in members),
            "imageIds": group_image_ids[len(rendered_groups)],
            "imageVotes": {image_id: group_votes[group_id][image_id] for image_id in group_image_ids[len(rendered_groups)]},
            "overlaps": overlaps,
        })

    lines = [
        "// 由 frontend/scripts/prepare_user_research.py 从 data/userreseach_data 离线生成；不含模型判断。",
        f"// users.json SHA-256: {hashlib.sha256(user_source.read_bytes()).hexdigest()}",
        f"// images.json SHA-256: {hashlib.sha256(image_source.read_bytes()).hexdigest()}",
        "import type { ResearchCohort, ResearchImage, ResearchUser } from '@/types/userResearch'",
        "",
        f"export const researchMethod = '选取 {photo_user_count} 位有可用 ENJOY 图片反馈的用户，再从巴基斯坦、印度访谈用户各取 {remaining // 2} 位；按 ENJOY 图片重叠进行轻量分组。'",
        f"export const researchUsers: ResearchUser[] = {js(rendered_users)}",
        f"export const researchCohorts: ResearchCohort[] = {js(rendered_groups)}",
        "export const researchImages: Record<string, ResearchImage> = {",
    ]
    for image_id in sorted(used_images):
        item = images[image_id]
        relative = "../../../data/userreseach_data/" + item["local_path"]
        lines.append(f"  {js(image_id)}: {{ id: {js(image_id)}, src: new URL({js(relative)}, import.meta.url).href, enjoyedBy: {all_votes[image_id]} }},")
    lines.extend(["}", ""])
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {len(rendered_users)} 位用户、{len(rendered_groups)} 组、{len(used_images)} 张被选中用户标记 ENJOY 的图片")


if __name__ == "__main__":
    main()
