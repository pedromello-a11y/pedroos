import os
from typing import Optional
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.features.tasks.models import Task, Checklist, TaskLink, TaskImage
from app.features.tasks.schemas import (
    TaskCreate, TaskUpdate, SnoozeRequest,
    ChecklistItemCreate, ChecklistItemUpdate, TaskLinkCreate,
)
from app.shared.ids import make_id, make_short_id
from app.shared.dates import now_brt, today_brt


async def create_task(db: AsyncSession, data: TaskCreate) -> Task:
    task_id = make_id()
    short = make_short_id(task_id)
    while True:
        exists = await db.execute(select(Task).where(Task.short_id == short))
        if not exists.scalar_one_or_none():
            break
        task_id = make_id()
        short = make_short_id(task_id)

    now = now_brt().isoformat()
    task = Task(
        id=task_id,
        short_id=short,
        title=data.title,
        raw_input=data.raw_input,
        description=data.description,
        project_slug=data.project_slug,
        deadline=data.deadline,
        priority=data.priority,
        status=data.status,
        reviewed=data.reviewed,
        source=data.source,
        parent_id=data.parent_id,
        jira_key=data.jira_key,
        created_at=now,
        updated_at=now,
        reviewed_at=now if data.reviewed == 1 else None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: str) -> Optional[Task]:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        result = await db.execute(select(Task).where(Task.short_id == task_id))
        task = result.scalar_one_or_none()
    return task


async def get_task_detail(db: AsyncSession, task_id: str):
    task = await get_task(db, task_id)
    if not task:
        return None, [], [], []

    checklist_result = await db.execute(
        select(Checklist).where(Checklist.task_id == task.id).order_by(Checklist.position)
    )
    links_result = await db.execute(
        select(TaskLink).where(TaskLink.task_id == task.id)
    )
    subtasks_result = await db.execute(
        select(Task).where(Task.parent_id == task.id).order_by(Task.created_at)
    )

    return (
        task,
        list(checklist_result.scalars().all()),
        list(links_result.scalars().all()),
        list(subtasks_result.scalars().all()),
    )


