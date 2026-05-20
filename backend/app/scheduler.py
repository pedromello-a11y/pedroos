"""
Background scheduler — roda dentro do mesmo processo uvicorn.
- Resumo diário: 08:30 BRT (dias úteis e fins de semana)
- Revisão semanal: segunda-feira 09:00 BRT
"""
import asyncio
import logging
from datetime import timedelta

from app.shared.dates import now_brt
from app.config import settings

logger = logging.getLogger(__name__)

_PRIO_EMOJI = {"p1": "🔺", "p2": "🔸", "p3": "·", "backlog": "·"}
_DAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
_MONTHS_PT = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]


def _fmt_date(iso: str) -> str:
    from datetime import date
    d = date.fromisoformat(iso)
    return f"{d.day} {_MONTHS_PT[d.month - 1]}"


async def _get_meetings_today() -> list[dict]:
    """Retorna reuniões de hoje (work + personal), ordenadas por horário."""
    from app.features.integrations.router import (
        _meetings_from_api, _meetings_from_ics, _get_access_token,
    )
    events = []
    try:
        access_token = await _get_access_token()
        if access_token:
            res = await _meetings_from_api(access_token)
        else:
            res = await _meetings_from_ics()
        events += res.get("events", [])
    except Exception:
        pass
    try:
        ics_url = settings.personal_calendar_ics_url
        if ics_url:
            res2 = await _meetings_from_ics(ics_url)
            events += res2.get("events", [])
    except Exception:
        pass
    return sorted(events, key=lambda e: e.get("start_time") or "")


async def _build_daily_summary() -> str:
    from sqlalchemy import select
    from app.features.tasks.models import Task
    from app.db import AsyncSessionLocal

    today = now_brt().date().isoformat()

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Task).where(
                Task.status.in_(["todo", "doing"]),
                Task.deadline == today,
            )
        )
        today_tasks = res.scalars().all()

        res2 = await db.execute(
            select(Task).where(
                Task.status == "doing",
                Task.deadline != today,
            )
        )
        doing_extra = [t for t in res2.scalars().all() if t.deadline != today]

        res3 = await db.execute(
            select(Task).where(Task.status == "doing", Task.deadline.is_(None))
        )
        doing_no_deadline = res3.scalars().all()
        doing_all = list(doing_extra) + list(doing_no_deadline)

        res4 = await db.execute(
            select(Task).where(
                Task.status == "todo",
                Task.deadline < today,
                Task.deadline.isnot(None),
            )
        )
        overdue = res4.scalars().all()

    meetings = await _get_meetings_today()

    now = now_brt()
    day_name = _DAYS_PT[now.weekday()]
    date_str = f"{now.day} {_MONTHS_PT[now.month - 1]}"
    lines = [f"☀️ *Bom dia!* {day_name.capitalize()}, {date_str}"]

    if meetings:
        lines.append(f"\n🗓 *Reuniões ({len(meetings)}):*")
        for ev in meetings:
            time_str = ev.get("start_time", "")[:5] if ev.get("start_time") else ""
            end_str = ev.get("end_time", "")[:5] if ev.get("end_time") else ""
            time_label = f"{time_str}–{end_str}" if end_str else time_str
            lines.append(f"  · {time_label} {ev.get('title', '')}")

    if doing_all:
        lines.append(f"\n🔥 *Fazendo ({len(doing_all)}):*")
        for t in doing_all:
            lines.append(f"  · {t.title}")

    if today_tasks:
        lines.append(f"\n📅 *Vence hoje ({len(today_tasks)}):*")
        for t in today_tasks:
            e = _PRIO_EMOJI.get(t.priority, "·")
            lines.append(f"  {e} {t.title}")

    if overdue:
        lines.append(f"\n⚠️ *Atrasadas ({len(overdue)}):*")
        for t in overdue[:5]:
            lines.append(f"  · {t.title} _{_fmt_date(t.deadline)}_")
        if len(overdue) > 5:
            lines.append(f"  …e mais {len(overdue) - 5}")

    if not meetings and not doing_all and not today_tasks and not overdue:
        lines.append("\n✨ Agenda limpa! Dia livre pra criar.")

    return "\n".join(lines)


async def _build_tomorrow_meetings() -> str:
    """Reuniões do dia seguinte — enviado às 18h."""
    from app.features.integrations.router import (
        _meetings_from_api, _meetings_from_ics, _get_access_token,
    )
    tomorrow = (now_brt().date() + timedelta(days=1)).isoformat()
    day_name = _DAYS_PT[(now_brt().weekday() + 1) % 7]
    d = now_brt().date() + timedelta(days=1)
    date_str = f"{d.day} {_MONTHS_PT[d.month - 1]}"

    events = []
    try:
        access_token = await _get_access_token()
        if access_token:
            res = await _meetings_from_api(access_token, target_date=tomorrow)
        else:
            res = await _meetings_from_ics(target_date=tomorrow)
        events += res.get("events", [])
    except Exception:
        pass
    try:
        ics_url = settings.personal_calendar_ics_url
        if ics_url:
            res2 = await _meetings_from_ics(ics_url, target_date=tomorrow)
            events += res2.get("events", [])
    except Exception:
        pass

    events = sorted(events, key=lambda e: e.get("start_time") or "")

    lines = [f"🌙 *Amanhã* — {day_name.capitalize()}, {date_str}"]
    if events:
        for ev in events:
            time_str = ev.get("start_time", "")[:5] if ev.get("start_time") else ""
            end_str = ev.get("end_time", "")[:5] if ev.get("end_time") else ""
            time_label = f"{time_str}–{end_str}" if end_str else time_str
            lines.append(f"  · {time_label} {ev.get('title', '')}")
    else:
        lines.append("  ✨ Sem reuniões marcadas.")

    return "\n".join(lines)


