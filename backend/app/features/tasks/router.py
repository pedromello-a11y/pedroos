from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.features.tasks import service
from app.features.tasks.schemas import (
    TaskCreate, TaskUpdate, TaskResponse, TaskDetailResponse, TaskWithSideEffects,
    ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemResponse,
    TaskLinkCreate, TaskLinkResponse, SnoozeRequest, TaskImageResponse,
    UndoCapDemotion,
)


def _wrap_demoted(task) -> TaskWithSideEffects:
    """Bundle a task com possíveis tasks rebaixadas pelo WIP cap."""
    payload = TaskWithSideEffects.model_validate(task)
    payload.demoted = [TaskResponse.model_validate(t) for t in getattr(task, "_demoted", []) or []]
    return payload

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
checklist_router = APIRouter(prefix="/api/checklist", tags=["checklist"])
links_router = APIRouter(prefix="/api/links", tags=["links"])
images_router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("", response_model=List[TaskResponse])
async def list_tasks(
    reviewed: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    project: Optional[str] = Query(None),
    deadline: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_tasks(
        db, reviewed=reviewed, status=status,
        project=project, deadline=deadline, parent_id=parent_id,
    )


@router.post("", response_model=TaskWithSideEffects, status_code=201)
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db)):
    task = await service.create_task(db, data)
    return _wrap_demoted(task)


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task, checklist, links, subtasks = await service.get_task_detail(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    result = TaskDetailResponse.model_validate(task)
    result.checklist = [ChecklistItemResponse.model_validate(c) for c in checklist]
    result.links = [TaskLinkResponse.model_validate(lnk) for lnk in links]
    result.subtasks = [TaskResponse.model_validate(s) for s in subtasks]
    return result


@router.patch("/{task_id}", response_model=TaskWithSideEffects)
async def update_task(task_id: str, data: TaskUpdate, db: AsyncSession = Depends(get_db)):
    task = await service.update_task(db, task_id, data)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return _wrap_demoted(task)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_task(db, task_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")


@router.post("/{task_id}/review", response_model=TaskWithSideEffects)
async def review_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await service.review_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return _wrap_demoted(task)


@router.post("/{task_id}/set-now", response_model=TaskWithSideEffects)
async def set_now(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await service.set_now_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return _wrap_demoted(task)


@router.post("/{task_id}/done", response_model=TaskResponse)
async def done_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await service.done_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@router.post("/undo-cap-demotion")
async def undo_cap_demotion(data: UndoCapDemotion, db: AsyncSession = Depends(get_db)):
    res = await service.undo_cap_demotion(db, data.trigger_id, data.restored_ids)
    return {
        "trigger": TaskResponse.model_validate(res["trigger"]) if res["trigger"] else None,
        "restored": [TaskResponse.model_validate(t) for t in res["restored"]],
    }


@router.post("/{task_id}/snooze", response_model=TaskResponse)
async def snooze_task(task_id: str, data: SnoozeRequest, db: AsyncSession = Depends(get_db)):
    task = await service.snooze_task(db, task_id, data.days)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@router.post("/{task_id}/checklist", response_model=ChecklistItemResponse, status_code=201)
async def add_checklist_item(task_id: str, data: ChecklistItemCreate, db: AsyncSession = Depends(get_db)):
    item = await service.add_checklist_item(db, task_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return item


@router.post("/{task_id}/links", response_model=TaskLinkResponse, status_code=201)
async def add_link(task_id: str, data: TaskLinkCreate, db: AsyncSession = Depends(get_db)):
    link = await service.add_link(db, task_id, data)
    if not link:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return link


# --- Checklist CRUD (prefix /api/checklist) ---

@checklist_router.patch("/{item_id}", response_model=ChecklistItemResponse)
async def update_checklist_item(item_id: str, data: ChecklistItemUpdate, db: AsyncSession = Depends(get_db)):
    item = await service.update_checklist_item(db, item_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    return item


@checklist_router.delete("/{item_id}", status_code=204)
async def delete_checklist_item(item_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_checklist_item(db, item_id):
        raise HTTPException(status_code=404, detail="Item não encontrado")


# --- Links CRUD (prefix /api/links) ---

@links_router.delete("/{link_id}", status_code=204)
async def delete_link(link_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_link(db, link_id):
        raise HTTPException(status_code=404, detail="Link não encontrado")


# --- Images (prefix /api/tasks/{id}/images + /api/images) ---

@router.post("/{task_id}/images", response_model=TaskImageResponse, status_code=201)
async def upload_image(task_id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    img = await service.upload_image(db, task_id, file)
    if not img:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return img


@router.get("/{task_id}/images", response_model=List[TaskImageResponse])
async def list_images(task_id: str, db: AsyncSession = Depends(get_db)):
    return await service.list_images(db, task_id)


@images_router.delete("/{image_id}", status_code=204)
async def delete_image(image_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_image(db, image_id):
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
