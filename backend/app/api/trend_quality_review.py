"""趋势图片人工筛选接口；只读模型档案，选择由独立文件保存。"""

import json
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from app.api.high_trends import call
from app.schemas.trend_quality_review import TrendQualitySelection
from app.services.high_trends.skill import PROJECT_ROOT
from app.services.trend_quality_review import TrendQualityReview, COLLECTION_ID

router = APIRouter(prefix='/trend-quality/review', tags=['Trend quality manual review'])
service = TrendQualityReview(PROJECT_ROOT)


@router.get('')
def get(model_category: Literal['all', 'PASS', 'FAIL', 'REVIEW', 'ERROR'] = 'all',
        manual: Literal['all', 'unreviewed', 'PASS', 'FAIL'] = 'all', direction_id: str = '',
        q: str = Query(default='', max_length=200), page: int = Query(default=1, ge=1),
        page_size: int = Query(default=60, ge=1, le=120)):
    return call(lambda: service.page(model_category=model_category, manual=manual,
                                    direction_id=direction_id, q=q, page=page, page_size=page_size))


@router.patch('')
def update(request: TrendQualitySelection):
    return call(service.update, request.revision, request.image_ids, request.decision)


@router.get('/images/{image_id}')
def image(image_id: str, thumbnail: bool = False):
    path = call(service.image, image_id, thumbnail)
    return FileResponse(path, content_disposition_type='inline', headers={
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=31536000, immutable'})


@router.get('/download')
def download(selection: Literal['PASS', 'FAIL', 'all'] = 'PASS'):
    data = call(service.download, selection)
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="{COLLECTION_ID}_manual_{selection}.json"'})
