"""Engine do /foco — conduz sessão de coaching com perguntas dinâmicas."""
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.shared.dates import now_brt
from app.features.ai.models import FocusSession
from app.features.ai.context_builder import build_context_prompt
from app.config import settings


_SYSTEM_PROMPT = """Você é um coach de produtividade pessoal do Pedro (motion designer, TDAH).
Seu papel: ajudá-lo a sair da paralisia e ganhar clareza sobre o que fazer AGORA.

REGRAS:
1. Nunca dê a resposta direta. Faça perguntas que gerem auto-reflexão.
2. Cada pergunta deve ter 3-5 opções contextuais baseadas nas tarefas/situação dele.
3. SEMPRE inclua "✏️ Outra coisa" como última opção.
4. Use o contexto fornecido para gerar opções ESPECÍFICAS, não genéricas.
5. Seja empático mas direto. Sem enrolação. Tom casual.
6. Quando perceber que o usuário chegou numa decisão, confirme e encerre.
7. Máximo 7 perguntas. Se chegar em 5 sem resolução, seja mais assertivo.

FORMATO DE RESPOSTA (SEMPRE JSON válido):
{
  "message": "Texto da pergunta",
  "options": ["Opção 1", "Opção 2", "✏️ Outra coisa"],
  "is_final": false,
  "summary": null
}

Quando is_final = true:
{
  "message": "Texto de encerramento",
  "options": ["🚀 Bora!", "🔄 Ajustar"],
  "is_final": true,
  "summary": "Resumo em 1 linha: o que vai fazer e por quê"
}

CONTEXTO DO USUÁRIO:
{context}"""


async def start_focus(db: AsyncSession, source: str = "dashboard") -> dict:
    now = now_brt().isoformat()
    context = await build_context_prompt(db)

    session = FocusSession(
        started_at=now,
        status="active",
        source=source,
        messages="[]",
        created_at=now,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    response = await _call_ai(context=context, history=[], is_first=True)

    history = [{"role": "assistant", "content": response}]
    session.messages = json.dumps(history, ensure_ascii=False)
    await db.commit()

    return {"session_id": session.id, "response": response}


async def respond_focus(db: AsyncSession, session_id: int, user_text: str) -> dict:
    res = await db.execute(select(FocusSession).where(FocusSession.id == session_id))
    session = res.scalar_one_or_none()

    if not session:
        return {"error": "Sessão não encontrada"}
    if session.status != "active":
        return {"error": "Sessão já encerrada"}

    history = json.loads(session.messages or "[]")
    history.append({"role": "user", "content": user_text})

    context = await build_context_prompt(db)
    response = await _call_ai(context=context, history=history)

    history.append({"role": "assistant", "content": response})
    session.messages = json.dumps(history, ensure_ascii=False)

    if response.get("is_final"):
        session.status = "completed"
        session.ended_at = now_brt().isoformat()
        session.outcome_summary = response.get("summary")
        if session.started_at:
            from datetime import datetime
            try:
                start = datetime.fromisoformat(session.started_at)
                end = datetime.fromisoformat(session.ended_at)
                session.duration_seconds = int((end - start).total_seconds())
            except Exception:
                pass

    await db.commit()
    return {
        "session_id": session.id,
        "response": response,
        "is_complete": response.get("is_final", False),
    }


async def close_focus(db: AsyncSession, session_id: int, status: str = "abandoned") -> dict:
    res = await db.execute(select(FocusSession).where(FocusSession.id == session_id))
    session = res.scalar_one_or_none()
    if session:
        session.status = status
        session.ended_at = now_brt().isoformat()
        await db.commit()
    return {"status": status, "session_id": session_id}


async def get_focus_history(db: AsyncSession, limit: int = 10) -> list:
    res = await db.execute(
        select(FocusSession).order_by(FocusSession.created_at.desc()).limit(limit)
    )
    sessions = res.scalars().all()
    return [
        {
            "id": s.id,
            "started_at": s.started_at,
            "status": s.status,
            "outcome_summary": s.outcome_summary,
            "duration_seconds": s.duration_seconds,
            "source": s.source,
        }
        for s in sessions
    ]


async def _call_ai(context: str, history: list, is_first: bool = False) -> dict:
    import httpx

    system = _SYSTEM_PROMPT.replace("{context}", context)
    messages = [{"role": "system", "content": system}]

    for msg in history:
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        messages.append({"role": role, "content": content})

    if is_first:
        messages.append({
            "role": "user",
            "content": "Iniciar sessão de foco. Analise meu contexto e faça a primeira pergunta.",
        })

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 400,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw)

            if "message" not in parsed:
                parsed["message"] = raw
            if "options" not in parsed:
                parsed["options"] = ["✏️ Escrever livremente"]
            if "is_final" not in parsed:
                parsed["is_final"] = False

            return parsed

    except Exception as exc:
        return {
            "message": "Opa, tive um problema técnico. Tenta de novo?",
            "options": ["🔄 Tentar de novo", "❌ Encerrar sessão"],
            "is_final": False,
            "error": str(exc),
        }
