"""Engine do /dump — texto livre → itens organizados → tarefas."""
import json
import uuid
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.shared.dates import now_brt
from app.features.ai.models import BrainDump
from app.features.tasks.models import Task
from app.features.tasks.schemas import TaskCreate
from app.features.tasks.service import create_task
from app.config import settings


_SYSTEM_PROMPT = """Você é um assistente de organização pessoal do Pedro (motion designer, TDAH).
Ele vai mandar um "brain dump" — texto livre com tudo que está na cabeça dele.

Seu trabalho:
1. Separar e categorizar cada item
2. Identificar se algum item se relaciona com tarefas existentes

TAREFAS EXISTENTES:
{existing_tasks}

RESPONDA EM JSON:
{
  "items": [
    {
      "original_text": "texto exato",
      "type": "task|note|reminder|idea",
      "title": "título limpo, verbo no infinitivo, máx 60 chars",
      "priority": "p1|p2|p3|backlog",
      "action": "create_task|update_task|just_note",
      "related_task_id": null,
      "related_task_title": null,
      "suggested_status": "queued|backlog",
      "deadline_hint": null
    }
  ],
  "summary": "Resumo de 1 linha",
  "immediate_actions": ["ação rápida 1", "ação rápida 2"],
  "message_to_user": "Mensagem amigável confirmando o que entendeu"
}"""


async def process_dump(db: AsyncSession, raw_text: str, source: str = "whatsapp") -> dict:
    now = now_brt().isoformat()

    res = await db.execute(select(Task).where(Task.status != "done"))
    existing_tasks = res.scalars().all()
    tasks_str = "\n".join(
        f"- [ID:{t.id[:8]}] {t.title} ({t.status})" for t in existing_tasks
    )

    dump = BrainDump(
        raw_input=raw_text,
        source=source,
        status="pending",
        created_at=now,
    )
    db.add(dump)
    await db.commit()
    await db.refresh(dump)

    system = _SYSTEM_PROMPT.replace("{existing_tasks}", tasks_str or "Nenhuma")

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": raw_text},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw)

        dump.parsed_items = json.dumps(parsed.get("items", []), ensure_ascii=False)
        dump.status = "processed"
        await db.commit()

        return {"dump_id": dump.id, "parsed": parsed, "status": "processed"}

    except Exception as exc:
        dump.status = "error"
        await db.commit()
        return {"dump_id": dump.id, "error": str(exc), "status": "error"}


async def confirm_dump(db: AsyncSession, dump_id: int, confirmed_items: list | None = None) -> dict:
    res = await db.execute(select(BrainDump).where(BrainDump.id == dump_id))
    dump = res.scalar_one_or_none()
    if not dump:
        return {"error": "Dump não encontrado"}

    items = confirmed_items or json.loads(dump.parsed_items or "[]")
    tasks_created_ids = []
    tasks_updated_ids = []
    now = now_brt().isoformat()

    _PRIO_MAP = {"high": "p1", "p1": "p1", "medium": "p2", "p2": "p2", "low": "p3", "p3": "p3", "backlog": "backlog"}
    _STATUS_OK = {"queued", "backlog", "todo"}

    for item in items:
        if item.get("action") == "create_task":
            raw_prio = item.get("priority", "p3")
            prio = _PRIO_MAP.get(str(raw_prio).lower(), "p3")
            raw_status = item.get("suggested_status", "backlog")
            status = raw_status if raw_status in _STATUS_OK else "backlog"

            new_task = TaskCreate(
                title=item["title"],
                status=status,
                priority=prio,
                reviewed=0,
                raw_input=item.get("original_text"),
                source="whatsapp",
            )
            created = await create_task(db, new_task)
            tasks_created_ids.append(created.id)

        elif item.get("action") == "update_task" and item.get("related_task_id"):
            short = item["related_task_id"]
            res2 = await db.execute(select(Task).where(Task.id.startswith(short)))
            task = res2.scalar_one_or_none()
            if task:
                # Append context to description
                note = item.get("original_text", "")
                if note:
                    current = task.description or ""
                    task.description = f"{current}\n[dump] {note}".strip()
                    task.updated_at = now
                tasks_updated_ids.append(task.id)

    dump.tasks_created = json.dumps(tasks_created_ids, ensure_ascii=False)
    dump.tasks_updated = json.dumps(tasks_updated_ids, ensure_ascii=False)
    dump.status = "confirmed"
    await db.commit()

    return {
        "dump_id": dump_id,
        "tasks_created": len(tasks_created_ids),
        "tasks_updated": len(tasks_updated_ids),
        "status": "confirmed",
    }
