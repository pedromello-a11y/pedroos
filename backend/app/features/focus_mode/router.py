from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from . import service
from .schemas import FocusStart, FocusEnd

router = APIRouter(prefix="/api/focus", tags=["focus"])


@router.get("/active")
async def get_active(db: AsyncSession = Depends(get_db)):
    s = await service.get_active_session(db)
    return s  # None ou objeto


@router.post("/start")
async def start(data: FocusStart, db: AsyncSession = Depends(get_db)):
    return await service.start_session(db, data)


@router.patch("/{session_id}/checkpoint/{idx}")
async def toggle_cp(session_id: str, idx: int, db: AsyncSession = Depends(get_db)):
    s = await service.toggle_checkpoint(db, session_id, idx)
    if not s:
        raise HTTPException(404, "Sessão ou checkpoint não encontrado")
    return s


@router.post("/{session_id}/pause")
async def pause(session_id: str, db: AsyncSession = Depends(get_db)):
    s = await service.pause_session(db, session_id)
    if not s:
        raise HTTPException(404, "Sessão não encontrada")
    return s


@router.post("/{session_id}/resume")
async def resume(session_id: str, db: AsyncSession = Depends(get_db)):
    s = await service.resume_session(db, session_id)
    if not s:
        raise HTTPException(404, "Sessão não encontrada")
    return s


@router.post("/{session_id}/end")
async def end(session_id: str, data: FocusEnd, db: AsyncSession = Depends(get_db)):
    s = await service.end_session(db, session_id, data.state)
    if not s:
        raise HTTPException(404, "Sessão não encontrada")
    return s


@router.get("/history")
async def history(task_id: str | None = Query(None), limit: int = 50, db: AsyncSession = Depends(get_db)):
    return await service.list_history(db, task_id=task_id, limit=limit)