async def _build_weekly_summary() -> str:
    from sqlalchemy import select
    from app.features.tasks.models import Task
    from app.db import AsyncSessionLocal

    today = now_brt().date()
    today_str = today.isoformat()
    week_end = (today + timedelta(days=6)).isoformat()

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Task).where(
                Task.status.in_(["todo", "doing"]),
                Task.deadline >= today_str,
                Task.deadline <= week_end,
            )
        )
        week_tasks = res.scalars().all()

        res2 = await db.execute(select(Task).where(Task.status == "doing"))
        doing = res2.scalars().all()

        res3 = await db.execute(
            select(Task).where(
                Task.status == "todo",
                Task.deadline < today_str,
                Task.deadline.isnot(None),
            )
        )
        overdue = res3.scalars().all()

        res4 = await db.execute(select(Task).where(Task.reviewed == 0))
        inbox_count = len(res4.scalars().all())

    date_str = f"{today.day} {_MONTHS_PT[today.month - 1]}"
    lines = [f"📋 *Revisão semanal* — {date_str}"]

    if doing:
        lines.append(f"\n🔥 *Em andamento ({len(doing)}):*")
        for t in doing:
            lines.append(f"  · {t.title}")

    if overdue:
        lines.append(f"\n⚠️ *Atrasadas ({len(overdue)}):*")
        for t in overdue[:8]:
            lines.append(f"  · {t.title} _{_fmt_date(t.deadline)}_")
        if len(overdue) > 8:
            lines.append(f"  …e mais {len(overdue) - 8}")

    if week_tasks:
        sorted_week = sorted(week_tasks, key=lambda t: t.deadline or "")
        lines.append(f"\n📅 *Vencem esta semana ({len(sorted_week)}):*")
        for t in sorted_week:
            e = _PRIO_EMOJI.get(t.priority, "·")
            lines.append(f"  {e} {_fmt_date(t.deadline)} — {t.title}")

    if inbox_count:
        lines.append(f"\n📥 *Inbox não revisado: {inbox_count} item(ns)*")

    if not doing and not week_tasks and not overdue:
        lines.append("\n✨ Semana limpa! Bom momento pra planejar.")

    return "\n".join(lines)


async def _build_eod_summary() -> str:
    """Resumo do fim do dia às 19h: o que foi feito + agenda de amanhã."""
    from sqlalchemy import select
    from app.features.tasks.models import Task
    from app.db import AsyncSessionLocal

    today = now_brt().date().isoformat()
    tomorrow = (now_brt().date() + timedelta(days=1)).isoformat()

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Task).where(
                Task.status == "done",
                Task.completed_at.startswith(today),
            )
        )
        done_today = res.scalars().all()

        res2 = await db.execute(
            select(Task).where(
                Task.status.in_(["todo", "doing"]),
                Task.deadline == tomorrow,
            )
        )
        tomorrow_tasks = res2.scalars().all()

    now = now_brt()
    day_name = _DAYS_PT[now.weekday()]
    date_str = f"{now.day} {_MONTHS_PT[now.month - 1]}"
    lines = [f"🌆 *Fim do dia* — {day_name.capitalize()}, {date_str}"]

    if done_today:
        lines.append(f"\n✅ *Realizei hoje ({len(done_today)}):*")
        for t in done_today:
            lines.append(f"  · {t.title}")
    else:
        lines.append("\n📭 Nenhuma tarefa finalizada hoje.")

    tomorrow_msg = await _build_tomorrow_meetings()
    lines.append("")
    lines.append(tomorrow_msg)

    if tomorrow_tasks:
        lines.append(f"\n📅 *Amanhã vence ({len(tomorrow_tasks)}):*")
        for t in tomorrow_tasks:
            e = _PRIO_EMOJI.get(t.priority, "·")
            lines.append(f"  {e} {t.title}")

    return "\n".join(lines)


