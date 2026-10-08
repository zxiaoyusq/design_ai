"""v0.8 极简判标契约；旧版结构化回执继续由 curation 处理。"""

from pathlib import Path

VERSION = 'cmf-reference-curation-v0.8.0'
PROMPT_PATH = Path(__file__).resolve().parents[3] / 'references/prompts/curation-v0.8.0.txt'


def evaluate(raw, *, truncated=False):
    """只接受完整单词；截断、异常和未决不能降格成审美不通过。"""
    word = raw.strip() if isinstance(raw, str) else None
    if truncated or word not in {'PASS', 'FAIL', 'REVIEW'}:
        return {'valid': False, 'status': 'invalid_output', 'decision': None}
    if word == 'REVIEW':
        return {'valid': True, 'status': 'needs_review', 'decision': None}
    return {'valid': True, 'status': 'complete', 'decision': word}
