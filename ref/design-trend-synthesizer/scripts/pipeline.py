#!/usr/bin/env python3
"""跨 Agent 通用入口：本脚本不连接模型或网络，模型调用由宿主执行。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# 在其他 Agent 复制运行时保持包目录整洁。
sys.dont_write_bytecode = True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # 新任务默认3.0；历史manifest仍路由旧实现，不改冻结任务与续跑契约。
    legacy = bool(argv and argv[0] == 'legacy')
    if legacy:
        argv = argv[1:]
    else:
        probe = argparse.ArgumentParser(add_help=False)
        probe.add_argument('--run')
        known, _ = probe.parse_known_args(argv)
        lean_run = False
        if known.run and (Path(known.run) / 'manifest.json').exists():
            lean_run = json.loads((Path(known.run) / 'manifest.json').read_text()).get('workflow') == 'lean'
        if not argv or argv[0] in {'prepare', 'run', '--help', '-h'} or lean_run:
            from lean import main as lean_main
            return lean_main(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="筛选日期、检查输入并生成首批文本任务")
    prepare.add_argument("--trends", default="data/trend_data/trends.json")
    prepare.add_argument("--users", default="data/userreseach_data/users.json")
    prepare.add_argument("--output", help="可选的运行目录；默认在项目 data/result/high_trend 下自动创建独立子目录")
    prepare.add_argument("--project-root", default=".", help="项目根目录，默认当前目录；用于默认输出位置与图片相对路径")
    prepare.add_argument("--start-date", help="包含当天，YYYY-MM-DD")
    prepare.add_argument("--end-date", help="包含当天，YYYY-MM-DD")
    prepare.add_argument("--undated", choices=("exclude", "include"), default="exclude")
    prepare.add_argument("--as-of", help="近期判断的固定基准日，默认运行当天")
    prepare.add_argument("--batch-records", type=int, default=32, help="单批最多来源记录数；同一用户内按字符和输出预算动态合批")
    prepare.add_argument("--batch-chars", type=int, default=16000, help="提取的完整 system+user 字符上限；其他阶段约束 payload 及完整源上下文，不等于 token 上限")
    prepare.add_argument("--extraction-observations", type=int, default=64, help="每批最多提取观察数，1–128；长文本据此预留容量")
    prepare.add_argument("--max-trends", type=int, default=8)
    prepare.add_argument("--include-vl-text", action="store_true", help="纳入已有视觉分析文本，仍不读图片")
    prepare.add_argument("--dry-run", action="store_true", help="只检查范围，不创建文件或任务")
    prepare.add_argument("--model", help="宿主将调用的模型标识；声明后可复用参数一致的用户提取缓存")
    prepare.add_argument("--model-parameters", default="{}", help="影响模型输出的参数 JSON 对象，不含密钥和连接地址")
    prepare.add_argument("--cache-dir", help="可选缓存目录；默认位于项目 data/result/high_trend/_cache")
    prepare.add_argument("--no-cache", action="store_true", help="禁止读取和写入用户提取缓存")
    for name in ("status", "next"):
        sub = commands.add_parser(name, help="检查状态" if name == "status" else "当前阶段完成后生成下一阶段任务")
        sub.add_argument("--run", required=True)
        sub.add_argument("--limit", type=int, default=5)
    accept = commands.add_parser("accept", help="校验并接收一个模型回复；失败时不推进")
    accept.add_argument("--run", required=True)
    accept.add_argument("--job", required=True)
    accept.add_argument("--response", required=True)
    accept.add_argument("--model", required=True)
    accept.add_argument("--input-tokens", type=int)
    accept.add_argument("--output-tokens", type=int)
    accept.add_argument("--execution", help="宿主执行元信息 JSON 文件，含 model_profile、有效消息哈希和尝试路径")
    split = commands.add_parser("split", help="拆分尚未接收的提取/主题/候选/反证任务")
    split.add_argument("--run", required=True)
    split.add_argument("--job", required=True)
    performance = commands.add_parser("performance", help="按阶段统计调用耗时、重试占用与用量，兼容旧运行日志")
    performance.add_argument("--run", required=True)
    contract = commands.add_parser("contract", help="查看单阶段输出契约和示例结构")
    contract.add_argument("--stage", required=True, choices=("extract", "theme", "propose", "screen", "merge", "audit", "draft", "review"))
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            from prepare import prepare as execute
            result = execute(args)
        elif args.command in {"status", "next"}:
            from workflow import advance, status
            if args.limit < 1:
                raise ValueError("limit 必须大于 0")
            result = (advance if args.command == "next" else status)(args.run, args.limit)
        elif args.command == "accept":
            from workflow import receive
            from core import read
            result = receive(args.run, args.job, args.response, args.model, args.input_tokens, args.output_tokens,
                             execution=read(args.execution) if args.execution else None)
        elif args.command == "split":
            from workflow import split_job
            result = split_job(args.run, args.job)
        elif args.command == "performance":
            from performance import summarize_performance
            from core import write
            result = summarize_performance(args.run)
            write(Path(args.run).resolve() / "performance_report.json", result)
        else:
            from contracts import instruction, response_template
            result = {"instruction": instruction(args.stage), "response_template": response_template(args.stage)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
