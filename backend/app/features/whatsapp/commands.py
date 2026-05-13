import re
from typing import Optional, Tuple
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.tasks.service import (
    get_task, done_task, update_task, delete_task,
    list_tasks, get_last_wa_task,
)
from app.features.tasks.schemas import TaskUpdate
from app.shared.dates import today_brt, days_overdue
from app.shared.responses import (
    format_task_list, format_done, format_deadline_updated,
    format_project_updated, format_cancelled, format_inbox_count,
    PRIORITY_EMOJI,
)


async def handle_command(text: str, db: AsyncSession, projects: list) -> Tuple[bool, Optional[str]]:
    """Returns (is_command, response). If not a command, returns (False, None)."""
    t = text.strip().lower()

    # ? / hoje
    if t in ("?", "hoje", "today"):
        today = today_brt().isoformat()
        tasks = [t for t in await list_tasks(db, reviewed=1, deadline="today") if t.status != "done"]
        overdue = [t for t in await list_tasks(db, reviewed=1, deadline="overdue") if t.status != "done"]
        response = format_task_list(tasks, "hoje")
        if overdue:
            response += f"\n\n⚠️ {len(overdue)} atrasada{'s' if len(overdue) != 1 else ''}"
            for task in overdue[:5]:
                d = days_overdue(date.fromisoformat(task.deadline))
                emoji = PRIORITY_EMOJI.get(task.priority, "⚪")
                proj = task.project_slug or "sem projeto"
                response += f"\n{emoji} #{task.short_id} · {proj} · {task.title} (-{d} dias)"
        return True, response

    # atrasadas
    if t in ("atrasadas", "overdue"):
        tasks = [t for t in await list_tasks(db, reviewed=1, deadline="overdue") if t.status != "done"]
        return True, format_task_list(tasks, "atrasadas")

    # inbox
    if t == "inbox":
        tasks = await list_tasks(db, reviewed=0)
        return True, format_inbox_count(len(tasks))

    # done <short_id>
    m = re.match(r"^done\s+#?(\w+)$", t)
    if m:
        short = m.group(1)
        task = await get_task(db, short)
        if task:
            await done_task(db, task.id)
            return True, format_done(task)
        return True, f"❓ tarefa #{short} não encontrada"

    # prazo <data>
    m = re.match(r"^prazo\s+(.+)$", t)
    if m:
        new_date = _parse_natural_date(m.group(1).strip())
        if new_date:
            task = await get_last_wa_task(db)
            if task:
                await update_task(db, task.id, TaskUpdate(deadline=new_date.isoformat()))
                task = await get_task(db, task.id)
                return True, format_deadline_updated(task)
        return True, "❓ não entendi a data. Tenta: prazo sexta, prazo 15/05, prazo amanhã"

    # projeto <slug>
    m = re.match(r"^projeto\s+(\S+)$", t)
    if m:
        slug = m.group(1).lower()
        project = next((p for p in projects if p.slug == slug), None)
        if project:
            task = await get_last_wa_task(db)
            if task:
                await update_task(db, task.id, TaskUpdate(project_slug=slug))
                return True, format_project_updated(task, project.name)
        return True, f"❓ projeto '{slug}' não encontrado. Use /api/projects pra ver os slugs"

    # cancelar / desfazer
    if t in ("cancelar", "desfazer", "undo", "cancela"):
        task = await get_last_wa_task(db, within_seconds=60)
        if task:
            await delete_task(db, task.id)
            return True, format_cancelled(task)
        return True, "❓ nenhuma tarefa recente pra cancelar (janela de 60s expirou)"

    return False, None


def _parse_natural_date(text: str) -> Optional[date]:
    today = today_brt()
    t = text.strip().lower()

    if t in ("hoje", "today"):
        return today
    if t in ("amanhã", "amanha", "tomorrow"):
        return today + timedelta(days=1)
    if t in ("depois de amanhã", "depois de amanha"):
        return today + timedelta(days=2)
    if t in ("semana que vem", "semana que vem", "próxima semana"):
        return today + timedelta(days=7)
    if t in ("fim de semana", "fds"):
        days = (5 - today.weekday()) % 7 or 7
        return today + timedelta(days=days)

    WEEKDAYS = {
        "segunda": 0, "segunda-feira": 0, "seg": 0,
        "terça": 1, "terca": 1, "terça-feira": 1, "ter": 1,
        "quarta": 2, "quarta-feira": 2, "qua": 2,
        "quinta": 3, "quinta-feira": 3, "qui": 3,
        "sexta": 4, "sexta-feira": 4, "sex": 4,
        "sábado": 5, "sabado": 5, "sáb": 5, "sab": 5,
        "domingo": 6, "dom": 6,
    }
    if t in WEEKDAYS:
        target = WEEKDAYS[t]
        days_ahead = (target - today.weekday()) % 7 or 7
        return today + timedelta(days=days_ahead)

    # DD/MM or DD/MM/YYYY
    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{4}))?$", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            return date(year, month, day)
        except ValueError:
            return None

    # dia 15
    m = re.match(r"^dia\s+(\d{1,2})$", t)
    if m:
        day = int(m.group(1))
        try:
            d = date(today.year, today.month, day)
            if d < today:
                month = today.month + 1 if today.month < 12 else 1
                year = today.year if today.month < 12 else today.year + 1
                d = date(year, month, day)
            return d
        except ValueError:
            return None

    try:
        return date.fromisoformat(t)
    except ValueError:
        return None