async def _check_task_reminders(send_fn, target_jid: str):
    """Envia lembretes de tarefas cujo remind_at chegou. Limpa o campo após enviar."""
    from sqlalchemy import select
    from app.features.tasks.models import Task
    from app.db import AsyncSessionLocal

    now_str = now_brt().isoformat()
    window_start = (now_brt() - timedelta(minutes=2)).isoformat()

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Task).where(
                Task.remind_at.isnot(None),
                Task.remind_at <= now_str,
                Task.remind_at >= window_start,
                Task.status != "done",
            )
        )
        tasks = res.scalars().all()
        for task in tasks:
            msg = f"⏰ *Lembrete:* {task.title}"
            if task.deadline:
                msg += f"\n📅 Prazo: {_fmt_date(task.deadline)}"
            ok = await send_fn(target_jid, msg)
            if ok:
                task.remind_at = None
                task.updated_at = now_brt().isoformat()
                logger.info("[scheduler] lembrete enviado: %s", task.short_id)
        if tasks:
            await db.commit()


async def _run_scheduler():
    from app.features.whatsapp.sender import send_whatsapp

    target_jid = settings.my_whatsapp_jid or settings.alfred_group_jid
    if not target_jid:
        logger.warning("[scheduler] my_whatsapp_jid não configurado — resumos desativados")
        return

    sent: set[str] = set()

    while True:
        await asyncio.sleep(30)
        try:
            now = now_brt()
            today = now.date().isoformat()
            h, m = now.hour, now.minute

            # Resumo diário — 08:30
            key_daily = f"daily_{today}"
            if h == 8 and m == 30 and key_daily not in sent:
                msg = await _build_daily_summary()
                ok = await send_whatsapp(target_jid, msg)
                if ok:
                    sent.add(key_daily)
                    logger.info("[scheduler] resumo diário enviado")

            # Agenda do dia seguinte — 18:00
            key_tomorrow = f"tomorrow_{today}"
            if h == 18 and m == 0 and key_tomorrow not in sent:
                msg = await _build_tomorrow_meetings()
                ok = await send_whatsapp(target_jid, msg)
                if ok:
                    sent.add(key_tomorrow)
                    logger.info("[scheduler] agenda amanhã enviada")

            # Resumo fim do dia — 19:00
            key_eod = f"eod_{today}"
            if h == 19 and m == 0 and key_eod not in sent:
                msg = await _build_eod_summary()
                ok = await send_whatsapp(target_jid, msg)
                if ok:
                    sent.add(key_eod)
                    logger.info("[scheduler] resumo fim do dia enviado")

            # Revisão semanal — segunda 09:00
            key_weekly = f"weekly_{today}"
            if now.weekday() == 0 and h == 9 and m == 0 and key_weekly not in sent:
                msg = await _build_weekly_summary()
                ok = await send_whatsapp(target_jid, msg)
                if ok:
                    sent.add(key_weekly)
                    logger.info("[scheduler] revisão semanal enviada")

            # Calcular score do dia — 23:55
            key_score = f"score_{today}"
            if h == 23 and m == 55 and key_score not in sent:
                try:
                    from app.features.habits.service import calculate_day_score
                    from app.db import AsyncSessionLocal as _ScoreSession
                    async with _ScoreSession() as score_db:
                        await calculate_day_score(score_db)
                    sent.add(key_score)
                    logger.info("[scheduler] day score calculado")
                except Exception as e:
                    logger.error(f"[scheduler] erro ao calcular score: {e}")

            # Lembretes de tarefas — verifica a cada ciclo (30s)
            await _check_task_reminders(send_whatsapp, target_jid)

            # Check-in inteligente — a cada 30min durante horário de trabalho
            # (o engine decide se envia ou não)
            if 9 <= h < 18 and not (12 <= h < 13):
                try:
                    from app.features.ai.checkin_engine import should_checkin, generate_checkin
                    from app.db import AsyncSessionLocal as _CheckinSession
                    async with _CheckinSession() as ci_db:
                        check = await should_checkin(ci_db)
                        if check.get("should"):
                            triggers = check.get("triggers", ["manual"])
                            result = await generate_checkin(ci_db, trigger=triggers[0])
                            if "message" in result and not result.get("error"):
                                msg = result["message"] + "\n\n"
                                for i, opt in enumerate(result.get("options", []), 1):
                                    msg += f"{i}️⃣ {opt}\n"
                                await send_whatsapp(target_jid, msg)
                                logger.info("[scheduler] check-in enviado: %s", triggers[0])
                except Exception as ci_exc:
                    logger.error(f"[scheduler] erro no check-in: {ci_exc}")

            # Análise de padrões — toda segunda às 03:00 (silencioso)
            key_patterns = f"patterns_{today}"
            if now.weekday() == 0 and h == 3 and m == 0 and key_patterns not in sent:
                try:
                    from app.features.ai.memory_engine import analyze_patterns
                    from app.db import AsyncSessionLocal as _MemSession
                    async with _MemSession() as mem_db:
                        await analyze_patterns(mem_db)
                    sent.add(key_patterns)
                    logger.info("[scheduler] análise de padrões executada")
                except Exception as mp_exc:
                    logger.error(f"[scheduler] erro na análise de padrões: {mp_exc}")

            # Limpa chaves antigas
            sent = {k for k in sent if today in k}

        except Exception as exc:
            logger.error(f"[scheduler] erro: {exc}")


def start_scheduler():
    asyncio.create_task(_run_scheduler())
