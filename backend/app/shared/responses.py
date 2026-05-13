from typing import Optional
from datetime import date
from .dates import format_date_pt, today_brt, days_overdue

PRIORITY_EMOJI = {"p1": "🔺", "p2": "🔸", "p3": "⚪", "backlog": "⬜"}


def format_task_created(task, project_name: Optional[str] = None) -> str:
    emoji = PRIORITY_EMOJI.get(task.priority, "⚪")
    project_part = project_name or "sem projeto"

    if task.deadline:
        try:
            d = date.fromisoformat(task.deadline)
            deadline_part = format_date_pt(d)
        except (ValueError, TypeError):
            deadline_part = task.deadline
    else:
        deadline_part = "sem prazo"

    lines = [f"📥 #{task.short_id} · {project_part} · {deadline_part} · {emoji}"]
    lines.append(f'"{task.title}"')
    return "\n".join(lines)


def format_task_list(tasks: list, title: str = "hoje") -> str:
    count = len(tasks)
    if count == 0:
        return f"📋 {title} · nenhuma tarefa"

    lines = [f"📋 {title} · {count} tarefa{'s' if count != 1 else ''}", ""]

    today = today_brt()
    overdue = [t for t in tasks if t.deadline and date.fromisoformat(t.deadline) < today]
    normal = [t for t in tasks if not t.deadline or date.fromisoformat(t.deadline) >= today]

    for t in normal:
        emoji = PRIORITY_EMOJI.get(t.priority, "⚪")
        proj = t.project_slug or "sem projeto"
        lines.append(f"{emoji} #{t.short_id} · {proj} · {t.title}")

    if overdue:
        lines.append("")
        lines.append(f"⚠️ {len(overdue)} atrasada{'s' if len(overdue) != 1 else ''}")
        for t in overdue:
            emoji = PRIORITY_EMOJI.get(t.priority, "⚪")
            d = days_overdue(date.fromisoformat(t.deadline))
            proj = t.project_slug or "sem projeto"
            lines.append(f"{emoji} #{t.short_id} · {proj} · {t.title} (-{d} dias)")

    return "\n".join(lines)


def format_done(task) -> str:
    return f"✅ #{task.short_id} concluída"


def format_deadline_updated(task) -> str:
    try:
        d = format_date_pt(date.fromisoformat(task.deadline))
    except Exception:
        d = task.deadline or "sem prazo"
    return f"📅 #{task.short_id} · prazo atualizado pra {d}"


def format_project_updated(task, project_name: str) -> str:
    return f"📁 #{task.short_id} · {project_name}"


def format_cancelled(task) -> str:
    return f"🗑️ #{task.short_id} cancelada"


def format_inbox_count(count: int) -> str:
    return f"📥 {count} tarefa{'s' if count != 1 else ''} pra revisar"
