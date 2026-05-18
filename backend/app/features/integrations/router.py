"""
Integrações: Jira (Atlassian Cloud) e Google Calendar (OAuth2).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from httpx import ConnectError, TimeoutException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db import get_db
from app.features.tasks.models import Task
from app.shared.dates import now_brt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["integrations"])

GOOGLE_TOKEN_FILE = "data/google_token.json"
GOOGLE_AUTH_URL   = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL  = "https://oauth2.googleapis.com/token"
GOOGLE_CAL_URL    = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


# ─── Google OAuth helpers ─────────────────────────────────────────────────────

def _load_refresh_token() -> str:
    if os.path.exists(GOOGLE_TOKEN_FILE):
        try:
            with open(GOOGLE_TOKEN_FILE) as f:
                return json.load(f).get("refresh_token", "")
        except Exception:
            pass
    return settings.google_refresh_token


def _save_refresh_token(token: str):
    os.makedirs("data", exist_ok=True)
    with open(GOOGLE_TOKEN_FILE, "w") as f:
        json.dump({"refresh_token": token}, f)


async def _get_access_token() -> str | None:
    refresh_token = _load_refresh_token()
    if not refresh_token or not settings.google_client_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id":     settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            })
        if res.status_code == 200:
            return res.json().get("access_token")
        log.warning("[google] refresh failed: %s %s", res.status_code, res.text[:200])
    except Exception as e:
        log.warning("[google] refresh error: %r", e)
    return None


# ─── OAuth2 flow endpoints ────────────────────────────────────────────────────

@router.get("/auth/google")
async def google_auth_start():
    """Retorna a URL de autorização do Google."""
    if not settings.google_client_id:
        return {"error": "GOOGLE_CLIENT_ID não configurado"}
    params = {
        "client_id":     settings.google_client_id,
        "redirect_uri":  settings.google_redirect_uri,
        "scope":         "https://www.googleapis.com/auth/calendar.events",
        "response_type": "code",
        "access_type":   "offline",
        "prompt":        "consent",
    }
    return {"url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@router.get("/auth/google/callback")
async def google_auth_callback(code: str = "", error: str = ""):
    """Recebe o callback do Google, troca o code por tokens e persiste o refresh_token."""
    if error:
        return HTMLResponse(f"<h1>❌ Erro: {error}</h1>")
    if not code:
        return HTMLResponse("<h1>❌ Código ausente</h1>")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(GOOGLE_TOKEN_URL, data={
                "code":          code,
                "client_id":     settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri":  settings.google_redirect_uri,
                "grant_type":    "authorization_code",
            })
    except Exception as e:
        return HTMLResponse(f"<h1>❌ Falha na requisição: {e}</h1>")

    if res.status_code != 200:
        return HTMLResponse(f"<h1>❌ Erro {res.status_code}</h1><pre>{res.text}</pre>")

    tokens = res.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        return HTMLResponse("<h1>⚠️ Google não retornou refresh_token. Revogue o acesso em myaccount.google.com/permissions e tente de novo.</h1>")

    _save_refresh_token(refresh)
    log.info("[google] refresh_token salvo em %s", GOOGLE_TOKEN_FILE)

    return HTMLResponse("""
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><title>Conectado</title>
<style>body{background:#06090F;color:#DDE4EF;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:16px}
h1{color:#22C55E;font-size:2rem}p{color:#64748B}</style></head>
<body><h1>✅ Google Calendar conectado!</h1><p>Pode fechar esta aba e voltar ao dashboard.</p></body>
</html>""")


@router.get("/auth/google/status")
async def google_auth_status():
    """Verifica se há um refresh token válido."""
    has_token = bool(_load_refresh_token() and settings.google_client_id)
    return {"authenticated": has_token}


# ─── Google Calendar API ──────────────────────────────────────────────────────

async def _meetings_from_api(access_token: str, target_date: str | None = None):
    tz = ZoneInfo(settings.timezone)
    if target_date:
        from datetime import date as _date
        d = _date.fromisoformat(target_date)
        base = datetime(d.year, d.month, d.day, tzinfo=tz)
    else:
        base = datetime.now(tz)
    day_start = base.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    day_end   = base.replace(hour=23, minute=59, second=59, microsecond=999999)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                GOOGLE_CAL_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "timeMin":            day_start.isoformat(),
                    "timeMax":            day_end.isoformat(),
                    "singleEvents":       "true",
                    "orderBy":            "startTime",
                    "maxResults":         20,
                    "conferenceDataVersion": "1",
                },
            )
    except (ConnectError, TimeoutException):
        return {"connected": False, "events": [], "error": "offline"}
    except Exception as e:
        log.warning("[google-cal] fetch error: %r", e)
        return {"connected": False, "events": [], "error": "fetch_failed"}

    if res.status_code == 401:
        return {"connected": False, "events": [], "error": "token_expired"}
    if res.status_code != 200:
        return {"connected": False, "events": [], "error": f"http_{res.status_code}"}

    events = []
    for item in res.json().get("items", []):
        start = item.get("start", {})
        dt_str = start.get("dateTime")
        if not dt_str:
            continue  # all-day

        local_dt = datetime.fromisoformat(dt_str).astimezone(tz)

        end_dt_str = item.get("end", {}).get("dateTime")
        end_time = datetime.fromisoformat(end_dt_str).astimezone(tz).strftime("%H:%M") if end_dt_str else None

        # pega link do Google Meet ou htmlLink como fallback
        link = ""
        for ep in (item.get("conferenceData") or {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                link = ep.get("uri", "")
                break
        if not link:
            link = item.get("htmlLink", "")

        events.append({
            "id":         item.get("id", ""),
            "title":      item.get("summary") or "(sem título)",
            "start_time": local_dt.strftime("%H:%M"),
            "end_time":   end_time,
            "location":   item.get("location") or "",
            "link":       link,
        })

    return {"connected": True, "events": events}


async def _meetings_from_ics(ics_url: str = "", target_date: str | None = None):
    """Fallback: ICS público (títulos aparecem como Busy em contas Workspace)."""
    if not ics_url:
        ics_url = settings.google_calendar_ics_url
    if not ics_url:
        return {"connected": False, "events": []}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(ics_url)
    except (ConnectError, TimeoutException):
        return {"connected": False, "events": [], "error": "offline"}
    except Exception as e:
        log.warning("[calendar] fetch failed: %s", e)
        return {"connected": False, "events": [], "error": "fetch_failed"}

    if res.status_code != 200:
        return {"connected": False, "events": [], "error": f"http_{res.status_code}"}

    try:
        from icalendar import Calendar
        import recurring_ical_events
    except ImportError:
        return {"connected": False, "events": [], "error": "missing_icalendar_lib"}

    tz = ZoneInfo(settings.timezone)
    if target_date:
        from datetime import date as _date
        d = _date.fromisoformat(target_date)
        base = datetime(d.year, d.month, d.day, tzinfo=tz)
    else:
        base = datetime.now(tz)
    day_start = base.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    day_end   = base.replace(hour=23, minute=59, second=59, microsecond=999999)

    try:
        cal = Calendar.from_ical(res.content)
        occurrences = recurring_ical_events.of(cal).between(day_start, day_end)
    except Exception as e:
        log.warning("[calendar] parse failed: %s", e)
        return {"connected": True, "events": [], "error": "parse_failed"}

    events = []
    for ev in occurrences:
        dt = ev.get("dtstart").dt
        if not isinstance(dt, datetime):
            continue
        local_dt = dt.astimezone(tz)
        end_dt = ev.get("dtend")
        end_time = None
        if end_dt:
            end_raw = end_dt.dt
            if isinstance(end_raw, datetime):
                end_time = end_raw.astimezone(tz).strftime("%H:%M")
        events.append({
            "id":         f"{ev.get('uid', '')}-{local_dt.strftime('%Y%m%d%H%M')}",
            "title":      str(ev.get("summary", "")),
            "start_time": local_dt.strftime("%H:%M"),
            "end_time":   end_time,
            "location":   str(ev.get("location") or ""),
            "link":       str(ev.get("url") or ""),
        })

    events.sort(key=lambda e: e["start_time"])
    return {"connected": True, "events": events}


@router.get("/meetings/today")
async def meetings_today(date: str | None = None):
    access_token = await _get_access_token()
    if access_token:
        return await _meetings_from_api(access_token, target_date=date)
    return await _meetings_from_ics(target_date=date)


@router.get("/meetings/personal")
async def meetings_personal(date: str | None = None):
    """Agenda pessoal via ICS privado."""
    ics_url = settings.personal_calendar_ics_url
    if not ics_url:
        return {"connected": False, "events": []}
    return await _meetings_from_ics(ics_url, target_date=date)


# ─── Google Calendar — criar evento ──────────────────────────────────────────

async def create_personal_event(title: str, event_date: str, event_time: str, duration_hours: float = 1.0) -> dict:
    """Cria evento no calendário Particular do Google (PERSONAL_CALENDAR_ID)."""
    access_token = await _get_access_token()
    if not access_token:
        return {"ok": False, "error": "not_authenticated"}

    calendar_id = settings.personal_calendar_id
    if not calendar_id:
        return {"ok": False, "error": "PERSONAL_CALENDAR_ID not configured"}

    tz = settings.timezone
    try:
        start_dt = datetime.fromisoformat(f"{event_date}T{event_time}:00")
        end_dt = start_dt + timedelta(hours=duration_hours)
    except ValueError as e:
        return {"ok": False, "error": f"invalid_datetime: {e}"}

    event_body = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
        "end":   {"dateTime": end_dt.isoformat(),   "timeZone": tz},
    }

    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=event_body,
            )
    except Exception as e:
        log.warning("[gcal-create] request error: %r", e)
        return {"ok": False, "error": "request_failed"}

    if res.status_code in (200, 201):
        data = res.json()
        log.info("[gcal-create] evento criado: %s", data.get("htmlLink"))
        return {"ok": True, "event_id": data.get("id"), "link": data.get("htmlLink")}

    log.warning("[gcal-create] %s %s", res.status_code, res.text[:200])
    return {"ok": False, "error": f"http_{res.status_code}"}


# ─── Pending Calendar Events ─────────────────────────────────────────────────

class PendingEventUpdate(BaseModel):
    title: Optional[str] = None
    event_date: Optional[str] = None
    event_time: Optional[str] = None
    duration_hours: Optional[float] = None


async def _create_pending_event(db: AsyncSession, title: str, event_date: str, event_time: str, duration_hours: float = 1.0):
    from app.features.integrations.models import PendingCalendarEvent
    ev = PendingCalendarEvent(
        id=str(uuid.uuid4()),
        title=title,
        event_date=event_date,
        event_time=event_time,
        duration_hours=duration_hours,
        created_at=now_brt().isoformat(),
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return ev


@router.get("/calendar/pending")
async def list_pending_events(db: AsyncSession = Depends(get_db)):
    from app.features.integrations.models import PendingCalendarEvent
    result = await db.execute(select(PendingCalendarEvent).order_by(PendingCalendarEvent.created_at))
    return [
        {"id": e.id, "title": e.title, "event_date": e.event_date,
         "event_time": e.event_time, "duration_hours": e.duration_hours}
        for e in result.scalars().all()
    ]


@router.patch("/calendar/pending/{event_id}")
async def update_pending_event(event_id: str, data: PendingEventUpdate, db: AsyncSession = Depends(get_db)):
    from app.features.integrations.models import PendingCalendarEvent
    result = await db.execute(select(PendingCalendarEvent).where(PendingCalendarEvent.id == event_id))
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ev, field, value)
    await db.commit()
    await db.refresh(ev)
    return {"id": ev.id, "title": ev.title, "event_date": ev.event_date,
            "event_time": ev.event_time, "duration_hours": ev.duration_hours}


@router.post("/calendar/pending/{event_id}/confirm")
async def confirm_pending_event(event_id: str, db: AsyncSession = Depends(get_db)):
    from app.features.integrations.models import PendingCalendarEvent
    result = await db.execute(select(PendingCalendarEvent).where(PendingCalendarEvent.id == event_id))
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Evento não encontrado")

    gcal = await create_personal_event(ev.title, ev.event_date, ev.event_time, ev.duration_hours)
    if not gcal.get("ok"):
        raise HTTPException(status_code=502, detail=gcal.get("error", "gcal_error"))

    await db.delete(ev)
    await db.commit()
    return {"ok": True, "link": gcal.get("link")}


@router.delete("/calendar/pending/{event_id}", status_code=204)
async def delete_pending_event(event_id: str, db: AsyncSession = Depends(get_db)):
    from app.features.integrations.models import PendingCalendarEvent
    result = await db.execute(select(PendingCalendarEvent).where(PendingCalendarEvent.id == event_id))
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    await db.delete(ev)
    await db.commit()


# ─── JIRA ─────────────────────────────────────────────────────────────────────

@router.get("/jira/active")
async def jira_active():
    base  = settings.jira_base_url.rstrip("/")
    email = settings.jira_email
    token = settings.jira_api_token
    jql   = settings.jira_jql

    if not (base and email and token):
        return {"connected": False, "issues": []}

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, http2=False) as client:
            res = await client.post(
                f"{base}/rest/api/3/search/jql",
                json={
                    "jql":       jql,
                    "fields":    ["summary", "status", "priority", "issuetype", "updated", "duedate", "description", "customfield_18234"],
                    "maxResults": 20,
                },
                headers={
                    "Authorization":  f"Basic {auth}",
                    "Accept":         "application/json",
                    "Content-Type":   "application/json",
                    "User-Agent":     "PedroOS/1.0",
                },
            )
    except (ConnectError, TimeoutException):
        return {"connected": False, "issues": [], "error": "offline"}
    except Exception as e:
        log.warning("[jira] request failed: %r", e)
        return {"connected": False, "issues": [], "error": f"request_failed: {type(e).__name__}: {repr(e)[:300]}"}

    if res.status_code != 200:
        log.warning("[jira] %s %s", res.status_code, res.text[:200])
        return {"connected": False, "issues": [], "error": f"http_{res.status_code}"}

    issues = []
    for it in res.json().get("issues", []):
        f = it.get("fields", {})
        issues.append({
            "key":         it.get("key"),
            "summary":     f.get("summary", ""),
            "status":      (f.get("status")    or {}).get("name", ""),
            "priority":    (f.get("priority")  or {}).get("name", ""),
            "type":        (f.get("issuetype") or {}).get("name", ""),
            "due_date":    f.get("duedate"),
            "description": _adf_to_text(f.get("customfield_18234") or f.get("description")),
            "url":         f"{base}/browse/{it.get('key')}",
        })

    return {"connected": True, "issues": issues}


@router.post("/jira/sync")
async def jira_sync(db: AsyncSession = Depends(get_db)):
    """Verifica no Jira se tarefas linkadas foram finalizadas e atualiza o status local."""
    base  = settings.jira_base_url.rstrip("/")
    email = settings.jira_email
    token = settings.jira_api_token

    if not (base and email and token):
        return {"synced": [], "error": "jira_not_configured"}

    result = await db.execute(
        select(Task).where(
            Task.jira_key.isnot(None),
            Task.status != "done",
        )
    )
    tasks = result.scalars().all()
    if not tasks:
        return {"synced": []}

    keys = [t.jira_key for t in tasks]
    jql = f"key in ({', '.join(keys)})"
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, http2=False) as client:
            res = await client.post(
                f"{base}/rest/api/3/search/jql",
                json={"jql": jql, "fields": ["status"], "maxResults": 100},
                headers={
                    "Authorization": f"Basic {auth}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "PedroOS/1.0",
                },
            )
    except Exception as e:
        log.warning("[jira/sync] request failed: %r", e)
        return {"synced": [], "error": repr(e)}

    if res.status_code != 200:
        return {"synced": [], "error": f"http_{res.status_code}"}

    done_keys = {
        it["key"]
        for it in res.json().get("issues", [])
        if (it.get("fields", {}).get("status", {}).get("statusCategory", {}).get("key") == "done")
    }

    synced = []
    now = now_brt().isoformat()
    task_map = {t.jira_key: t for t in tasks}
    for key in done_keys:
        if key in task_map:
            t = task_map[key]
            t.status = "done"
            t.completed_at = now
            t.updated_at = now
            synced.append({"id": t.id, "short_id": t.short_id, "title": t.title, "jira_key": key})

    if synced:
        await db.commit()
        log.info("[jira/sync] %d tarefas finalizadas: %s", len(synced), [s["jira_key"] for s in synced])

    return {"synced": synced}


def _adf_to_text(node, depth=0) -> str:
    """Converte Atlassian Document Format (ADF) para texto plano."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    parts = []
    ntype = node.get("type", "")
    text = node.get("text")
    if text:
        parts.append(text)
    for child in node.get("content", []):
        parts.append(_adf_to_text(child, depth + 1))
    result = "".join(parts).strip()
    if ntype in ("paragraph", "heading", "listItem") and depth > 0:
        result = result + "\n"
    return result
