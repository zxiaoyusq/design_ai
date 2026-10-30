"""D03 极简单图判标：固定预处理、单次请求和可追溯回执。"""

import asyncio
import base64
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys
from time import monotonic

from langchain_core.messages import HumanMessage
from PIL import Image, ImageOps

from app.agents.bounded import AGENT_RUNTIME_VERSION, create_bounded_agent
from app.agents.dna_deep_agent import PROJECT_ROOT, _model_options
from app.services.dna.prism_r5 import _reply, _safe_exception
from app.services.llm import create_chat_model
from app.services.llm.telemetry import ModelCallTelemetry

SKILL = PROJECT_ROOT / '.agents/skills/prism-trend-quality'
sys.path.insert(0, str(SKILL / 'runtime'))
from prism_runtime.quality import compact

PREPROCESS_VERSION = 'long-edge-1600-jpeg92-v1'
DEADLINE_SECONDS = 60


def prepare_image(path: Path):
    """不裁切、不放大；小图保留原字节，透明图保留透明通道。"""
    original = path.read_bytes()
    with Image.open(BytesIO(original)) as source:
        source.load()
        original_size = source.size
        image = ImageOps.exif_transpose(source)
        oriented = image.size != original_size or source.getexif().get(274, 1) != 1
        resized = max(image.size) > 1600
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        mime = Image.MIME.get(source.format, 'image/jpeg')
        result = original
        # 高压缩率的小 JPEG/WebP 不重复有损编码；大 PNG 的传输体积单独压缩。
        if resized or oriented or len(original) > 512_000:
            buffer = BytesIO()
            alpha = image.mode in {'RGBA', 'LA'} or 'transparency' in image.info
            if alpha:
                image.convert('RGBA').save(buffer, format='PNG', optimize=True)
                candidate_mime = 'image/png'
            else:
                image.convert('RGB').save(buffer, format='JPEG', quality=92, subsampling=0)
                candidate_mime = 'image/jpeg'
            if resized or oriented or len(buffer.getvalue()) < len(original):
                result, mime = buffer.getvalue(), candidate_mime
        return result, {
            'version': PREPROCESS_VERSION, 'original_pixels': list(original_size),
            'input_pixels': list(image.size), 'original_bytes': len(original),
            'input_bytes': len(result), 'mime_type': mime,
            'image_sha256': sha256(original).hexdigest(),
            'input_image_sha256': sha256(result).hexdigest(),
        }


def model_options(model_id):
    """保持现有推理设置；上限包含隐藏推理，不能按可见单词数设置成个位数。"""
    options = _model_options(model_id)
    options.update(timeout=DEADLINE_SECONDS, max_tokens=4096)
    return options


async def classify(image_bytes, metadata, *, image_id, model_id):
    """不重试，不入库；调用方须先持久化 submitted 账本再调用。"""
    prompt = compact.PROMPT_PATH.read_bytes()
    options = model_options(model_id)
    if sha256(image_bytes).hexdigest() != metadata['input_image_sha256']:
        raise ValueError('发送图与预处理记录哈希不一致')
    record = {
        'image_id': image_id, 'version': compact.VERSION, 'model': model_id,
        'agent_runtime_version': AGENT_RUNTIME_VERSION,
        'parameters': options, 'prompt_sha256': sha256(prompt).hexdigest(),
        **metadata, 'preprocessing_version': metadata['version'],
        'started_at': datetime.now(UTC).isoformat(), 'production_admission': False,
    }
    record['version'] = compact.VERSION
    telemetry = ModelCallTelemetry()
    timer = monotonic()
    try:
        agent = create_bounded_agent(
            model=create_chat_model(model_id, **options), system_prompt=prompt.decode(),
            name='prism-trend-quality-compact',
        )
        # SDK timeout 是单次网络操作期限；外层期限覆盖整个流，超时不再自动补查。
        async with asyncio.timeout(DEADLINE_SECONDS):
            result = await agent.ainvoke({'messages': [HumanMessage(content=[{
                'type': 'image', 'base64': base64.b64encode(image_bytes).decode('ascii'),
                'mime_type': metadata['mime_type'],
            }])]}, config={'callbacks': [telemetry], 'recursion_limit': 40})
        raw = _reply(result)
        last = result['messages'][-1]
        response = getattr(last, 'response_metadata', {})
        record.update(raw_response=raw, http_status=200,
                      http_status_source='successful_sdk_completion',
                      message_usage_metadata=getattr(last, 'usage_metadata', None),
                      response_metadata={k: response[k] for k in
                                         ('model_name', 'model_provider', 'finish_reason', 'id', 'status', 'incomplete_details')
                                         if k in response})
        truncated = response.get('finish_reason') in {'length', 'max_tokens'} or response.get('status') == 'incomplete'
        record.update(compact.evaluate(raw, truncated=truncated))
    except Exception as exc:
        record.update(valid=False, decision=None, status='execution_error',
                      http_status=getattr(exc, 'status_code', None) or 0, error=_safe_exception(exc))
    record.update(finished_at=datetime.now(UTC).isoformat(),
                  duration_seconds=round(monotonic() - timer, 3), usage=telemetry.snapshot())
    return record
