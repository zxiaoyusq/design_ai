"""新版原生情绪板的只读宿主预览；旧纯文本准备/发布入口已退役。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / 'backend'))
STOP_REASON = '旧纯文本4–8张宿主生成/发布已停用；请按同事v2完成原生设计转译、真实裁片和整板验收后预览。'


def prepare():
    """不再创建旧协议任务，不能把文字候选伪装成10项目视觉结果。"""
    raise RuntimeError(STOP_REASON)


def publish(run):
    """已有历史记录继续读取；新交付须走原生门，禁止绕过网页入口写完成。"""
    raise RuntimeError(STOP_REASON)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-run', help='旧参数仅用于给出迁移说明，不再写入任务')
    parser.add_argument('--preview-native-run', help='visual_workflow下含web-handoff.json的运行相对目录，仅离线核验/输出')
    args = parser.parse_args()
    if args.publish_run or not args.preview_native_run:
        parser.exit(2, STOP_REASON + '\n')
    from app.services.visual_workflow.web_adapter import preview_handoff
    print(json.dumps(preview_handoff(args.preview_native_run), ensure_ascii=False))


if __name__ == '__main__':
    main()
