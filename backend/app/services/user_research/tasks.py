"""用研 PPT 任务生命周期：原页提取、待核对结果和显式确认。"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import uuid

from fastapi import UploadFile

from app.agents.user_research_intake import PROMPT_VERSION, extract_slide, frozen_prompt
from app.services.llm import get_model
from app.services.user_research.presentation import MAX_COMPRESSED_BYTES, prepare_presentation
from app.services.user_research.storage import ResearchStore, _atomic


def now() -> str:
    return datetime.now(UTC).isoformat()


class ResearchTasks:
    """单进程持久化工作队列；进程重启不自动重放已计费的模型调用。"""

    def __init__(self, store: ResearchStore):
        self.store = store
        self._worker = asyncio.Semaphore(1)
        self._uploads = asyncio.Lock()

    def recover(self) -> None:
        for task in self.store.list_tasks():
            if task['status'] in ('queued', 'extracting'):
                self.update(task, status='failed', stage='interrupted',
                            message='服务重启导致任务中断，请检查已有回执后重新上传。', error='任务中断，未自动重试模型。')

    def update(self, task: dict, **changes) -> dict:
        task.update(changes, updatedAt=now())
        self.store.save_task(task)
        return task

    async def create(self, file: UploadFile, name: str, model: str) -> dict:
        get_model(model)
        filename = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
        if not filename.lower().endswith('.pptx'):
            raise ValueError('请上传 .pptx 文件；旧版 .ppt 请先另存为 .pptx。')
        if not name.strip() or len(name.strip()) > 120 or len(filename) > 240:
            raise ValueError('请填写 1–120 字的用户名称，文件名不超过 240 字。')
        run_id = uuid.uuid4().hex
        run = self.store._run(run_id)
        run.mkdir(parents=True)
        target = run / 'input.pptx'
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open('wb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_COMPRESSED_BYTES:
                        raise ValueError('PPTX 超过 100 MB，请拆分后上传。')
                    digest.update(chunk)
                    stream.write(chunk)
            if not size:
                raise ValueError('上传文件为空。')
            # 同一份来源重复提交复用已有结果或任务，不覆盖五人历史资料。
            async with self._uploads:
                checksum = digest.hexdigest()
                for task in self.store.list_tasks():
                    if task.get('sourceSha256') == checksum and task['status'] != 'failed':
                        target.unlink()
                        run.rmdir()
                        return task
                stamp = now()
                task = dict(id=run_id, userId='import_' + run_id, name=name.strip(), filename=filename,
                            status='queued', stage='queued', message='等待提取', totalSlides=0, processedSlides=0,
                            model=model, sourceSha256=checksum, createdAt=stamp, updatedAt=stamp)
                for user in self.store.list_users():
                    if user.get('sourceSha256') == checksum:
                        task.update(userId=user['id'], status='completed', stage='reused', message='已复用这份 PPT 的已有提取结果。')
                        break
                self.store.save_task(task)
                return task
        except BaseException:
            target.unlink(missing_ok=True)
            if run.exists() and not any(run.iterdir()):
                run.rmdir()
            raise
        finally:
            await file.close()

    async def run(self, task_id: str) -> None:
        async with self._worker:
            task = self.store.get_task(task_id)
            if task['status'] != 'queued':
                return
            run = self.store._run(task_id)
            try:
                self.update(task, status='extracting', stage='preparing', message='正在读取文字、原图并渲染 PPT 原页。')
                inventory = await asyncio.to_thread(prepare_presentation, run / 'input.pptx', run / 'prepared')
                prompt = frozen_prompt()
                (run / 'prompt.txt').write_text(prompt, encoding='utf-8')
                self.update(task, totalSlides=inventory['slideCount'], stage='extracting', message='正在按 Skill 逐页核对问答和图片态度。')
                records, images, profile, asset_paths, warnings = [], [], {}, {}, []
                for slide in inventory['slides']:
                    output = await extract_slide(slide, model_id=task['model'], prompt=prompt, run=run)
                    page = slide['number']
                    pictures = {p['id']: p for p in slide['pictures']}
                    for fact in output.profile:
                        # 同字段多页不同填写值保留并列，不用最后一页覆盖前文。
                        previous = profile.get(fact.key)
                        if previous and previous != fact.value:
                            profile[fact.key] = list(dict.fromkeys((previous if isinstance(previous, list) else [previous]) + [fact.value]))
                        else:
                            profile[fact.key] = fact.value
                    for index, answer in enumerate(output.records, 1):
                        rid = f'p{page}-r{index}'
                        linked = []
                        for pic_index, choice in enumerate(answer.images, 1):
                            iid = f'{rid}-i{pic_index}'
                            linked.append(iid)
                            picture = pictures.get(choice.pictureId)
                            if picture:
                                asset_paths[iid] = Path(picture['localPath'])
                            images.append(dict(id=iid, code=choice.code, emotion=choice.emotion, url=None,
                                               sourceSlide=page, questionId=rid, description=choice.description,
                                               evidenceScope=choice.evidenceScope, evidenceKind=choice.evidenceKind,
                                               evidenceText=choice.evidenceText, sourceShapePath=picture['shapePath'] if picture else None,
                                               status='extracted' if picture else 'missing_source_image'))
                        records.append(dict(id=rid, section=answer.section, question=answer.question, answer=answer.answer,
                                            originalAnswer=answer.originalAnswer, sourceRole=answer.role,
                                            sourceShapePaths=answer.answerShapePaths, sourceSlide=page,
                                            sourceFile=task['filename'], imageIds=linked, sourceKind='ppt'))
                    warnings.extend(f'第 {page} 页：{warning}' for warning in output.warnings)
                    self.update(task, processedSlides=page, message=f'已核对 {page} / {inventory["slideCount"]} 页')
                if not records and not profile:
                    raise ValueError('未发现可确认的用户填写内容；未创建空用户结果。')
                detail = dict(id=task['userId'], name=task['name'], profile=profile,
                              sourceFile=task['filename'], sourceSha256=inventory['sourceSha256'],
                              records=records, images=images, warnings=list(dict.fromkeys(warnings)),
                              status='needs_review', createdAt=task['createdAt'], provenance=dict(
                                  taskId=task_id, sourceKind='ppt', sourceVerified=True,
                                  textKind='PPT 填写内容及中文翻译，并非逐字访谈',
                                  skills=['prism-research-intake', 'user-research-ppt-json-importer'],
                                  promptVersion=PROMPT_VERSION, promptSha256=hashlib.sha256(prompt.encode()).hexdigest(),
                                  model=task['model'], completedAt=now(), originalPagesReviewed=True,
                                  totalSlides=inventory['slideCount']))
                self.store.save_user(detail, asset_paths)
                self.update(task, status='needs_review', stage='review', message='提取完成，请核对问答与图片态度后确认。')
            except asyncio.CancelledError:
                self.update(task, status='failed', stage='interrupted', message='任务被中断，已保存已完成的原页回执。', error='执行中断')
                raise
            except Exception as exc:
                # SDK 错误可能含认证头或请求体，公开接口只返回可控领域错误。
                public = str(exc)[:350] if isinstance(exc, ValueError) else f'提取失败（{type(exc).__name__}），请检查服务配置和 PPT 后重试。'
                _atomic(run / 'failure.json', dict(type=type(exc).__name__, message=public, at=now()))
                self.update(task, status='failed', stage='failed', message=public, error=public)

    def confirm(self, task_id: str) -> dict:
        task = self.store.get_task(task_id)
        if task['status'] == 'completed':
            return task
        if task['status'] != 'needs_review':
            raise ValueError('只有已提取、待核对的结果可以确认。')
        detail = self.store.get_user(task['userId'])
        paths = {image['id']: self.store.asset_path(detail['id'], image['id'])
                 for image in detail['images'] if image.get('url')}
        detail['status'] = 'ready'
        detail['provenance']['confirmedAt'] = now()
        self.store.save_user(detail, paths)
        return self.update(task, status='completed', stage='completed', message='已确认提取结果。')
