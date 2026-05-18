import re
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.features.tasks.models import WaProcessed
from app.features.tasks.service import create_task
from app.features.tasks.schemas import TaskCreate
from app.features.projects.service import list_projects
from app.features.whatsapp.commands import handle_command
from app.features.whatsapp.ai_parser import parse_message, _parse_date
from app.features.whatsapp.sender import send_whatsapp
from app.features.integrations.router import _create_pending_event
from app.features.notes.service import create_note
from app.features.notes.schemas import NoteCreate
from app.features.tasks.sse import broadcast
from app.shared.dates import now_brt
from app.shared.responses import format_task_created

_DUMP_TAGS = {
    "ideia": "ideia",
    "decisão": "decisão",
    "decisao": "decisão",
    "referência": "referência",
    "referencia": "referência",
    "reunião": "reunião",
    "reuniao": "reunião",
}

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

_MONTHS_PT = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}


def _parse_event_text(text: str) -> dict | None:
    """Extrai título, data e hora de textos como 'Natação sexta 20h' ou 'Almoço amanhã 12:30'."""
    working = text.strip()
    lower = working.lower()

    # --- hora: "20h", "20h30", "20:30", "às 9h" ---
    time_match = re.search(r"\b(\d{1,2})h(\d{2})?\b|\b(\d{1,2}):(\d{2})\b", lower)
    if not time_match:
        return None

    if time_match.group(1) is not None:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
    else:
        hour = int(time_match.group(3))
        minute = int(time_match.group(4))

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    time_str = f"{hour:02d}:{minute:02d}"
    time_token = time_match.group(0)

    # --- data: dia-da-semana, "amanhã", "hoje", "dia 15", "15/05", "15 mai" ---
    # Remove token de hora para não confundir o parser de data
    without_time = re.sub(re.escape(time_token), "", lower).strip()

    event_date: date | None = None
    date_token_found: str | None = None

    # Tenta "15 mai" / "dia 15 mai"
    m = re.search(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS_PT.keys()) + r")\b", without_time)
    if m:
        from datetime import date as _date
        today = _parse_date("hoje") or _date.today()
        day = int(m.group(1))
        month = _MONTHS_PT[m.group(2)]
        year = today.year
        try:
            candidate = _date(year, month, day)
            if candidate < today:
                candidate = _date(year + 1, month, day)
            event_date = candidate
            date_token_found = m.group(0)
        except ValueError:
            pass

    if not event_date:
        # Tenta tokens isolados: dia-da-semana, "amanhã", "hoje", "dd/mm"
        for token in re.findall(r"\S+", without_time):
            d = _parse_date(token)
            if d:
                event_date = d
                date_token_found = token
                break

    if not event_date:
        return None

    # --- título: texto restante após remover hora e data ---
    title = lower
    title = re.sub(re.escape(time_token), "", title).strip()
    if date_token_found:
        title = re.sub(re.escape(date_token_found), "", title).strip()
    title = re.sub(r"\bàs?\b", "", title).strip()
    title = re.sub(r"\s{2,}", " ", title).strip(" ,-")

    # Preserva capitalização original removendo os mesmos tokens do texto original
    title_orig = working
    title_orig = re.sub(re.escape(time_token), "", title_orig, flags=re.IGNORECASE).strip()
    if date_token_found:
        title_orig = re.sub(re.escape(date_token_found), "", title_orig, flags=re.IGNORECASE).strip()
    title_orig = re.sub(r"\bàs?\b", "", title_orig, flags=re.IGNORECASE).strip()
    title_orig = re.sub(r"\s{2,}", " ", title_orig).strip(" ,-")

    if not title_orig:
        return None

    return {
        "title": title_orig[:80],
        "date": event_date.isoformat(),
        "time": time_str,
        "date_display": event_date.strftime("%d/%m"),
    }




