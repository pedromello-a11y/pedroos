"""Engine de memórias — detecta padrões e aprende sobre o usuário."""
import json
import logging
from datetime import timedelta
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.shared.dates import now_brt
from app.features.ai.models import AIMemory, FocusSession, CheckIn
from app.features.tasks.models import Task
from app.config import settings

logger = logging.getLogger(__name__)


async def get_memories(db: AsyncSession) -> list:
    res = await db.execute(
        select(AIMemory)
        .where(AIMemory.is_active == True, AIMemory.confidence >= 0.3)
        .order_by(AIMemory.confidence.desc())
        .limit(15)
    )
    return [
        {
            "id": m.id,
            "category": m.category,
            "content": m.content,
            "confidence": m.confidence,
        }
        for m in res.scalars().all()
    ]


async def add_memory(db: AsyncSession, content: str, category: str = "preference") -> dict:
    now = now_brt().isoformat()
    memory = AIMemory(
        category=category,
        content=content,
        confidence=0.9,
        evidence_count=1,
        last_seen=now,
        is_active=True,
        extra="{}",
        created_at=now,
        updated_at=now,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return {"id": memory.id, "content": content, "category": category}


async def delete_memory(db: AsyncSession, memory_id: int) -> dict:
    res = await db.execute(select(AIMemory).where(AIMemory.id == memory_id))
    memory = res.scalar_one_or_none()
    if memory:
        memory.is_active = False
        memory.updated_at = now_brt().isoformat()
        await db.commit()
    return {"status": "deleted"}


async def analyze_patterns(db: AsyncSession) -> dict:
    """Analisa padrões dos últimos 7 dias e atualiza memórias."""
    seven_days_ago = (now_brt() - timedelta(days=7)).isoformat()

    # Coletar dados
    res_done = await db.execute(
        select(Task).where(Task.status == "done", Task.updated_at >= seven_days_ago)
    )
    done_tasks = res_done.scalars().all()

    res_focus = await db.execute(
        select(FocusSession).where(FocusSession.created_at >= seven_days_ago)
    )
    focus_sessions = res_focus.scalars().all()

    res_checkins = await db.execute(
        select(CheckIn).where(CheckIn.sent_at >= seven_days_ago)
    )
    checkins = res_checkins.scalars().all()

    res_mem = await db.execute(select(AIMemory).where(AIMemory.is_active == True))
    current_memories = res_mem.scalars().all()

    completion_data = [
        {
            "title": t.title,
            "project": t.project_slug,
            "completed_at": t.completed_at,
            "priority": t.priority,
        }
        for t in done_tasks
    ]

    focus_data = [
        {
            "status": s.status,
            "duration_seconds": s.duration_seconds,
            "outcome": s.outcome_summary,
            "started_at": s.started_at,
        }
        for s in focus_sessions
    ]

    checkin_data = [
        {
            "trigger": c.trigger_reason,
            "responded": c.response is not None,
            "sent_at": c.sent_at,
        }
        for c in checkins
    ]

    mem_data = [{"id": m.id, "content": m.content, "confidence": m.confidence} for m in current_memories]

    prompt = f"""Analise os dados de produtividade dos últimos 7 dias do Pedro.

TAREFAS CONCLUÍDAS: {json.dumps(completion_data, ensure_ascii=False, default=str)}

SESSÕES DE FOCO: {json.dumps(focus_data, ensure_ascii=False, default=str)}

CHECK-INS: {json.dumps(checkin_data, ensure_ascii=False, default=str)}

MEMÓRIAS EXISTENTES: {json.dumps(mem_data, ensure_ascii=False)}

Identifique padrões de horário, tipos de tarefa adiadas, gatilhos de paralisia, etc.

JSON:
{{
  "new_patterns": [
    {{
      "category": "productivity|preference|pattern|blocker",
      "content": "descrição do padrão em 1 frase",
      "confidence": 0.5
    }}
  ],
  "reinforce": [
    {{"memory_id": 1, "new_confidence": 0.8}}
  ],
  "weaken": [
    {{"memory_id": 2, "new_confidence": 0.2}}
  ]
}}"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": "Analista de padrões comportamentais. PT-BR."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 600,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            parsed = json.loads(resp.json()["choices"][0]["message"]["content"])

        now_iso = now_brt().isoformat()

        for pattern in parsed.get("new_patterns", []):
            # Evitar duplicatas próximas
            needle = pattern["content"][:30].lower()
            res_dup = await db.execute(
                select(AIMemory).where(AIMemory.content.ilike(f"%{needle}%"), AIMemory.is_active == True)
            )
            if not res_dup.scalar_one_or_none():
                db.add(AIMemory(
                    category=pattern["category"],
                    content=pattern["content"],
                    confidence=pattern.get("confidence", 0.5),
                    evidence_count=1,
                    last_seen=now_iso,
                    is_active=True,
                    extra="{}",
                    created_at=now_iso,
                    updated_at=now_iso,
                ))

        for item in parsed.get("reinforce", []):
            res_m = await db.execute(select(AIMemory).where(AIMemory.id == item["memory_id"]))
            m = res_m.scalar_one_or_none()
            if m:
                m.confidence = min(1.0, item["new_confidence"])
                m.evidence_count += 1
                m.last_seen = now_iso
                m.updated_at = now_iso

        for item in parsed.get("weaken", []):
            res_m = await db.execute(select(AIMemory).where(AIMemory.id == item["memory_id"]))
            m = res_m.scalar_one_or_none()
            if m:
                m.confidence = max(0.0, item["new_confidence"])
                if m.confidence < 0.1:
                    m.is_active = False
                m.updated_at = now_iso

        await db.commit()
        return {"status": "analyzed", "result": parsed}

    except Exception as exc:
        logger.error(f"[memory] analyze_patterns erro: {exc}")
        return {"error": str(exc)}
