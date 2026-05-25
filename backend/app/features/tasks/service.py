import os
from typing import Optional
from datetime import date, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.features.tasks.models import Task, Checklist, TaskLink, TaskImage
from app.features.tasks.schemas import (
    TaskCreate, TaskUpdate, SnoozeRequest,
    ChecklistItemCreate, ChecklistItemUpdate, TaskLinkCreate,
)
from app.shared.ids import make_id, make_short_id
from app.shared.dates import now_brt, today_brt


_SESSION_CAP_MINUTES = 360  # 6h — corner case se cron 19h/22h falhar


def _accumulate_doing_time(task: Task) -> int:
    """Soma o tempo da sessão atual (desde doing_since) em time_spent_minutes.
    Cap de 6h por sessão. Retorna minutos adicionados. Limpa doing_since."""
    if not task or not task.doing_since:
        return 0
    try:
        start = datetime.fromisoformat(task.doing_since)
    except (ValueError, TypeError):
        task.doing_since = None
        return 0
    elapsed_min = int((now_brt() - start).total_seconds() / 60)
    if elapsed_min <= 0:
        task.doing_since = None
        return 0
    credited = min(elapsed_min, _SESSION_CAP_MINUTES)
    task.time_spent_minutes = (task.time_spent_minutes or 0) + credited
    task.doing_since = None
    return credited


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
    await db.flush()
    demoted: list[Task] = []
    if task.status == "todo" and _task_context(task.project_slug) == "personal":
        demoted = await _enforce_personal_todo_cap(db)
    await db.commit()
    await db.refresh(task)
    task._demoted = demoted  # attr transient — pydantic ignora _
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


_PERSONAL_KEYWORDS = ("pessoal", "personal", "vida", "casa", "saude", "hobby")

_PERSONAL_TODO_CAP = 4


def _task_context(project_slug: str | None) -> str:
    """Mesma lógica do frontend getProjectContext: sem slug = hotmart; keywords pessoais = personal."""
    if not project_slug:
        return "hotmart"
    s = project_slug.lower()
    return "personal" if any(k in s for k in _PERSONAL_KEYWORDS) else "hotmart"


def _priority_weight(p: str | None) -> int:
    return {"p1": 3, "p2": 2, "p3": 1, "backlog": 0}.get(p or "", 1)


async def _enforce_personal_todo_cap(db: AsyncSession) -> list[Task]:
    """Mantém no máximo _PERSONAL_TODO_CAP tasks pessoais com status='todo'.
    Rebaixa excedentes para 'backlog' (menor prioridade primeiro, depois mais antigas).
    Retorna lista das tasks rebaixadas. Não toca em subtasks."""
    res = await db.execute(select(Task).where(Task.status == "todo", Task.parent_id.is_(None)))
    all_todo = list(res.scalars().all())
    personal = [t for t in all_todo if _task_context(t.project_slug) == "personal"]
    excess = len(personal) - _PERSONAL_TODO_CAP
    if excess <= 0:
        return []
    personal.sort(key=lambda t: (_priority_weight(t.priority), t.created_at or ""))
    now = now_brt().isoformat()
    demoted = personal[:excess]
    for t in demoted:
        t.status = "backlog"
        t.updated_at = now
    return demoted


async def _demote_other_doing(db: AsyncSession, keep_task_id: str) -> None:
    """Garante só 1 'doing' POR CONTEXTO (personal vs hotmart). Rebaixa as outras pra 'todo'."""
    keep = await db.get(Task, keep_task_id)
    if not keep:
        return
    keep_ctx = _task_context(keep.project_slug)
    res = await db.execute(select(Task).where(Task.status == "doing", Task.id != keep_task_id))
    now = now_brt().isoformat()
    for other in res.scalars().all():
        if _task_context(other.project_slug) == keep_ctx:
            _accumulate_doing_time(other)
            other.status = "todo"
            other.updated_at = now


async def update_task(db: AsyncSession, task_id: str, data: TaskUpdate) -> Optional[Task]:
    task = await get_task(db, task_id)
    if not task:
        return None
    prev_status = task.status
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(task, field, value)
    now = now_brt().isoformat()
    task.updated_at = now
    new_status = payload.get("status")
    if new_status == "doing" and prev_status != "doing":
        task.doing_since = now
        await _demote_other_doing(db, task.id)
    elif new_status is not None and new_status != "doing" and prev_status == "doing":
        _accumulate_doing_time(task)
    demoted: list[Task] = []
    if task.status == "todo" and _task_context(task.project_slug) == "personal":
        demoted = await _enforce_personal_todo_cap(db)
    await db.commit()
    await db.refresh(task)
    task._demoted = demoted
    return task


async def set_now_task(db: AsyncSession, task_id: str) -> Optional[Task]:
    """Promove tarefa para 'doing' e rebaixa qualquer outra que estivesse 'doing'."""
    task = await get_task(db, task_id)
    if not task:
        return None
    await _demote_other_doing(db, task.id)
    now = now_brt().isoformat()
    if task.status != "doing":
        task.doing_since = now
    task.status = "doing"
    task.updated_at = now
    # _demote_other_doing pode ter empurrado tasks para 'todo' (pessoal): aplicar cap
    demoted = await _enforce_personal_todo_cap(db)
    await db.commit()
    await db.refresh(task)
    task._demoted = demoted
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
        if task.status in (None, 'raw'):
            task.status = 'todo'
        demoted: list[Task] = []
        if task.status == "todo" and _task_context(task.project_slug) == "personal":
            demoted = await _enforce_personal_todo_cap(db)
        await db.commit()
        await db.refresh(task)
        task._demoted = demoted
    return task


async def done_task(db: AsyncSession, task_id: str) -> Optional[Task]:
    task = await get_task(db, task_id)
    if not task:
        return None
    if task.doing_since:
        _accumulate_doing_time(task)
    task.status = "done"
    task.completed_at = now_brt().isoformat()
    task.updated_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(task)
    return task


async def undo_cap_demotion(db: AsyncSession, trigger_id: str, restored_ids: list[str]) -> dict:
    """Reverte um rebaixamento por WIP cap:
    - trigger (a task que causou o cap) volta pra 'backlog'
    - restored (as que tinham sido empurradas) voltam pra 'todo'
    NÃO aplica o cap de novo (essa é a vontade explícita do usuário)."""
    now = now_brt().isoformat()
    out = {"trigger": None, "restored": []}
    trigger = await get_task(db, trigger_id)
    if trigger:
        trigger.status = "backlog"
        trigger.doing_since = None
        trigger.updated_at = now
        out["trigger"] = trigger
    for rid in restored_ids:
        t = await get_task(db, rid)
        if t:
            t.status = "todo"
            t.updated_at = now
            out["restored"].append(t)
    await db.commit()
    return out


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


async def auto_deactivate_doing(db: AsyncSession) -> list[Task]:
    """Varre tasks em 'doing', acumula tempo da sessão, demote pra 'todo'.
    Usado pelo scheduler às 19h (com notificação) e 22h (silencioso safety net)."""
    res = await db.execute(select(Task).where(Task.status == "doing"))
    tasks = list(res.scalars().all())
    if not tasks:
        return []
    now = now_brt().isoformat()
    for t in tasks:
        _accumulate_doing_time(t)
        t.status = "todo"
        t.updated_at = now
    await db.commit()
    return tasks


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
