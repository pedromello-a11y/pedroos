"""Rotas da API para o sistema de IA."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.features.ai import focus_engine, dump_engine, checkin_engine, memory_engine

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class StartFocusReq(BaseModel):
    source: str = "dashboard"


class FocusRespondReq(BaseModel):
    session_id: int
    response: str


class DumpReq(BaseModel):
    text: str
    source: str = "dashboard"


class DumpConfirmReq(BaseModel):
    dump_id: int
    confirmed_items: Optional[list] = None


class CheckInRespondReq(BaseModel):
    checkin_id: int
    response: str


class MemoryReq(BaseModel):
    content: str
    category: str = "preference"


# ─── Focus ──────────────────────────────────────────────────────────────────

@router.post("/focus/start")
async def start_focus(req: StartFocusReq, db: AsyncSession = Depends(get_db)):
    return await focus_engine.start_focus(db, source=req.source)


@router.post("/focus/respond")
async def respond_focus(req: FocusRespondReq, db: AsyncSession = Depends(get_db)):
    result = await focus_engine.respond_focus(db, req.session_id, req.response)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/focus/confirm/{session_id}")
async def confirm_focus(session_id: int, db: AsyncSession = Depends(get_db)):
    return await focus_engine.close_focus(db, session_id, status="completed")


@router.post("/focus/abandon/{session_id}")
async def abandon_focus(session_id: int, db: AsyncSession = Depends(get_db)):
    return await focus_engine.close_focus(db, session_id, status="abandoned")


@router.get("/focus/history")
async def focus_history(limit: int = 10, db: AsyncSession = Depends(get_db)):
    return await focus_engine.get_focus_history(db, limit=limit)


# ─── Dump ───────────────────────────────────────────────────────────────────

@router.post("/dump")
async def process_dump(req: DumpReq, db: AsyncSession = Depends(get_db)):
    return await dump_engine.process_dump(db, raw_text=req.text, source=req.source)


@router.post("/dump/confirm")
async def confirm_dump(req: DumpConfirmReq, db: AsyncSession = Depends(get_db)):
    return await dump_engine.confirm_dump(db, dump_id=req.dump_id, confirmed_items=req.confirmed_items)


# ─── Check-ins ──────────────────────────────────────────────────────────────

@router.get("/checkin/should")
async def should_checkin(db: AsyncSession = Depends(get_db)):
    return await checkin_engine.should_checkin(db)


@router.post("/checkin/generate")
async def generate_checkin(trigger: str = "manual", db: AsyncSession = Depends(get_db)):
    return await checkin_engine.generate_checkin(db, trigger=trigger)


@router.post("/checkin/respond")
async def respond_checkin(req: CheckInRespondReq, db: AsyncSession = Depends(get_db)):
    return await checkin_engine.record_checkin_response(db, req.checkin_id, req.response)


@router.post("/eod-review")
async def eod_review(db: AsyncSession = Depends(get_db)):
    return await checkin_engine.generate_eod_review(db)


# ─── Memories ───────────────────────────────────────────────────────────────

@router.get("/memories")
async def list_memories(db: AsyncSession = Depends(get_db)):
    return await memory_engine.get_memories(db)


@router.post("/memories")
async def create_memory(req: MemoryReq, db: AsyncSession = Depends(get_db)):
    return await memory_engine.add_memory(db, content=req.content, category=req.category)


@router.delete("/memories/{memory_id}")
async def remove_memory(memory_id: int, db: AsyncSession = Depends(get_db)):
    return await memory_engine.delete_memory(db, memory_id)


@router.post("/memories/analyze")
async def analyze(db: AsyncSession = Depends(get_db)):
    return await memory_engine.analyze_patterns(db)
