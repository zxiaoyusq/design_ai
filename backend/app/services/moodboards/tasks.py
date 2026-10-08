"""旧情绪板历史读取与冻结版本校验；不再执行纯文本生成。"""

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from threading import RLock

from app.schemas.moodboards import Assignments, Clusters, CuratedAssignments, CuratedClusters, CuratedClustersV3
from app.services.dna import storage

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SKILL_FILE = PROJECT_ROOT / "ref/moodboard-generator/SKILL.md"
ACTIVE = {"queued", "running"}
LEGACY_EXECUTION_STOP_REASON = "已切换同事 v2 原生视觉流程；旧 DNA 文本 4–8 张生成与续跑已停用。请使用原生设计转译、实际裁图、独立整板复核链，网页仅接收已校验的结果。"


def now():
    return datetime.now(UTC).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def write(path, value):
    storage._atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode())


def dna_projection(business):
    """按字段投影语义信息，保留证据与不确定性；不截断字段值或载入图片。"""
    style = business.get("style", {})
    return {
        "object": business.get("object", {}),
        "style": {k: v for k, v in style.items() if k in {"composition_summary", "primary", "primary_style"}}
        | {"style_candidates": [{k: v for k, v in candidate.items()
                                  if k in {"style_id", "label_zh", "confidence_score", "main_conflicts",
                                           "rank", "match_score", "main_support", "regions", "facet_ids"}}
                                 for candidate in style.get("style_candidates", style.get("tags", []))]},
        # 证据中的整体覆盖与局部限定是主导性判断依据，不能仅保留关键词和置信度。
        "key_dna": [{k: v for k, v in item.items()
                     if k in {"group", "name", "value", "confidence_score", "inference_note", "region", "evidence"}}
                    for item in business.get("key_dna", [])],
        "semantic_profile": business.get("semantic_profile", {}),
        "novel_dna": business.get("novel_dna", []),
        "quality": business.get("quality", {}),
    }


def resolve_pointer(value, pointer):
    """证据必须指向模型实际收到的 DNA 字段，禁止空路径与虚构证据。"""
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError(f"无效 DNA 证据路径：{pointer}")
    try:
        for part in pointer[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise ValueError("无效数组下标")
                value = value[int(key)]
            else:
                value = value[key]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"DNA 证据路径不存在：{pointer}") from exc
    if value is None or value == "" or value == [] or value == {}:
        raise ValueError(f"DNA 证据路径为空：{pointer}")
    return value


def validate_assignments(data, images, directions, version="v1"):
    """每个输入恰好出现一次，方向与证据必须属于冻结输入。"""
    schema = CuratedAssignments if version in {"v2", "v3"} else Assignments
    parsed = schema.model_validate(data).model_dump()["assignments"]
    known = {image["result_id"]: image["dna"] for image in images}
    if Counter(x["result_id"] for x in parsed) != Counter(known.keys()):
        raise ValueError("方向匹配输出存在重复、遗漏或未知图片")
    allowed = {direction["id"] for direction in directions}
    for item in parsed:
        if item["direction_id"] is not None and item["direction_id"] not in allowed:
            raise ValueError("模型返回未选择的趋势方向")
        if any(did not in allowed for did in item.get("competing_direction_ids", [])):
            raise ValueError("模型返回未选择的竞争方向")
        for pointer in item["evidence_paths"]:
            resolve_pointer(known[item["result_id"]], pointer)
    return parsed


def validate_clustering(data, result_ids, version="v1"):
    """v1 全部分区；v2/v3 精选与未入选共同覆盖候选，按冻结版本校验成板下限。"""
    schema = {"v2": CuratedClusters, "v3": CuratedClustersV3}.get(version, Clusters)
    parsed = schema.model_validate(data).model_dump()
    clusters = parsed["clusters"]
    if len({c["id"] for c in clusters}) != len(clusters):
        raise ValueError("类别 ID 不能重复")
    if len({c["name"] for c in clusters}) != len(clusters):
        raise ValueError("类别名称不能重复")
    accounted = [rid for c in clusters for rid in c["result_ids"]]
    accounted.extend(item["result_id"] for item in parsed.get("excluded", []))
    if Counter(accounted) != Counter(result_ids):
        raise ValueError("方向内分类存在重复、遗漏或跨方向图片")
    return {"clusters": clusters, "excluded": parsed.get("excluded", [])}


