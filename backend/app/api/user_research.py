"""用研 PPT 上传、结果查看和确认接口，不修改原始五用户资料。"""
from contextlib import asynccontextmanager

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.services.user_research.storage import ResearchStore
from app.services.user_research.tasks import ResearchTasks

store = ResearchStore()
manager = ResearchTasks(store)


@asynccontextmanager
async def lifespan(_app):
    await run_in_threadpool(manager.recover)
    yield


router = APIRouter(prefix='/user-research', tags=['user-research'], lifespan=lifespan)


def read(operation, *args):
    """将本地存储边界转为稳定的 HTTP 错误，不公开服务器路径。"""
    try:
        return operation(*args)
    except FileNotFoundError:
        raise HTTPException(404, '未找到对应的用研记录或图片。') from None
    except ValueError:
        raise HTTPException(400, '请求标识或状态不正确。') from None


@router.get('/users')
def users():
    return {'users': store.list_users()}


@router.get('/users/{user_id}')
def user(user_id: str):
    return read(store.get_user, user_id)


@router.get('/tasks')
def tasks():
    return {'tasks': sorted(store.list_tasks(), key=lambda x: x['createdAt'], reverse=True)[:50]}


@router.get('/tasks/{task_id}')
def task(task_id: str):
    return read(store.get_task, task_id)


@router.post('/imports', status_code=202)
async def imports(background: BackgroundTasks, file: UploadFile = File(...), name: str = Form(...), model: str = Form(...)):
    try:
        value = await manager.create(file, name, model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if value['status'] == 'queued':
        background.add_task(manager.run, value['id'])
    return value


@router.post('/tasks/{task_id}/confirm')
def confirm(task_id: str):
    return read(manager.confirm, task_id)


@router.get('/assets/{user_id}/{image_id}')
def asset(user_id: str, image_id: str):
    path = read(store.asset_path, user_id, image_id)
    return FileResponse(path, headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=3600'})
