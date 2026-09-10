"""只读汇总真实调用日志；命令行显式生成 performance_report.json，不调用模型或网络。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys

sys.dont_write_bytecode = True

_IN_PROGRESS = {"pending", "running", "in_flight", "started", "incomplete"}


def _read_object(path):
    if not path.exists():
        return None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("日志不是 JSON 对象")
        return value, None
    except (OSError, ValueError) as exc:
        return None, {"file": str(path), "reason": str(exc)}


def _moment(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # 不猜测本地时区；日志必须给出明确时区，才能计算不同调用的墙钟跨度。
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _nonnegative(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _token_count(value):
    return value if type(value) is int and value >= 0 else None


def _percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    left = math.floor(index)
    right = math.ceil(index)
    return ordered[left] + (ordered[right] - ordered[left]) * (index - left)


def _stage(run, job_id, result, request):
    for item in (result, request):
        if isinstance(item.get("stage"), str) and item["stage"]:
            return item["stage"]
    job, _ = _read_object(run / "jobs" / f"{job_id}.json")
    stage = job.get("stage") if job else None
    return stage if isinstance(stage, str) and stage else "unknown"


def _attempt(run, folder, legacy):
    result_path = folder / ("result.json" if legacy else "outcome.json")
    result, result_error = _read_object(result_path)
    request, request_error = _read_object(folder / "request.json")
    request = request or {}
    result = result or {}
    kind = result.get("status" if legacy else "kind")
    stage = _stage(run, folder.parent.name, result, request)
    ended = bool(result) and isinstance(kind, str) and bool(kind) and kind not in _IN_PROGRESS
    start = _moment(result.get("started_at") or request.get("started_at"))
    finish = _moment(result.get("finished_at"))
    ordered_timestamps = start is not None and finish is not None and finish >= start
    duration = _nonnegative(result.get("elapsed_seconds"))
    if duration is None and ordered_timestamps:
        duration = (finish - start).total_seconds()
    usage = result.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    profile = request.get("model_profile")
    profile = profile if isinstance(profile, dict) else {}
    model = result.get("model") or result.get("requested_model") or profile.get("model")
    return {
        "stage": stage, "ended": ended, "valid": kind == "valid", "kind": kind,
        "seconds": duration, "start": start if ordered_timestamps else None,
        "finish": finish if ordered_timestamps else None,
        "model": model if isinstance(model, str) else None,
        "input_tokens": _token_count(result.get("input_tokens", usage.get("input_tokens"))),
        "output_tokens": _token_count(result.get("output_tokens", usage.get("output_tokens"))),
        "file": str(result_path), "errors": [error for error in (result_error, request_error) if error],
    }


def _summary(attempts):
    ended = [item for item in attempts if item["ended"]]
    durations = [item["seconds"] for item in ended if item["seconds"] is not None]
    failed = [item for item in ended if not item["valid"]]
    failure_durations = [item["seconds"] for item in failed if item["seconds"] is not None]
    paired = [item for item in ended if item["start"] is not None]
    first = min((item["start"] for item in paired), default=None)
    last = max((item["finish"] for item in paired), default=None)
    result = {
        "attempt_count": len(ended), "valid_count": sum(item["valid"] for item in ended),
        "failure_count": len(failed), "incomplete_count": len(attempts) - len(ended),
        "duration_sample_count": len(durations), "missing_duration_count": len(ended) - len(durations),
        "missing_timestamp_count": len(ended) - len(paired),
        "p50_seconds": _percentile(durations, 0.5) if durations else None,
        "p95_seconds": _percentile(durations, 0.95) if durations else None,
        "max_seconds": max(durations) if durations else None,
        "mean_seconds": statistics.fmean(durations) if durations else None,
        # 部分缺失时这些总量只累加已知部分；全缺失不能用 0 假装没有耗时。
        "sum_call_seconds": sum(durations) if durations or not ended else None,
        "failed_call_seconds": sum(failure_durations) if failure_durations or not failed else None,
        "failure_kinds": dict(sorted(Counter(item["kind"] for item in failed).items())),
        "input_tokens_known": sum(item["input_tokens"] for item in ended if item["input_tokens"] is not None),
        "output_tokens_known": sum(item["output_tokens"] for item in ended if item["output_tokens"] is not None),
        "input_usage_count": sum(item["input_tokens"] is not None for item in ended),
        "output_usage_count": sum(item["output_tokens"] is not None for item in ended),
        "missing_usage_count": sum(item["input_tokens"] is None or item["output_tokens"] is None for item in ended),
        "models": sorted({item["model"] for item in ended if item["model"]}),
        "first_started_at": first.isoformat() if first else None,
        "last_finished_at": last.isoformat() if last else None,
        "observed_wall_span_seconds": (last - first).total_seconds() if first and last else None,
    }
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in result.items()}


def summarize_performance(run):
    """读取旧 host 和新 runner 的调用尝试，不创建文件、不把缓存接收当作模型调用。"""
    run = Path(run).resolve()
    if not run.is_dir():
        raise ValueError(f"运行目录不存在：{run}")
    attempts = []
    for relative, pattern, legacy in (("host/attempts", "*/attempt-*", True),
                                      ("runner/attempts", "*/*", False)):
        for folder in sorted((run / relative).glob(pattern)):
            if folder.is_dir():
                attempts.append(_attempt(run, folder, legacy))
    grouped = {}
    for item in attempts:
        grouped.setdefault(item["stage"], []).append(item)
    stages = {stage: _summary(items) for stage, items in sorted(grouped.items())}
    by_median = sorted((stage for stage in stages if stages[stage]["p50_seconds"] is not None),
                       key=lambda stage: (-stages[stage]["p50_seconds"], stage))
    by_total = sorted((stage for stage in stages if stages[stage]["duration_sample_count"]),
                      key=lambda stage: (-stages[stage]["sum_call_seconds"], stage))
    totals = _summary(attempts)
    return {
        "schema_version": "design_trend_performance_v1", "run_dir": str(run),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": totals, "stages": stages,
        "observed_wall_span_seconds": totals["observed_wall_span_seconds"],
        "slowest_single_call_stage": by_median[0] if by_median else None,
        "largest_total_call_stage": by_total[0] if by_total else None,
        "stage_rankings": {"by_p50_seconds": by_median, "by_sum_call_seconds": by_total},
        "diagnostics": [error for item in attempts for error in item["errors"]],
        "notes": [
            "仅已结束的调用参与成功/失败、耗时和 token 统计；重试按实际调用逐次计入，缓存接收和未调用任务不计入。",
            "p50/p95 使用排序样本的线性插值，只使用已知时长；slowest_single_call_stage 按 p50 排序。",
            "sum_call_seconds 累加实际调用耗时；并发时不等于用户等待时间，缺失时长时只是已知部分。",
            "observed_wall_span_seconds 是已结束且开始/结束时间完整的调用从首开始至末结束的跨度，包含暂停和等待，不能解释为纯模型耗时。",
            "missing_duration_count、missing_timestamp_count 和 incomplete_count 独立报告；缺失值不填 0。tokens_known 仅代表已知用量。",
            "失败类别只使用日志的结构化 status/kind，不根据错误正文中的 overloaded 等关键词推断。",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="运行目录；显式写入其 performance_report.json")
    args = parser.parse_args(argv)
    try:
        report = summarize_performance(args.run)
        # CLI 的唯一写入点；供宿主直接调用的 summarize_performance 始终只读。
        from core import write
        destination = Path(args.run).resolve() / "performance_report.json"
        write(destination, report)
        print(json.dumps({"report_file": str(destination), **report}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"统计失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