async def list_tasks(
    db: AsyncSession,
    reviewed: Optional[int] = None,
    status: Optional[str] = None,
    project: Optional[str] = None,
    deadline: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> list[Task]:
    q = select(Task)
    conditions = []

    if reviewed is not None:
        conditions.append(Task.reviewed == reviewed)
    if status:
        conditions.append(Task.status == status)
    if project:
        conditions.append(Task.project_slug == project)
    if parent_id:
        conditions.append(Task.parent_id == parent_id)

    today = today_brt().isoformat()

    # exclude snoozed tasks from inbox (snoozed_until > today)
    if reviewed == 0:
        conditions.append(
            or_(Task.snoozed_until.is_(None), Task.snoozed_until <= today)
        )

    if deadline == "today":
        conditions.append(Task.deadline == today)
    elif deadline == "overdue":
        conditions.append(and_(Task.deadline.isnot(None), Task.deadline < today))
    elif deadline == "week":
        week_end = (today_brt() + timedelta(days=7)).isoformat()
        conditions.append(and_(Task.deadline >= today, Task.deadline <= week_end))
    elif deadline == "null":
        conditions.append(Task.deadline.is_(None))

    if conditions:
        q = q.where(and_(*conditions))

    q = q.order_by(Task.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_task(db: AsyncSession, task_id: str, data: TaskUpdate) -> Optional[Task]:
    task = await get_task(db, task_id)
    if not task:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    task.updated_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(task)
    return task


async def delete_task(db: AsyncSession, task_id: str) -> bool:
    task = await get_task(db, task_id)
    if not task:
        return False
    await db.delete(task)
    await db.commit()
    return True


async def review_task(db: AsyncSession, task_id: str) -> Optional[Task]:
    task = await get_task(db, task_id)
    if not task:
        return None
    if task.reviewed == 0:
        task.reviewed = 1
        task.reviewed_at = now_brt().isoformat()
        task.updated_at = now_brt().isoformat()
        await db.commit()
        await db.refresh(task)
    return task


async def done_task(db: AsyncSession, task_id: str) -> Optional[Task]:
    task = await get_task(db, task_id)
    if not task:
        return None
    task.status = "done"
    task.completed_at = now_brt().isoformat()
    task.updated_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(task)
    return task


async def snooze_task(db: AsyncSession, task_id: str, days: int = 1) -> Optional[Task]:
    task = await get_task(db, task_id)
    if not task:
        return None
    task.snoozed_until = (today_brt() + timedelta(days=days)).isoformat()
    task.updated_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(task)
    return task


async def add_checklist_item(db: AsyncSession, task_id: str, data: ChecklistItemCreate) -> Optional[Checklist]:
    task = await get_task(db, task_id)
    if not task:
        return None
    max_result = await db.execute(
        select(func.max(Checklist.position)).where(Checklist.task_id == task.id)
    )
    max_pos = max_result.scalar() or 0
    item = Checklist(
        id=make_id(),
        task_id=task.id,
        text=data.text,
        done=0,
        position=max_pos + 1,
        created_at=now_brt().isoformat(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_checklist_item(db: AsyncSession, item_id: str, data: ChecklistItemUpdate) -> Optional[Checklist]:
    result = await db.execute(select(Checklist).where(Checklist.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


async def delete_checklist_item(db: AsyncSession, item_id: str) -> bool:
    result = await db.execute(select(Checklist).where(Checklist.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return False
    await db.delete(item)
    await db.commit()
    return True


async def add_link(db: AsyncSession, task_id: str, data: TaskLinkCreate) -> Optional[TaskLink]:
    task = await get_task(db, task_id)
    if not task:
        return None
    link = TaskLink(
        id=make_id(),
        task_id=task.id,
        url=data.url,
        label=data.label,
        created_at=now_brt().isoformat(),
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def delete_link(db: AsyncSession, link_id: str) -> bool:
    result = await db.execute(select(TaskLink).where(TaskLink.id == link_id))
    link = result.scalar_one_or_none()
    if not link:
        return False
    await db.delete(link)
    await db.commit()
    return True


_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "uploads")


async def upload_image(db: AsyncSession, task_id: str, file) -> Optional[TaskImage]:
    task = await get_task(db, task_id)
    if not task:
        return None
    os.makedirs(_UPLOADS_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    stored = make_id() + ext
    content = await file.read()
    with open(os.path.join(_UPLOADS_DIR, stored), "wb") as f:
        f.write(content)
    img = TaskImage(
        id=make_id(),
        task_id=task.id,
        filename=stored,
        original_name=file.filename or stored,
        mime_type=file.content_type or "image/jpeg",
        size=len(content),
        created_at=now_brt().isoformat(),
    )
    db.add(img)
    await db.commit()
    await db.refresh(img)
    return img


async def list_images(db: AsyncSession, task_id: str) -> list:
    result = await db.execute(
        select(TaskImage).where(TaskImage.task_id == task_id).order_by(TaskImage.created_at)
    )
    return result.scalars().all()


async def delete_image(db: AsyncSession, image_id: str) -> bool:
    result = await db.execute(select(TaskImage).where(TaskImage.id == image_id))
    img = result.scalar_one_or_none()
    if not img:
        return False
    try:
        os.remove(os.path.join(_UPLOADS_DIR, img.filename))
    except FileNotFoundError:
        pass
    await db.delete(img)
    await db.commit()
    return True


async def get_last_wa_task(db: AsyncSession, within_seconds: int = 3600) -> Optional[Task]:
    from datetime import timedelta
    cutoff = (now_brt() - timedelta(seconds=within_seconds)).isoformat()
    result = await db.execute(
        select(Task)
        .where(Task.source == "whatsapp", Task.created_at >= cutoff)
        .order_by(Task.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
