"""高潜选材 → 已有设计卡核验／显式补缺 → 原生统一情绪聚类的网页适配。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
import fcntl
from functools import lru_cache, partial
import hashlib
import importlib.util
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from PIL import Image

from app.agents.design_dna_preparation import DEFAULT_MODEL, execution_config, execute_structured
from app.services.dna import preparation
from app.services.dna.storage import PROJECT_ROOT, _atomic_write
from app.services.llm.catalog import get_model, list_models
from app.services.moodboards.sources import MoodboardSources


SKILL_ROOT = PROJECT_ROOT / ".agents/skills/prism-dna-cluster-moodboard"


@lru_cache(maxsize=1)
def grouping():
    """直接复用 Skill 的跨批发现、路由、真实图片选组和约束检查。"""
    spec = importlib.util.spec_from_file_location("prism_web_llm_group", SKILL_ROOT / "scripts/llm_group.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def now():
    return datetime.now(UTC).isoformat()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    _atomic_write(Path(path), (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class MoodboardClusteringManager:
    """新任务独立归档；旧网页任务和历史卡原文不被覆盖，也不自动续费或重试。"""

    def __init__(self, root=PROJECT_ROOT, *, sources=None, prepared=preparation):
        self.root = Path(root).resolve()
        self.output = self.root / "data/result/moodboard_clustering_web"
        self.sources = sources or MoodboardSources(self.root)
        self.prepared = prepared
        self.lock = RLock()

    def catalog(self):
        source = self.sources.catalog()
        return {**source, "default_model": DEFAULT_MODEL,
                "models": [{"id": row.id, "name": row.name} for row in list_models()],
                "rules": {"min_images": 6, "max_images": 10, "category_max_ratio": .5},
                "skill": "prism-dna-cluster-moodboard", "comparison_mode": "unified"}

    def _prepared_index(self):
        # 本阶段只列摘要，深度核验原答和实际像素在确认后的准备阶段执行。
        try:
            rows = self.prepared.list_prepared_results()
        except (OSError, ValueError, KeyError) as exc:
            return {}, [f"已有 DNA 索引暂不可用：{type(exc).__name__}；不会因此自动重新提取。"]
        by_sha = {}
        for row in sorted(rows, key=lambda item: item.get("created_at", "")):
            if row.get("card_count", 0) and row.get("schema_valid"):
                by_sha[row["image_sha256"]] = row
        return by_sha, []

    def preview(self, request):
        scope = self.sources.scope(request.source_result_id, request.direction_ids)
        index, warnings = self._prepared_index()
        images = []
        for row in scope["images"]:
            dna = index.get(row["sha256"])
            images.append({**row, "id": row["sha256"], "image_name": Path(row["path"]).name,
                           "status": "ready" if dna else "missing_dna", "prepared_result_id": dna["id"] if dna else None,
                           "card_count": dna["card_count"] if dna else 0, "category": dna.get("category") if dna else None,
                           "reason": "已有冻结设计卡，执行前核验原始证据" if dna else "缺少可复用设计卡"})
        counts = {"total_images": len(images), "ready_images": sum(row["status"] == "ready" for row in images),
                  "missing_dna": sum(row["status"] == "missing_dna" for row in images),
                  "ready_cards": sum(row["card_count"] for row in images),
                  "unavailable_images": len(scope["missing"]), "excluded_images": len(scope["excluded"])}
        preview_id = "mbp_" + uuid4().hex
        document = {"preview_id": preview_id, "created_at": now(), "request": request.model_dump(),
                    "scope": scope, "source": scope["result"], "images": images, "counts": counts,
                    "warnings": scope.get("warnings", []) + warnings, "dna_index_available": not warnings}
        write(self.output / "previews" / f"{preview_id}.json", document)
        return self._public_preview(document)

    @staticmethod
    def _public_preview(document):
        keys = ("id", "image_name", "preview_url", "status", "reason", "card_count", "category")
        result = {key: document[key] for key in ("preview_id", "created_at", "source", "counts", "warnings")}
        result["images"] = [{key: row.get(key) for key in keys} for row in document["images"]]
        # 缺图和人工排除另列，绝不算作已送模型或视觉拒绝。
        result["unavailable"] = document["scope"]["missing"]
        result["excluded"] = document["scope"]["excluded"]
        return result

    def _folder(self, task_id):
        if not re.fullmatch(r"mbc_[a-f0-9]{32}", task_id):
            raise FileNotFoundError("图片聚类任务不存在")
        folder = self.output / task_id
        if not (folder / "task.json").is_file():
            raise FileNotFoundError("图片聚类任务不存在")
        return folder

    def get(self, task_id):
        with self.lock:
            folder = self._folder(task_id)
            task = read(folder / "task.json")
            if task["status"] in {"queued", "running"}:
                try:
                    os.kill(task["owner_pid"], 0)
                except ProcessLookupError:
                    task.update(status="failed", stage="interrupted", updated_at=now(),
                                message="服务已中断，证据保留；没有自动重发模型请求", can_resume=False)
                    write(folder / "task.json", task)
            return {key: value for key, value in task.items() if key != "owner_pid"}

    def list(self):
        tasks = [self.get(path.parent.name) for path in self.output.glob("mbc_*/task.json")]
        return sorted([{**task, "result": None} for task in tasks], key=lambda task: task["created_at"], reverse=True)

    def create(self, request):
        get_model(request.model_id)
        path = self.output / "previews" / f"{request.preview_id}.json"
        if not path.is_file():
            raise FileNotFoundError("请先预览本次高潜图片范围")
        preview = read(path)
        if not preview.get("dna_index_available", True):
            raise ValueError("已有 DNA 索引不可读取，请先修复索引；不能将索引故障当作全量缺失重提")
        current = self.sources.scope(**{"result_id": preview["request"]["source_result_id"],
                                        "direction_ids": preview["request"]["direction_ids"]})
        if current["input_digest"] != preview["scope"]["input_digest"]:
            raise ValueError("高潜来源、图片或人工反馈已变化，请重新预览确认")
        if not preview["counts"]["ready_images"] and not request.prepare_missing:
            raise ValueError("没有可用 DNA；请确认补缺，或先在 DNA 提取页完成准备")
        if not preview["images"]:
            raise ValueError("所选结果没有可用图片")
        # 跨进程锁避免双击或多个 Web worker 同时启动昂贵任务。
        self.output.mkdir(parents=True, exist_ok=True)
        with self.lock, (self.output / ".create.lock").open("a") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            if any(task["status"] in {"queued", "running"} for task in self.list()):
                raise RuntimeError("已有图片聚类任务运行中，请等待结束")
            if any(task["request"]["preview_id"] == request.preview_id for task in self.list()):
                raise ValueError("本次预览已经提交；如需新运行，请重新预览并确认")
            task_id = "mbc_" + uuid4().hex
            folder = self.output / task_id
            write(folder / "input.json", preview)
            configuration = execution_config(request.model_id)
            write(folder / "contract.json", {"schema_version": "prism.web_moodboard_clustering.v1",
                  "request": request.model_dump(), "input_sha256": fingerprint(preview),
                  "execution_config": configuration, "comparison_mode": "unified", "mode": "full_catalogue",
                  "independent_review": False, "automatic_retries": False,
                  "skill_files": self._skill_identity()})
            task = {"id": task_id, "created_at": now(), "updated_at": now(), "status": "queued",
                    "stage": "queued", "message": "等待核验本次选材与已有设计卡", "owner_pid": os.getpid(),
                    "request": request.model_dump(), "counts": preview["counts"], "source": preview["source"],
                    "progress": {"calls_started": 0, "max_calls": request.max_calls}, "can_resume": False,
                    "result": None, "error": None}
            write(folder / "task.json", task)
        return self.get(task_id)

    @staticmethod
    def _skill_identity():
        paths = [path for path in SKILL_ROOT.rglob("*") if path.is_file() and path.suffix in {".py", ".md"}]
        paths += list((preparation.SKILL_ROOT / "scripts").glob("*.py"))
        paths += list((preparation.SKILL_ROOT / "references").glob("*.md"))
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}

    def _update(self, task_id, **values):
        with self.lock:
            path = self._folder(task_id) / "task.json"
            task = read(path)
            if "progress" in values:
                # 并发回执可能乱序抵达；累计启动次数不可被较早事件回退。
                values["progress"]["calls_started"] = max(values["progress"]["calls_started"],
                                                          task["progress"]["calls_started"])
            task.update(**values, updated_at=now())
            write(path, task)

    def _validated_cards(self, result_id, expected_sha):
        result = self.prepared.load_prepared_result(result_id)
        if result["source"]["image_sha256"] != expected_sha or not result["validation"]["native_evidence_verified"]:
            raise ValueError("设计卡不属于当前原图或原始证据未通过")
        return result["cards"]

    def run(self, task_id):
        folder = self._folder(task_id)
        # 后台调度重复执行也不会产生第二轮请求。
        with (folder / ".run.lock").open("a") as guard:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            if self.get(task_id)["status"] != "queued":
                return
            try:
                self._run(task_id)
            except Exception as exc:
                self._update(task_id, status="failed", stage="failed", error=str(exc)[:1500],
                             message="执行未完成；已保存阶段证据，不自动重试或重提 DNA")

    def _run(self, task_id):
        folder = self._folder(task_id)
        task, preview, contract = self.get(task_id), read(folder / "input.json"), read(folder / "contract.json")
        request = task["request"]
        if fingerprint(preview) != contract["input_sha256"] or self._skill_identity() != contract["skill_files"]:
            raise ValueError("确认后的输入或 Skill 实现已变化，请创建新任务")
        if execution_config(request["model_id"]) != contract["execution_config"]:
            raise ValueError("确认后的模型执行配置已变化")
        for binding in preview["scope"].get("source_refs", []):
            if hashlib.sha256(Path(binding["path"]).read_bytes()).hexdigest() != binding["sha256"]:
                raise ValueError("确认后的高潜来源或人工反馈发生变化，请重新预览")
        self._update(task_id, status="running", stage="preparation", message="核验已有 DNA；聚类阶段不会补写 DNA")
        cards, ledger, missing = [], [], []
        for row in preview["images"]:
            if not row["prepared_result_id"]:
                missing.append(row)
                continue
            try:
                valid = self._validated_cards(row["prepared_result_id"], row["sha256"])
                cards.extend(valid)
                ledger.append({"sha256": row["sha256"], "result_id": row["prepared_result_id"], "status": "reused", "cards": len(valid)})
            except Exception as exc:
                # 已有卡核验失败不转成缺卡后盲目重提；保持真实失败和人工处理入口。
                ledger.append({"sha256": row["sha256"], "status": "invalid_evidence", "reason": str(exc)[:500]})
        new_calls = 0
        stop_preparation = False

        def prepare(row):
            nonlocal new_calls, stop_preparation
            with self.lock:
                if stop_preparation or new_calls >= request["max_calls"]:
                    return [], {"sha256": row["sha256"], "status": "not_sent_budget_or_provider"}
                new_calls += 1
                self._update(task_id, progress={"calls_started": new_calls, "max_calls": request["max_calls"]},
                             message=f"DNA 补缺：已启动 {new_calls} 次；完成全部准备后才开始聚类")
            try:
                path = Path(row["path"])
                if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                    raise ValueError("选材原图字节已变化")
                output = self.prepared.run_preparation_extraction(image_path=path,
                    content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    model_id=request["model_id"], user_prompt="")
                valid = self._validated_cards(output.result_id, row["sha256"])
                return valid, {"sha256": row["sha256"], "result_id": output.result_id, "status": "prepared", "cards": len(valid)}
            except Exception as exc:
                reason = str(exc)[:700]
                if getattr(exc, "stop_new_calls", False) or any(token in reason.lower() for token in ("429", "401", "403", "quota", "rate limit", "额度", "余额", "鉴权")):
                    with self.lock:
                        stop_preparation = True
                return [], {"sha256": row["sha256"], "status": "preparation_failed", "reason": reason,
                            "result_id": getattr(exc, "result_id", None), "stop_new_calls": stop_preparation}

        if request["prepare_missing"]:
            with ThreadPoolExecutor(max_workers=request["workers"]) as pool:
                for valid, row in pool.map(prepare, missing):
                    cards.extend(valid)
                    ledger.append(row)
                    write(folder / "preparation-ledger.json", ledger)
        else:
            ledger.extend({"sha256": row["sha256"], "status": "missing_dna_not_authorized"} for row in missing)
        write(folder / "preparation-ledger.json", ledger)
        if not cards:
            result = {"boards": [], "small_groups": [], "summary": {"preparation": ledger, "dna_calls": new_calls}}
            write(folder / "result.json", result)
            self._update(task_id, status="partial", stage="preparation_incomplete", message="没有通过核验的设计卡，未启动聚类",
                         result=result)
            return
        if len({card["card_id"] for card in cards}) != len(cards):
            raise ValueError("多个设计卡快照出现重复卡号，未擅自改写身份")
        # 新高潜关联只扩充可核验来源别名用于排重，原卡/原答/ROI 原文单独保存、不回写。
        write(folder / "verified-cards.original.json", cards)
        projected = deepcopy(cards)
        by_sha = {row["sha256"]: row for row in preview["images"]}
        for card in projected:
            source = by_sha[card["image_sha256"]]
            aliases = [{key: origin[key] for key in ("article_id", "project_id") if origin.get(key)}
                       for origin in source.get("origins", [])]
            for alias in aliases:
                if alias and alias not in card["sources"]:
                    card["sources"].append(alias)
        document = {"schema_version": "prism.web_verified_design_cards_projection.v1", "cards": projected,
                    "images": ledger, "preparation_sources": ledger, "source_scope_digest": preview["scope"]["input_digest"],
                    "source_alias_enrichment_only": True}
        write(folder / "verified-cards.json", document)
        module = grouping()
        remaining = request["max_calls"] - new_calls
        if stop_preparation or remaining <= 0:
            result = {"boards": [], "small_groups": [], "summary": {"preparation": ledger, "dna_calls": new_calls}}
            write(folder / "result.json", result)
            self._update(task_id, status="partial", stage="preparation_incomplete", message="准备阶段已停止或预算用尽；设计卡保留，未启动聚类",
                         result=result)
            return
        self._update(task_id, stage="clustering", message=f"准备完成：{len(cards)} 张有效设计卡；开始跨批统一情绪聚类")
        out = folder / "grouping"
        out.mkdir()

        def progress(event):
            self._update(task_id, stage=event.get("stage", "clustering"),
                         message=f"图片聚类 · {event.get('stage', 'clustering')}；正在比较冻结 DNA 和真实图片",
                         progress={"calls_started": new_calls + event.get("model_calls_started", 0), "max_calls": request["max_calls"]})

        calls = module.ModelCalls(out, "", workers=request["workers"], max_calls=remaining,
                    execute=partial(execute_structured, model_id=request["model_id"]),
                    execution_config=contract["execution_config"], progress_callback=progress, comparison_mode="unified")
        output = module.run_pipeline(document, calls, mode="full_catalogue", card_batch_size=32, visual_batch_size=16)
        for name, value in output.items():
            write(out / f"{name}.json", value)
        result = self._project_result(task_id, output, document, preview)
        result["summary"]["preparation"] = ledger
        result["summary"]["dna_calls"] = new_calls
        result["summary"]["human_approved"] = False
        result["summary"]["source_selection_is_not_cluster_boundary"] = True
        write(folder / "result.json", result)
        partial_result = output["clusters"]["summary"]["status"] == "partial" or any(row["status"] not in {"reused", "prepared"} for row in ledger)
        self._update(task_id, status="partial" if partial_result else "completed", stage="finished", result=result,
                     progress={"calls_started": new_calls + calls.attempted, "max_calls": request["max_calls"]},
                     message=f"已生成 {len(result['boards'])} 张候选板；保留未处理和未入组原因，待人工确认")

    def _project_result(self, task_id, output, document, preview):
        cards = {card["card_id"]: card for card in document["cards"]}
        images = {row["sha256"]: row for row in preview["images"]}
        boards = []
        for board in output["boards"]["boards"]:
            members = []
            evidence = {entry["card_id"]: entry for entry in board.get("member_evidence", [])}
            for member in board["members"]:
                card = cards[member["unit_id"]]
                original = images[card["image_sha256"]]
                token = hashlib.sha256(card["card_id"].encode()).hexdigest()
                base = f"/api/v1/moodboards/clustering/tasks/{task_id}/images/{token}"
                members.append({"id": token, "card_id": card["card_id"], "image_name": original["image_name"],
                                "preview_url": base, "original_url": base + "?original=true", "category": card["category"],
                                "display_bbox": card["display_bbox"],
                                "reason": evidence.get(card["card_id"], {}).get("support", card["subject"]["identity"]),
                                "strongest_difference": evidence.get(card["card_id"], {}).get("strongest_difference"),
                                "why_coordinated": evidence.get(card["card_id"], {}).get("why_coordinated")})
            boards.append({"id": board["board_id"], "title": board.get("name", board.get("title", board["board_id"])),
                           "description": board.get("dominant_relation", board.get("description", board.get("rationale", ""))),
                           "status": "model_selected_not_human_approved", "members": members,
                           "constraints": board.get("constraint_check", board.get("constraints", {}))})
        return {"boards": boards, "small_groups": [row for row in output["clusters"]["clusters"] if row["status"] != "model_grouped"],
                "summary": output["clusters"]["summary"], "residual_cards": output["clusters"]["residual_cards"]}

    def image(self, task_id, token, original=False):
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise FileNotFoundError("情绪板图片不存在")
        folder = self._folder(task_id)
        document = read(folder / "verified-cards.json")
        card = next((row for row in document["cards"] if hashlib.sha256(row["card_id"].encode()).hexdigest() == token), None)
        if card is None:
            raise FileNotFoundError("情绪板图片不存在")
        path = Path(card["local_path"]).resolve()
        if not path.is_relative_to(self.root / "data") or hashlib.sha256(path.read_bytes()).hexdigest() != card["image_sha256"]:
            raise ValueError("冻结原图路径或字节校验失败")
        if original:
            return path
        crop = folder / "display" / f"{token}.png"
        if not crop.exists():
            x, y, w, h = card["display_bbox"]
            with Image.open(path) as source:
                bounds = (max(0, math.floor(x * source.width)), max(0, math.floor(y * source.height)),
                          min(source.width, math.ceil((x+w)*source.width)), min(source.height, math.ceil((y+h)*source.height)))
                buffer = io.BytesIO()
                source.crop(bounds).save(buffer, "PNG")
                _atomic_write(crop, buffer.getvalue())
        return crop

    def download(self, task_id):
        path = self._folder(task_id) / "result.json"
        if not path.is_file():
            raise FileNotFoundError("本次尚未生成聚类结果")
        return path


moodboard_clustering_manager = MoodboardClusteringManager()
