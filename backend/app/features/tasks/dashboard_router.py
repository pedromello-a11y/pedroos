from datetime import datetime, date as _date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.features.tasks.models import Task
from app.features.projects.models import Project
from app.features.ai.models import AIMemory
from app.features.integrations.router import _get_access_token, _meetings_from_api
from app.shared.dates import now_brt, today_brt, format_date_pt, DAYS_PT, MONTHS_PT

router = APIRouter(prefix="/api/tasks", tags=["dashboard"])

_URGENCY_ORDER = {"overdue": 0, "today": 1, "tomorrow": 2, "this_week": 3, "none": 4}


@router.get("/dashboard")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    now = now_brt()
    today = today_brt()

    # Tarefas ativas e revisadas (sem subtarefas)
    result = await db.execute(
        select(Task).where(
            Task.status.notin_(["done", "raw"]),
            Task.reviewed == 1,
            Task.parent_id.is_(None),
        ).order_by(Task.position, Task.created_at)
    )
    tasks = result.scalars().all()

    # Projetos para lookup de nome/cor
    proj_result = await db.execute(select(Project))
    projects = {p.slug: p for p in proj_result.scalars().all()}

    # Classificar tarefas
    now_task = None
    today_tasks = []
    blocked_tasks = []
    queued_tasks = []
    backlog_tasks = []

    for task in tasks:
        fmt = _format_task(task, today, projects)

        if task.status_note:
            blocked_tasks.append(fmt)
        elif task.status == "doing":
            if now_task is None:
                now_task = fmt
            else:
                today_tasks.append(fmt)
        elif task.status == "queued":
            queued_tasks.append(fmt)
        elif task.status == "backlog" or task.priority == "backlog":
            backlog_tasks.append(fmt)
        else:
            today_tasks.append(fmt)

    today_tasks.sort(key=lambda t: _URGENCY_ORDER.get(t["deadline_urgency"], 4))

    # Progresso do dia (9h–18h)
    work_start = now.replace(hour=9,  minute=0, second=0, microsecond=0)
    work_end   = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now <= work_start:
        work_progress = 0
    elif now >= work_end:
        work_progress = 100
    else:
        elapsed = (now - work_start).total_seconds()
        total   = (work_end - work_start).total_seconds()
        work_progress = int((elapsed / total) * 100)

    # Tempo livre restante no dia de trabalho
    remaining_work_min = max(0, int((work_end - now).total_seconds() / 60)) if now < work_end else 0

    # Agenda do Google Calendar
    agenda = []
    total_meeting_min = 0
    try:
        token = await _get_access_token()
        events = []
        if token:
            cal = await _meetings_from_api(token, today.isoformat())
            events = cal.get("events", [])

        for ev in events:
            start_time = ev.get("start_time", "")
            end_time   = ev.get("end_time", "")
            duration_min = 60
            is_now = False

            if start_time and end_time:
                try:
                    sh, sm = map(int, start_time.split(":"))
                    eh, em = map(int, end_time.split(":"))
                    duration_min = max(1, (eh * 60 + em) - (sh * 60 + sm))
                    ev_start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                    ev_end   = now.replace(hour=eh, minute=em, second=0, microsecond=0)
                    is_now   = ev_start <= now <= ev_end
                except (ValueError, AttributeError):
                    pass

            total_meeting_min += duration_min
            agenda.append({
                "time":         start_time,
                "title":        ev.get("title", ""),
                "duration_min": duration_min,
                "is_now":       is_now,
            })
    except Exception:
        pass

    free_minutes = max(0, remaining_work_min - total_meeting_min)

    # Deadlines próximas (tarefas com prazo nos próximos 7 dias)
    dl_result = await db.execute(
        select(Task).where(
            Task.status.notin_(["done"]),
            Task.deadline.isnot(None),
        )
    )
    upcoming_deadlines = []
    for task in dl_result.scalars().all():
        urgency = _calc_urgency(task.deadline, today)
        if urgency in ("overdue", "today", "tomorrow", "this_week"):
            proj = projects.get(task.project_slug)
            upcoming_deadlines.append({
                "task_title": task.title,
                "project":    proj.name if proj else "",
                "date":       _fmt_deadline(task.deadline),
                "urgency":    urgency,
            })
    upcoming_deadlines.sort(key=lambda d: _URGENCY_ORDER.get(d["urgency"], 4))

    # Memórias de IA
    mem_result = await db.execute(
        select(AIMemory)
        .where(AIMemory.is_active.is_(True))
        .order_by(AIMemory.confidence.desc())
        .limit(5)
    )
    memories = [
        {"content": m.content, "confidence": m.confidence, "category": m.category}
        for m in mem_result.scalars().all()
    ]

    return {
        "today_date":  format_date_pt(today).capitalize(),
        "current_time": now.strftime("%H:%M"),
        "now_task":    now_task,
        "today_tasks": today_tasks[:5],
        "blocked_tasks":   blocked_tasks,
        "queued_tasks":    queued_tasks,
        "backlog_tasks":   backlog_tasks,
        "time_available": {
            "total_free_minutes": free_minutes,
            "free_windows":       [],
            "work_progress":      work_progress,
        },
        "agenda":              agenda,
        "upcoming_deadlines":  upcoming_deadlines[:5],
        "memories":            memories,
    }