def validate_clusters(data, result_ids, version="v1"):
    """兼容旧调用方的列表返回值；新流程通过 validate_clustering 保留排除原因。"""
    return validate_clustering(data, result_ids, version)["clusters"]


def assignment_batches(images):
    """分包只限制匹配阶段，每包都与全部方向比较；不会改变方向内二次聚类范围。"""
    batches, batch, size = [], [], 0
    for image in images:
        length = len(encode(image))
        if length > 35_000:
            raise ValueError("单张 DNA 文本过大，请选择其他结果")
        if batch and (size + length > 35_000 or len(batch) >= 10):
            batches.append(batch)
            batch, size = [], 0
        batch.append(image)
        size += length
    if batch:
        batches.append(batch)
    return batches


class MoodboardManager:
    """旧网页任务只读档案；新原生视觉链由独立入口执行与投影。"""

    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root)
        self.output = self.root / "data/result/moodboards"
        self._lock = RLock()

    def _folder(self, task_id):
        if not re.fullmatch(r"mb_[a-f0-9]{32}", task_id):
            raise FileNotFoundError("情绪版任务不存在")
        folder = self.output / task_id
        if not (folder / "task.json").is_file():
            raise FileNotFoundError("情绪版任务不存在")
        return folder


    def _trend(self, task_id):
        if not re.fullmatch(r"web_[a-f0-9]{32}", task_id):
            raise FileNotFoundError("趋势任务不存在")
        folder = self.root / "data/result/high_trend" / task_id
        task = read(folder / "web_task.json")
        if task["status"] not in {"completed", "partial"}:
            raise ValueError("请选择已有有效结果的高潜趋势任务")
        result = read(folder / "high_potential_trends.json")
        return task, result


    def _dna_trace(self, result_id):
        return storage._trace_data(result_id) or {}


    @staticmethod
    def _identity(result_id, trace):
        source = trace.get("input_image", {})
        # 同图多次提取按原始图片哈希归一；旧资料缺少哈希时使用稳定来源身份。
        return (source.get("sha256") or trace.get("image_id") or source.get("path")
                or result_id)


    def catalog(self):
        """只列出可选趋势及每个来源图片的最新成功 DNA。"""
        trend_tasks = []
        for path in (self.root / "data/result/high_trend").glob("web_*/web_task.json"):
            try:
                task, result = self._trend(path.parent.name)
            except (FileNotFoundError, ValueError):
                continue
            directions = [{k: card.get(k, "") for k in ("id", "title", "description")}
                          for card in result.get("trends", [])]
            if directions:
                trend_tasks.append({"id": task["id"], "created_at": task["created_at"], "directions": directions})
        unique, images = set(), []
        for item in storage.list_results():
            identity = self._identity(item["id"], self._dna_trace(item["id"]))
            if identity not in unique:
                unique.add(identity)
                images.append({**item, "created_at": str(item["created_at"])})
        return {"trend_tasks": sorted(trend_tasks, key=lambda t: t["created_at"], reverse=True),
                "dna_results": images,
                "execution": {"supported": False, "workflow": "colleague_v2_native", "reason": LEGACY_EXECUTION_STOP_REASON}}


    def list(self):
        with self._lock:
            tasks = [read(path) for path in self.output.glob("mb_*/task.json")]
        # 历史列表不重复发送每张图片的分析正文。
        return sorted([{**task, "result": None} for task in tasks], key=lambda t: t["created_at"], reverse=True)


    def get(self, task_id):
        with self._lock:
            return read(self._folder(task_id) / "task.json")


    def download(self, task_id):
        path = self._folder(task_id) / "result.json"
        if not path.is_file():
            raise FileNotFoundError("情绪版结果尚未生成")
        return path


    def create(self, request):
        """停用旧纯文本创建；不创建任务或调用模型。"""
        raise RuntimeError(LEGACY_EXECUTION_STOP_REASON)

    def resume(self, task_id):
        """停用旧任务续跑，原历史结果仍可只读查看。"""
        raise RuntimeError(LEGACY_EXECUTION_STOP_REASON)

    def run(self, task_id):
        """不允许私下执行已停用的旧状态机。"""
        raise RuntimeError(LEGACY_EXECUTION_STOP_REASON)


moodboard_manager = MoodboardManager()
