from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.features.tasks import service
from app.features.tasks.schemas import (
    TaskCreate, TaskUpdate, TaskResponse, TaskDetailResponse,
    ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemResponse,
    TaskLinkCreate, TaskLinkResponse, SnoozeRequest,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
checklist_router = APIRouter(prefix="/api/checklist", tags=["checklist"])
links_router = APIRouter(prefix="/api/links", tags=["links"])


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


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_task(db, data)


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


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, data: TaskUpdate, db: AsyncSession = Depends(get_db)):
    task = await service.update_task(db, task_id, data)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_task(db, task_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")


@router.post("/{task_id}/review", response_model=TaskResponse)
async def review_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await service.review_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@router.post("/{task_id}/done", response_model=TaskResponse)
async def done_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await service.done_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


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