@router.post("/{task_id}/set-now")
async def set_task_as_now(task_id: str, db: AsyncSession = Depends(get_db)):
    """Marca task como 'doing' e rebaixa a anterior para 'todo'."""
    # Rebaixa doing atual
    prev = await db.execute(select(Task).where(Task.status == "doing"))
    for t in prev.scalars().all():
        t.status = "todo"
        t.updated_at = now_brt().isoformat()

    # Busca por id ou short_id
    result = await db.execute(
        select(Task).where(
            (Task.id == task_id) | (Task.short_id == task_id)
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Tarefa não encontrada")

    task.status = "doing"
    task.updated_at = now_brt().isoformat()
    await db.commit()
    return {"ok": True}


@router.post("/{task_id}/complete")
async def complete_task_alias(task_id: str, db: AsyncSession = Depends(get_db)):
    """Alias de /done — compatível com o frontend do dashboard."""
    from app.features.tasks.service import done_task
    task = await done_task(db, task_id)
    if not task:
        raise HTTPException(404, "Tarefa não encontrada")
    return {"ok": True}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_task(task: Task, today: _date, projects: dict) -> dict:
    proj = projects.get(task.project_slug)
    urgency = _calc_urgency(task.deadline, today) if task.deadline else "none"

    blocker_days = None
    if task.status_note and task.updated_at:
        try:
            updated = datetime.fromisoformat(task.updated_at).date()
            blocker_days = (today - updated).days
        except Exception:
            pass

    estimated_minutes = int(task.estimated_hours * 60) if task.estimated_hours else None

    return {
        "id":               task.id,
        "short_id":         task.short_id,
        "title":            task.title,
        "status":           task.status,
        "project":          proj.name  if proj else None,
        "project_color":    proj.color if proj else None,
        "deadline":         task.deadline,
        "deadline_urgency": urgency,
        "notes":            task.description,
        "blocker":          task.status_note,
        "blocker_days":     blocker_days,
        "estimated_minutes": estimated_minutes,
        "subtasks":         [],
        "priority":         task.priority,
    }


def _calc_urgency(deadline_str: str, today: _date) -> str:
    try:
        d = _date.fromisoformat(deadline_str[:10])
        diff = (d - today).days
        if diff < 0:   return "overdue"
        if diff == 0:  return "today"
        if diff == 1:  return "tomorrow"
        if diff <= 7:  return "this_week"
    except Exception:
        pass
    return "none"


def _fmt_deadline(deadline_str: str) -> str:
    try:
        d = _date.fromisoformat(deadline_str[:10])
        return f"{DAYS_PT[d.weekday()]} {d.day} {MONTHS_PT[d.month - 1]}"
    except Exception:
        return deadline_str
