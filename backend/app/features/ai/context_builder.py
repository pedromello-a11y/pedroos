"""Monta o contexto completo do estado atual do usuário para injetar na IA."""
import json
from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.shared.dates import now_brt
from app.features.tasks.models import Task
from app.features.ai.models import AIMemory, FocusSession, CheckIn


async def build_context_prompt(db: AsyncSession) -> str:
    """Retorna contexto completo como texto para o prompt da IA."""
    now = now_brt()
    today = now.date().isoformat()
    yesterday = (now.date() - timedelta(days=1)).isoformat()

    # Tarefas ativas
    res = await db.execute(select(Task).where(Task.status != "done", Task.reviewed == 1))
    tasks = res.scalars().all()

    doing = [t for t in tasks if t.status == "doing"]
    queued = [t for t in tasks if t.status == "queued"]
    todo = [t for t in tasks if t.status == "todo"]
    backlog = [t for t in tasks if t.status == "backlog"]

    # Tarefas atrasadas
    res_ov = await db.execute(
        select(Task).where(
            Task.status != "done",
            Task.deadline.isnot(None),
            Task.deadline < today,
        )
    )
    overdue = res_ov.scalars().all()

    # Memórias ativas
    res_mem = await db.execute(
        select(AIMemory)
        .where(AIMemory.is_active == True, AIMemory.confidence >= 0.3)
        .order_by(AIMemory.confidence.desc())
        .limit(8)
    )
    memories = res_mem.scalars().all()

    # Atividade recente (concluídas ontem/hoje)
    res_done = await db.execute(
        select(Task).where(
            Task.status == "done",
            Task.completed_at >= yesterday,
        )
    )
    done_recent = res_done.scalars().all()

    _DAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    _MONTHS_PT = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]

    lines = [
        f"=== CONTEXTO ATUAL ===",
        f"Agora: {now.strftime('%H:%M')} de {_DAYS_PT[now.weekday()]}, {now.day} {_MONTHS_PT[now.month-1]}",
        "",
    ]

    if doing:
        lines.append("🔴 FAZENDO:")
        for t in doing:
            dl = f" [prazo: {t.deadline}]" if t.deadline else ""
            lines.append(f"  · {t.title}{dl}")
        lines.append("")

    if overdue:
        lines.append("⚠️ ATRASADAS:")
        for t in overdue[:5]:
            lines.append(f"  · {t.title} (prazo era {t.deadline})")
        lines.append("")

    if queued:
        lines.append("🔵 NA FILA:")
        for t in queued[:8]:
            dl = f" [{t.deadline}]" if t.deadline else ""
            lines.append(f"  · {t.title}{dl}")
        lines.append("")

    if todo:
        lines.append("🟡 AGUARDANDO:")
        for t in todo[:8]:
            dl = f" [{t.deadline}]" if t.deadline else ""
            lines.append(f"  · {t.title}{dl}")
        lines.append("")

    if backlog:
        lines.append(f"⚪ BACKLOG: {len(backlog)} tarefas")
        lines.append("")

    if done_recent:
        lines.append("✅ CONCLUÍDAS RECENTEMENTE:")
        for t in done_recent[:5]:
            lines.append(f"  · {t.title}")
        lines.append("")

    if memories:
        lines.append("🧠 PADRÕES CONHECIDOS SOBRE VOCÊ:")
        for m in memories:
            lines.append(f"  • {m.content} ({m.confidence:.0%} confiança)")
        lines.append("")

    return "\n".join(lines)
