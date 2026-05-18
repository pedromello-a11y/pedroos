from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.features.notes.schemas import NoteCreate, NoteUpdate, NoteResponse
from app.features.notes.service import (
    create_note, list_notes, get_note, update_note, delete_note, note_to_task,
)
from app.features.tasks.schemas import TaskResponse

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=list[NoteResponse])
async def api_list_notes(
    project_slug: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await list_notes(db, project_slug=project_slug, tag=tag, q=q)


@router.post("", response_model=NoteResponse, status_code=201)
async def api_create_note(data: NoteCreate, db: AsyncSession = Depends(get_db)):
    return await create_note(db, data)


@router.get("/{note_id}", response_model=NoteResponse)
async def api_get_note(note_id: str, db: AsyncSession = Depends(get_db)):
    note = await get_note(db, note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def api_update_note(note_id: str, data: NoteUpdate, db: AsyncSession = Depends(get_db)):
    note = await get_note(db, note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    return await update_note(db, note, data)


@router.delete("/{note_id}", status_code=204)
async def api_delete_note(note_id: str, db: AsyncSession = Depends(get_db)):
    note = await get_note(db, note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    await delete_note(db, note)


@router.post("/{note_id}/to-task", response_model=TaskResponse)
async def api_note_to_task(note_id: str, db: AsyncSession = Depends(get_db)):
    note = await get_note(db, note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    task = await note_to_task(db, note)
    return task