@router.post("/webhook")
async def whatsapp_webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    message_id = payload.get("message_id", "")
    from_jid = payload.get("from") or payload.get("from_jid", "")
    text = (payload.get("text") or "").strip()

    if not text or not message_id:
        return {"ok": False, "reason": "missing fields"}

    # idempotency
    existing = await db.execute(
        select(WaProcessed).where(WaProcessed.message_id == message_id)
    )
    if existing.scalar_one_or_none():
        return {"ok": True, "duplicate": True}

    wa = WaProcessed(message_id=message_id, processed_at=now_brt().isoformat())
    db.add(wa)
    await db.commit()

    projects = await list_projects(db, active=1)

    # ── dump: cria nota ──────────────────────────────────────────────────────
    if text.lower().startswith("dump"):
        # Formats: "dump: texto"  |  "dump fire: texto"  |  "dump ideia: texto"
        rest = text[4:].strip()          # remove "dump"
        project_slug = None
        tag = None

        if rest.startswith(":"):
            # plain dump: texto
            content = rest[1:].strip()
        else:
            # may have a modifier: " fire: texto" or " ideia: texto"
            colon_idx = rest.find(":")
            if colon_idx != -1:
                modifier = rest[:colon_idx].strip().lower()
                content = rest[colon_idx + 1:].strip()
                # check if modifier is a tag keyword
                if modifier in _DUMP_TAGS:
                    tag = _DUMP_TAGS[modifier]
                else:
                    # treat modifier as project slug
                    project_slug = modifier
            else:
                content = rest.strip()

        if content:
            note_data = NoteCreate(
                title=content[:80],
                content=content,
                raw_input=text,
                project_slug=project_slug,
                tag=tag,
                source="whatsapp",
            )
            note = await create_note(db, note_data)
            tag_str = f" [{note.tag}]" if note.tag else ""
            proj_str = f" → {note.project_slug}" if note.project_slug else ""
            response_text = f"📝 Nota salva{tag_str}{proj_str}\n_{content[:60]}_"
        else:
            response_text = "❌ Formato: *dump: texto* ou *dump ideia: texto* ou *dump fire: texto*"

        if from_jid:
            await send_whatsapp(from_jid, response_text)
        return {"ok": True, "response": response_text}

    # ── evento: cria no Google Calendar Particular ──────────────────────────
    if text.lower().startswith("evento:"):
        event_text = text[len("evento:"):].strip()
        parsed_ev = _parse_event_text(event_text)
        if parsed_ev:
            await _create_pending_event(
                db=db,
                title=parsed_ev["title"],
                event_date=parsed_ev["date"],
                event_time=parsed_ev["time"],
            )
            response_text = (
                f"📅 *{parsed_ev['title']}* — {parsed_ev['date_display']} às {parsed_ev['time']}\n"
                f"Confirme no dashboard antes de ir pra agenda."
            )
        else:
            response_text = "❌ Não entendi. Tente: *evento: Título data hora* (ex: evento: Natação sexta 20h)"

        if from_jid:
            await send_whatsapp(from_jid, response_text)
        return {"ok": True, "response": response_text}

    is_command, response_text = await handle_command(text, db, projects)

    if not is_command:
        forced_project = None
        if text.lower().startswith("pessoal:"):
            text = text[len("pessoal:"):].strip()
            forced_project = "pessoal"

        parsed = await parse_message(text, projects)

        task_data = TaskCreate(
            title=parsed.get("title") or text[:60],
            raw_input=text,
            project_slug=forced_project or parsed.get("project_slug") or None,
            deadline=parsed.get("deadline") or None,
            priority=parsed.get("priority") or "p3",
            reviewed=0,
            source="whatsapp",
        )
        task = await create_task(db, task_data)
        broadcast("inbox", task.short_id)
        project_name = None
        if task.project_slug:
            proj = next((p for p in projects if p.slug == task.project_slug), None)
            project_name = proj.name if proj else task.project_slug
        response_text = format_task_created(task, project_name)

    if response_text and from_jid:
        await send_whatsapp(from_jid, response_text)

    return {"ok": True, "response": response_text}


@router.get("/status")
async def whatsapp_status():
    """Retorna status de conexão e QR code atual (JSON) — proxy para o gateway."""
    from app.config import settings
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.wa_gateway_url}/qr")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {"connected": False, "qr": None}


@router.post("/reset")
async def whatsapp_reset():
    """Deleta sessão e força novo QR — proxy para o gateway."""
    from app.config import settings
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{settings.wa_gateway_url}/reset")
            return resp.json()
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


@router.get("/qr", response_class=HTMLResponse)
async def whatsapp_qr():
    """Página HTML com o QR code para escanear."""
    from app.config import settings
    from urllib.parse import quote

    qr_data = None
    connected = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.wa_gateway_url}/qr")
            if resp.status_code == 200:
                data = resp.json()
                connected = data.get("connected", False)
                qr_data = data.get("qr")
    except Exception:
        pass

    if connected:
        return HTMLResponse(
            "<!DOCTYPE html><html><head><title>Pedro OS — WhatsApp</title></head>"
            '<body style="font-family:sans-serif;text-align:center;padding:40px;background:#111;color:#fff">'
            "<h2>✅ WhatsApp conectado!</h2>"
            "<p style='color:#aaa'>Sessão ativa. Pode fechar esta aba.</p>"
            "</body></html>"
        )

    if not qr_data:
        return HTMLResponse(
            "<!DOCTYPE html><html><head>"
            '<meta http-equiv="refresh" content="10">'
            "</head>"
            '<body style="font-family:sans-serif;text-align:center;padding:40px;background:#111;color:#fff">'
            "<h2>QR code ainda não gerado.</h2>"
            "<p>Aguarde alguns segundos e recarregue.</p>"
            "</body></html>"
        )

    img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(qr_data)}"
    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Pedro OS — WhatsApp QR</title>
  <meta http-equiv="refresh" content="30">
</head>
<body style="font-family:sans-serif;text-align:center;padding:40px;background:#111;color:#fff">
  <h2>Escaneie com o WhatsApp</h2>
  <img src="{img_url}" style="border:8px solid #fff;border-radius:8px;margin:16px auto;display:block;background:#fff"/>
  <p style="color:#aaa">Recarregue após escanear para confirmar conexão.</p>
</body>
</html>"""
    return HTMLResponse(html)
