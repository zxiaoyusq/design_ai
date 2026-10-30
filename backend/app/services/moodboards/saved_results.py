"""已交付 Skill 情绪板的只读投影；保留当时成员、取景、合同和质量结论。"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image

from app.services.dna.storage import PROJECT_ROOT, _atomic_write


BASE = Path("data/result/dna_cluster_moodboard")
DEFAULT_RESULT_ID = "bounded-three-20261012"
# 仅登记两个已正式交付的最终快照，不把中间检查点和外部 PPT 混入 Skill 结果。
RUNS = {
    DEFAULT_RESULT_ID: {
        "title": "1600 图 · 三张五图候选（2026-10-12）",
        "folder": BASE / "sample1600_bounded_three_20261011",
        "boards": "final-candidates/boards.json", "manifest": "delivery-final/delivery-manifest.json",
        "review": "delivery-final/data/current-assessment.json", "kind": "bounded",
        "status_label": "1 板当前对照支持 · 2 板需要修改",
        "notes": ["本次沿用当时每板至少 5 张的有界合同，三张候选各 5 张。", "原记录未完成三板全部达到参考标准的目标，均未经设计师批准。"],
    },
    "reference-aligned-20261010": {
        "title": "1600 图 · 定点修订后候选（2026-10-10）",
        "folder": BASE / "sample1600_balanced_llm_20261010",
        "boards": "targeted-revision-v4/boards.json", "manifest": "result-manifest.json",
        "kind": "reference", "status_label": "2 板 AI 参考对照通过 · 1 板未独立审阅",
        "notes": ["保留最后一次定点修订的三张候选，不重复列出修订前的同一组板。", "AI 参考对照结论属于当时的审阅范围；设计师批准仍为未确认。"],
    },
}
RELATIONS = {"palette": "配色组织", "silhouette": "廓形与比例", "planes": "块面与体量",
             "lines": "线条关系", "optics": "光学质感", "texture": "纹理与图案", "details": "构造与细节"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=32)
def _json_snapshot(path: str, stamp: int, size: int, expected: str | None):
    raw = Path(path).read_bytes()
    if expected is not None and _sha(raw) != expected:
        raise ValueError("已保存结果的来源 SHA 不匹配")
    return json.loads(raw)


class SavedMoodboardResults:
    """封闭运行目录与真实成员身份；读取不会创建模型任务或升级旧审阅状态。"""

    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).resolve()

    def _data_path(self, path):
        path = Path(path)
        resolved = (path if path.is_absolute() else self.root / path).resolve()
        if not resolved.is_relative_to(self.root / "data"):
            raise ValueError("已保存结果的来源超出项目数据目录")
        if not resolved.is_file():
            raise FileNotFoundError("已保存结果的来源文件不存在")
        return resolved

    def _json(self, path, expected=None):
        path = self._data_path(path)
        stat = path.stat()
        return _json_snapshot(str(path), stat.st_mtime_ns, stat.st_size, expected)

    def _reference(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("sha256"), str):
            raise ValueError("已保存结果缺少可核验的文件引用")
        return self._json(value["path"], value["sha256"])

    def _context(self, result_id):
        if result_id not in RUNS:
            raise FileNotFoundError("已保存的 Skill 情绪板结果不存在")
        spec = RUNS[result_id]
        folder = self.root / spec["folder"]
        manifest = self._json(folder / spec["manifest"])
        boards_path = self._data_path(folder / spec["boards"])
        binding = (manifest.get("inputs", {}).get("boards.json") if spec["kind"] == "bounded"
                   else manifest.get("boards_ref"))
        if not binding or self._data_path(binding["path"]) != boards_path:
            raise ValueError("交付清单未绑定本次登记的图板快照")
        boards = self._json(boards_path, binding["sha256"])
        observation_ref = boards.get("input_refs", {}).get("observations")
        observations = self._reference(observation_ref)
        units = {unit["unit_id"]: unit for unit in observations["units"]}
        if len(units) != len(observations["units"]):
            raise ValueError("已保存设计卡身份重复")
        review = (self._reference(manifest["assessment_ref"]) if spec["kind"] == "bounded"
                  else self._reference(manifest["reference_review_ref"]))
        assessed = {row["board_id"]: row for row in review.get("boards", review.get("reviews", []))}
        members, receipts = {}, []
        for board in boards["boards"]:
            provenance = board["provenance"]
            self._reference(provenance["answer_ref"])
            receipt = self._json(Path(provenance["path"]) / "receipt.json")
            if (receipt.get("status") != "completed" or provenance.get("status") not in {"completed", "cached"}
                    or receipt.get("answer_ref") != provenance["answer_ref"]):
                raise ValueError("已保存成员缺少真实成功模型回执")
            receipts.append(receipt)
            for member in board["members"]:
                unit = units.get(member["unit_id"])
                bbox = member.get("display_bbox", member.get("roi"))
                if (unit is None or unit["image_id"] != member["image_id"]
                        or unit["image_sha256"] != member["sha256"] or unit["display_bbox"] != bbox):
                    raise ValueError("已保存成员与冻结对象／取景不一致")
                self._bbox(bbox)
                self._data_path(unit["local_path"])
                token = _sha((board["board_id"] + "\n" + member["unit_id"]).encode())
                if token in members:
                    raise ValueError("已保存成员的展示身份重复")
                members[token] = {"member": member, "unit": unit, "board_id": board["board_id"]}
        return {"spec": spec, "folder": folder, "manifest": manifest, "boards": boards,
                "boards_path": boards_path, "assessed": assessed, "members": members, "receipts": receipts}

    def _feedback(self):
        """仅使用已登记的人工导出文件，绑定原集合，不按整图 SHA 迁移反馈。"""
        path = self.root / "ref/问题反馈/情绪版选图.json"
        if not path.is_file():
            return {}, []
        manifest_path = self.root / "frontend/public/visual-workflow/moodboard-image-review-20261012/deployment-manifest.json"
        paths = [path.resolve(), manifest_path.resolve()]
        expected_paths = [path, manifest_path]
        if any(actual != expected for actual, expected in zip(paths, expected_paths)):
            raise ValueError("人工反馈登记文件不能通过软链指向其他来源")
        records = _json_snapshot(str(path), path.stat().st_mtime_ns, path.stat().st_size, None)
        manifest = _json_snapshot(str(manifest_path), manifest_path.stat().st_mtime_ns, manifest_path.stat().st_size, None)
        if (records.get("schema_version") != "prism.image_rejection_feedback.v1"
                or records.get("collection_identity") != manifest.get("identity")):
            raise ValueError("人工反馈与原图板集合的身份不匹配")
        indexed = {}
        for row in records["records"]:
            key = (row["board_id"], row.get("unit_id"), row["image_sha256"], tuple(row["roi"]))
            if key in indexed or row["status"] not in {"rejected", "unmarked"}:
                raise ValueError("人工反馈存在重复身份或未知状态")
            indexed[key] = row
        refs = [{"path": str(item), "sha256": _sha(item.read_bytes())} for item in paths]
        return indexed, refs

    @staticmethod
    def _feedback_member(index, spec, board, ordinal, member):
        alias = f"bounded-{ordinal}" if spec["kind"] == "bounded" else "reference-" + board["board_id"]
        key = (alias, member["unit_id"], member["sha256"], tuple(member.get("display_bbox", member.get("roi"))))
        row = index.get(key)
        if index and row is None:
            raise ValueError("人工反馈未精确对应当前图板、对象和取景")
        return {"status": row["status"], "reason": row.get("reason", ""), "updated_at": row.get("updated_at")} if row else {
            "status": "unmarked", "reason": "", "updated_at": None}

    @staticmethod
    def _bbox(bbox):
        if (not isinstance(bbox, list) or len(bbox) != 4
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in bbox)):
            raise ValueError("已保存图板的取景格式无效")
        x, y, width, height = bbox
        if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1.000001 or y + height > 1.000001:
            raise ValueError("已保存图板的取景超出原图")

    @staticmethod
    def _created(context):
        return context["manifest"].get("created_at") or context["boards"].get("summary", {}).get("finished_at", "")

    def list(self):
        results = []
        for result_id in RUNS:
            context = self._context(result_id)
            spec, boards = context["spec"], context["boards"]["boards"]
            feedback, _ = self._feedback()
            rejected = sum(self._feedback_member(feedback, spec, board, ordinal, member)["status"] == "rejected"
                           for ordinal, board in enumerate(boards, 1) for member in board["members"])
            results.append({"id": result_id, "title": spec["title"], "created_at": self._created(context),
                            "board_count": len(boards), "image_count": sum(len(board["members"]) for board in boards),
                            "status_label": "有人工排除 · 待修改" if rejected else spec["status_label"],
                            "notes": spec["notes"], "rejected_images": rejected})
        return {"default_result_id": DEFAULT_RESULT_ID, "results": results}

    @staticmethod
    def _quality(spec, board, review):
        judgment = review.get("result", review.get("judgment"))
        if judgment == "supported_in_current_context":
            return "当前板面对照支持 · 未经人工批准", "success"
        if judgment == "aligned":
            return "AI 参考对照通过 · 未经人工批准", "success"
        if judgment == "needs_revision":
            return "需要修改", "warning"
        return "模型候选 · 未独立审阅", "default"

    @staticmethod
    def _constraints(board, kind):
        rules = board.get("constraints", {})
        count = len(board["members"])
        policy = rules.get("quantity_policy", {})
        minimum, maximum = policy.get("minimum", 5 if kind == "bounded" else 6), policy.get("maximum", 10)
        rows = [{"label": "图片数量", "value": f"{count} 张（当时合同 {minimum}–{maximum} 张）"}]
        category = rules.get("category_limit")
        if category:
            counts = category.get("counts", {})
            largest = max(counts.values(), default=0)
            rows.append({"label": "同品类占比", "value": f"最大 {largest}/{count}；{len(category.get('unknown_card_ids', []))} 项未核",
                         "status": category.get("status", "unknown")})
        else:
            rows.append({"label": "同品类占比", "value": "旧快照未记录本项核验"})
        for field, label in (("article_independence", "文章来源"), ("project_independence", "项目来源")):
            rows.append({"label": label, "value": "已知来源 ID 已排重" if rules.get(field) == "known_ids_checked" else "存在未登记来源"})
        runway = rules.get("runway", {})
        rows.append({"label": "秀场图片", "value": f"已知 {len(runway.get('yes', []))} 张，未核 {len(runway.get('unknown', []))} 张；当时上限 {runway.get('maximum', '未记录')} 张"})
        return rows

    def get(self, result_id):
        context = self._context(result_id)
        spec, document = context["spec"], context["boards"]
        feedback, feedback_refs = self._feedback()
        boards = []
        for ordinal, board in enumerate(document["boards"], 1):
            review = context["assessed"].get(board["board_id"], {})
            status_label, tone = self._quality(spec, board, review)
            notes = ([review["observation"]] if review.get("observation") else []) + review.get("remaining_issues", [])
            if review.get("common_relation"):
                notes.append(review["common_relation"])
            evidence = {row["card_id"]: row for row in board.get("member_evidence", [])}
            members, links = [], []
            for token, binding in context["members"].items():
                if binding["board_id"] != board["board_id"]:
                    continue
                member, unit = binding["member"], binding["unit"]
                detail = evidence.get(member["unit_id"], {})
                sources = unit.get("sources", [])
                for source in sources:
                    url = source.get("article_url", "")
                    if url.startswith(("https://", "http://")) and not any(link["url"] == url for link in links):
                        links.append({"label": source.get("title") or "来源文章", "url": url})
                url = f"/api/v1/moodboards/clustering/saved-results/{result_id}/images/{token}"
                members.append({"id": token, "image_name": unit.get("subject", {}).get("identity") or member["image_id"],
                    "preview_url": url, "original_url": url + "?original=true", "category": unit.get("category", "品类未核"),
                    "reason": detail.get("support") or member.get("reason", ""),
                    "strongest_difference": detail.get("strongest_difference"),
                    "why_coordinated": detail.get("why_coordinated", detail.get("decision_basis")),
                    "source_label": (sources[0].get("title") or " · ".join(
                        f"{label}{sources[0][key]}" for key, label in (("article_id", "文章 "), ("project_id", "项目 "))
                        if sources[0].get(key)) or "来源未登记") if sources else "来源未登记",
                    "image_id": member["image_id"], "display_bbox": member.get("display_bbox", member.get("roi")),
                    "feedback": self._feedback_member(feedback, spec, board, ordinal, member)})
            rejected = sum(member["feedback"]["status"] == "rejected" for member in members)
            if rejected:
                notes.insert(0, f"原有审阅：{status_label}")
                status_label, tone = "有人工排除 · 待修改", "warning"
                notes.append(f"设计师 2026-10-13 已排除 {rejected} 图；其余未标记不代表通过。")
            relations = [{"label": label, "value": board.get("common_relations", {}).get(key, "")}
                         for key, label in RELATIONS.items() if board.get("common_relations", {}).get(key)]
            boards.append({"id": board["board_id"], "title": board["title"],
                "description": board.get("dominant_relation") or board.get("profile", {}).get("summary") or "",
                "status_label": status_label, "status_tone": tone, "review_notes": notes,
                "relations": relations, "constraints": self._constraints(board, spec["kind"]), "members": members,
                "feedback_summary": {"rejected": rejected, "unmarked": len(members) - rejected},
                "hardest_pair": board.get("hardest_pair"), "design_quality_choice": board.get("design_quality_choice"), "source_links": links})
        summary = document.get("summary", {})
        receipts = context["receipts"]
        models = sorted({row["requested_model"] for row in receipts if row.get("requested_model")})
        prompt_versions = sorted({row["prompt_version"] for row in receipts if row.get("prompt_version")})
        return {"id": result_id, "title": spec["title"], "created_at": self._created(context),
                "model_id": "、".join(models) or "原回执未报告", "prompt_version": "、".join(prompt_versions) or None,
                "status_label": "有人工排除 · 待修改" if any(board["feedback_summary"]["rejected"] for board in boards) else spec["status_label"],
                "notes": spec["notes"], "boards": boards, "trace": {"feedback_refs": feedback_refs},
                "summary": [{"label": "候选板", "value": str(len(boards))},
                            {"label": "板内图片位置", "value": str(sum(len(board["members"]) for board in boards))},
                            {"label": "输入设计卡", "value": str(summary.get("cards", "未记录"))},
                            {"label": "实际看图原图", "value": str(summary.get("actual_visual_originals", "按原阶段记录"))},
                            {"label": "设计师批准", "value": "未确认"}],
                "downloads": [{"label": "下载原始图板结果 JSON", "url": f"/api/v1/moodboards/clustering/saved-results/{result_id}/download"}]}

    def image(self, result_id, token, original=False):
        context = self._context(result_id)
        binding = context["members"].get(token)
        if binding is None:
            raise FileNotFoundError("已保存情绪板的图片不存在")
        unit, member = binding["unit"], binding["member"]
        path = self._data_path(unit["local_path"])
        raw = path.read_bytes()
        if _sha(raw) != member["sha256"]:
            raise ValueError("已保存原图的字节与冻结记录不一致")
        if original:
            return path
        bbox = member.get("display_bbox", member.get("roi"))
        self._bbox(bbox)
        x, y, width, height = bbox
        crop_path = self.root / "data/result/moodboard_saved_display" / result_id / f"{token}.png"
        with Image.open(io.BytesIO(raw)) as source:
            bounds = (max(0, math.floor(x * source.width)), max(0, math.floor(y * source.height)),
                      min(source.width, math.ceil((x + width) * source.width)), min(source.height, math.ceil((y + height) * source.height)))
            cropped = source.crop(bounds)
            if crop_path.exists():
                with Image.open(crop_path) as cached:
                    if cached.size != cropped.size or cached.mode != cropped.mode or cached.tobytes() != cropped.tobytes():
                        raise ValueError("已缓存的取景像素与真实冻结视窗不一致")
            else:
                buffer = io.BytesIO()
                cropped.save(buffer, "PNG")
                _atomic_write(crop_path, buffer.getvalue())
        return crop_path

    def download(self, result_id):
        return self._context(result_id)["boards_path"]


saved_moodboard_results = SavedMoodboardResults()
