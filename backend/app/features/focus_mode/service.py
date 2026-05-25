import json
import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.dates import now_brt
from .models import FocusModeSession
from .schemas import FocusStart, Checkpoint


def _serialize(session: FocusModeSession) -> dict:
    return {
        "id": session.id,
        "task_id": session.task_id,
        "planned_minutes": session.planned_minutes,
        "paused_seconds": session.paused_seconds or 0,
        "state": session.state,
        "checkpoints": json.loads(session.checkpoints or "[]"),
        "started_at": session.started_at,
        "paused_at": session.paused_at,
        "ended_at": session.ended_at,
        "created_at": session.created_at,
    }


async def get_active_session(db: AsyncSession) -> Optional[dict]:
    res = await db.execute(
        select(FocusModeSession).where(FocusModeSession.state.in_(("active", "paused")))
        .order_by(FocusModeSession.created_at.desc()).limit(1)
    )
    s = res.scalar_one_or_none()
    return _serialize(s) if s else None


async def start_session(db: AsyncSession, data: FocusStart) -> dict:
    # encerra qualquer sessão ainda em aberto
    res = await db.execute(
        select(FocusModeSession).where(FocusModeSession.state.in_(("active", "paused")))
    )
    now = now_brt().isoformat()
    for old in res.scalars().all():
        old.state = "aborted"
        old.ended_at = now

    cps: List[Checkpoint] = data.checkpoints or []
    if not cps:
        cps = [Checkpoint(label="Concluir tarefa", weight=100)]

    session = FocusModeSession(
        id=str(uuid.uuid4()),
        task_id=data.task_id,
        planned_minutes=data.planned_minutes,
        paused_seconds=0,
        state="active",
        checkpoints=json.dumps([c.model_dump() for c in cps]),
        started_at=now,
        created_at=now,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _serialize(session)


async def toggle_checkpoint(db: AsyncSession, session_id: str, idx: int) -> Optional[dict]:
    res = await db.execute(select(FocusModeSession).where(FocusModeSession.id == session_id))
    s = res.scalar_one_or_none()
    if not s:
        return None
    cps = json.loads(s.checkpoints or "[]")
    if idx < 0 or idx >= len(cps):
        return None
    now = now_brt().isoformat()
    cps[idx]["done"] = not cps[idx].get("done", False)
    cps[idx]["done_at"] = now if cps[idx]["done"] else None
    s.checkpoints = json.dumps(cps)
    await db.commit()
    await db.refresh(s)
    return _serialize(s)


async def pause_session(db: AsyncSession, session_id: str) -> Optional[dict]:
    res = await db.execute(select(FocusModeSession).where(FocusModeSession.id == session_id))
    s = res.scalar_one_or_none()
    if not s or s.state != "active":
        return _serialize(s) if s else None
    s.state = "paused"
    s.paused_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(s)
    return _serialize(s)


async def resume_session(db: AsyncSession, session_id: str) -> Optional[dict]:
    res = await db.execute(select(FocusModeSession).where(FocusModeSession.id == session_id))
    s = res.scalar_one_or_none()
    if not s or s.state != "paused":
        return _serialize(s) if s else None
    if s.paused_at:
        try:
            delta = (datetime.fromisoformat(now_brt().isoformat()) - datetime.fromisoformat(s.paused_at)).total_seconds()
            s.paused_seconds = (s.paused_seconds or 0) + int(max(delta, 0))
        except Exception:
            pass
    s.paused_at = None
    s.state = "active"
    await db.commit()
    await db.refresh(s)
    return _serialize(s)


async def end_session(db: AsyncSession, session_id: str, state: str = "completed") -> Optional[dict]:
    res = await db.execute(select(FocusModeSession).where(FocusModeSession.id == session_id))
    s = res.scalar_one_or_none()
    if not s:
        return None
    # se estava paused, contabiliza o tempo de pausa antes de fechar
    if s.state == "paused" and s.paused_at:
        try:
            delta = (datetime.fromisoformat(now_brt().isoformat()) - datetime.fromisoformat(s.paused_at)).total_seconds()
            s.paused_seconds = (s.paused_seconds or 0) + int(max(delta, 0))
        except Exception:
            pass
        s.paused_at = None
    s.state = state if state in ("completed", "aborted") else "completed"
    s.ended_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(s)
    return _serialize(s)


async def list_history(db: AsyncSession, task_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = select(FocusModeSession).order_by(FocusModeSession.created_at.desc()).limit(limit)
    if task_id:
        q = select(FocusModeSession).where(FocusModeSession.task_id == task_id)\
            .order_by(FocusModeSession.created_at.desc()).limit(limit)
    res = await db.execute(q)
    return [_serialize(s) for s in res.scalars().all()]
