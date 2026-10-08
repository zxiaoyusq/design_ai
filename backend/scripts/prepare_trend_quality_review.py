"""离线冻结两批趋势图片模型结果，创建不重置选择的人工图库；不调用模型。"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.trend_quality_review import TrendQualityReview


if __name__ == '__main__':
    service = TrendQualityReview(ROOT)
    print(json.dumps({'folder': str(service.folder), 'counts': service.prepare()}, ensure_ascii=False))
