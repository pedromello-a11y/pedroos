"""Engine de check-ins inteligentes e review de fim de dia."""
import json
import logging
from datetime import timedelta
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.shared.dates import now_brt
from app.features.ai.models import CheckIn, DailyReview
from app.features.tasks.models import Task
from app.features.ai.context_builder import build_context_prompt
from app.config import settings

logger = logging.getLogger(__name__)

# Configurações de comportamento
WORK_START_HOUR = 9
WORK_END_HOUR = 18
LUNCH_START = 12
LUNCH_END = 13
MIN_INTERVAL_HOURS = 2
MAX_CHECKINS_PER_DAY = 3


async def should_checkin(db: AsyncSession) -> dict:
    """Verifica se deve enviar check-in agora."""
    now = now_brt()
    h = now.hour
    today = now.date().isoformat()

    if h < WORK_START_HOUR or h >= WORK_END_HOUR:
        return {"should": False, "reason": "fora_horario"}

    if LUNCH_START <= h < LUNCH_END:
        return {"should": False, "reason": "almoco"}

    # Verificar quantidade de check-ins de hoje
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    res_count = await db.execute(
        select(CheckIn).where(CheckIn.sent_at >= today_start)
    )
    today_count = len(res_count.scalars().all())
    if today_count >= MAX_CHECKINS_PER_DAY:
        return {"should": False, "reason": "maximo_diario"}

    # Verificar último check-in
    res_last = await db.execute(
        select(CheckIn).order_by(CheckIn.sent_at.desc()).limit(1)
    )
    last = res_last.scalar_one_or_none()
    if last and last.sent_at:
        from datetime import datetime
        try:
            last_dt = datetime.fromisoformat(last.sent_at)
            if (now - last_dt.replace(tzinfo=now.tzinfo if hasattr(now, 'tzinfo') else None)) < timedelta(hours=MIN_INTERVAL_HOURS):
                return {"should": False, "reason": "muito_recente"}
        except Exception:
            pass

    triggers = []

    # Trigger 1: Inatividade — nenhuma tarefa atualizada nas últimas 2h
    two_hours_ago = (now - timedelta(hours=2)).isoformat()
    res_active = await db.execute(
        select(Task).where(
            Task.status != "done",
            Task.updated_at >= two_hours_ago,
        )
    )
    if not res_active.scalars().first():
        triggers.append("inactivity_2h")

    # Trigger 2: Deadline se aproximando nas próximas 3h
    in_3h = (now + timedelta(hours=3)).date().isoformat()
    res_dl = await db.execute(
        select(Task).where(
            Task.status != "done",
            Task.deadline.isnot(None),
            Task.deadline <= in_3h,
            Task.deadline >= today,
        )
    )
    urgent = res_dl.scalars().first()
    if urgent:
        triggers.append(f"deadline:{urgent.title[:40]}")

    if triggers:
        return {"should": True, "triggers": triggers}

    return {"should": False, "reason": "sem_trigger"}


async def generate_checkin(db: AsyncSession, trigger: str) -> dict:
    """Gera mensagem de check-in e registra no banco."""
    now = now_brt()
    context = await build_context_prompt(db)

    prompt = f"""Baseado no contexto e trigger "{trigger}", gere um check-in curto.

REGRAS:
- Máximo 2-3 linhas
- Tom casual e amigável
- Se inactividade: perguntar sobre progresso
- Se deadline: alertar sem alarmar
- 3 opções de resposta rápida

CONTEXTO:
{context}

JSON:
{{
  "message": "texto",
  "options": ["opção 1", "opção 2", "opção 3"],
  "urgency": "low|medium|high"
}}"""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": "Assistente de produtividade conciso e amigável."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 200,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            parsed = json.loads(resp.json()["choices"][0]["message"]["content"])

        now_iso = now.isoformat()
        checkin = CheckIn(
            type="nudge" if "inactivity" in trigger else "reminder",
            trigger_reason=trigger,
            message_sent=parsed.get("message", ""),
            sent_at=now_iso,
            created_at=now_iso,
        )
        db.add(checkin)
        await db.commit()
        await db.refresh(checkin)

        return {
            "checkin_id": checkin.id,
            "message": parsed.get("message"),
            "options": parsed.get("options", []),
            "urgency": parsed.get("urgency", "low"),
        }

    except Exception as exc:
        logger.error(f"[checkin] erro: {exc}")
        return {"error": str(exc)}


async def record_checkin_response(db: AsyncSession, checkin_id: int, response: str) -> dict:
    res = await db.execute(select(CheckIn).where(CheckIn.id == checkin_id))
    checkin = res.scalar_one_or_none()
    if checkin:
        checkin.response = response
        checkin.response_at = now_brt().isoformat()
        await db.commit()
    return {"status": "ok", "checkin_id": checkin_id}


async def generate_eod_review(db: AsyncSession) -> dict:
    """Gera e persiste o review de fim de dia."""
    now = now_brt()
    today = now.date().isoformat()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # Verificar se já existe
    res_ex = await db.execute(select(DailyReview).where(DailyReview.date == today))
    existing = res_ex.scalar_one_or_none()
    if existing:
        return {"status": "already_generated", "ai_summary": existing.ai_summary}

    # Dados do dia
    res_done = await db.execute(
        select(Task).where(Task.status == "done", Task.completed_at >= today_start)
    )
    done_today = res_done.scalars().all()

    res_doing = await db.execute(select(Task).where(Task.status == "doing"))
    in_progress = res_doing.scalars().all()

    res_all = await db.execute(
        select(Task).where(Task.status.notin_(["done", "backlog"]))
    )
    all_active = [t for t in res_all.scalars().all() if t.updated_at < today_start]

    context = await build_context_prompt(db)

    prompt = f"""Gere um fechamento de dia conciso e motivador.

CONTEXTO:
{context}

CONCLUÍDAS HOJE: {[t.title for t in done_today] or ['Nenhuma']}
EM ANDAMENTO: {[t.title for t in in_progress]}
NÃO TOCADAS: {[t.title for t in all_active[:5]]}

JSON:
{{
  "summary": "Resumo em 2-3 frases",
  "highlight": "Principal conquista (ou mensagem encorajadora se não completou nada)",
  "suggestion_tomorrow": "Sugestão concreta para amanhã",
  "message": "Mensagem completa para WhatsApp, usando markdown do WhatsApp (*negrito*, _itálico_)"
}}"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": "Gera reviews de fim de dia concisos e úteis. Tom amigável, PT-BR."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.5,
                    "max_tokens": 400,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            parsed = json.loads(resp.json()["choices"][0]["message"]["content"])

        now_iso = now.isoformat()
        review = DailyReview(
            date=today,
            tasks_completed=json.dumps([t.id for t in done_today]),
            tasks_in_progress=json.dumps([t.id for t in in_progress]),
            tasks_not_touched=json.dumps([t.id for t in all_active[:10]]),
            ai_summary=parsed.get("summary"),
            ai_suggestions_tomorrow=parsed.get("suggestion_tomorrow"),
            created_at=now_iso,
        )
        db.add(review)
        await db.commit()

        return {"status": "generated", "review": parsed}

    except Exception as exc:
        logger.error(f"[eod_review] erro: {exc}")
        return {"error": str(exc)}
