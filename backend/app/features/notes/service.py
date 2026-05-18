import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.features.notes.models import Note
from app.features.notes.schemas import NoteCreate, NoteUpdate
from app.features.tasks.schemas import TaskCreate
from app.features.tasks.service import create_task
from app.shared.dates import now_brt


def _short_id() -> str:
    return uuid.uuid4().hex[:6].upper()


async def create_note(db: AsyncSession, data: NoteCreate) -> Note:
    now = now_brt().isoformat()
    note = Note(
        id=str(uuid.uuid4()),
        short_id=_short_id(),
        title=data.title,
        content=data.content,
        raw_input=data.raw_input,
        project_slug=data.project_slug,
        tag=data.tag,
        pinned=data.pinned,
        source=data.source,
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def list_notes(
    db: AsyncSession,
    project_slug: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    pinned_first: bool = True,
) -> list[Note]:
    stmt = select(Note)

    if project_slug == "inbox":
        stmt = stmt.where(Note.project_slug.is_(None))
    elif project_slug:
        stmt = stmt.where(Note.project_slug == project_slug)

    if tag:
        stmt = stmt.where(Note.tag == tag)

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Note.title.ilike(like),
                Note.content.ilike(like),
                Note.raw_input.ilike(like),
            )
        )

    if pinned_first:
        stmt = stmt.order_by(Note.pinned.desc(), Note.created_at.desc())
    else:
        stmt = stmt.order_by(Note.created_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_note(db: AsyncSession, note_id: str) -> Note | None:
    result = await db.execute(select(Note).where(Note.id == note_id))
    return result.scalar_one_or_none()


async def update_note(db: AsyncSession, note: Note, data: NoteUpdate) -> Note:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(note, field, value)
    note.updated_at = now_brt().isoformat()
    await db.commit()
    await db.refresh(note)
    return note


async def delete_note(db: AsyncSession, note: Note) -> None:
    await db.delete(note)
    await db.commit()


async def note_to_task(db: AsyncSession, note: Note) -> object:
    """Converts a note into a task (note is kept)."""
    task_data = TaskCreate(
        title=note.title or note.raw_input or "Nota sem título",
        description=note.content,
        project_slug=note.project_slug,
        source="dashboard",
        reviewed=1,
    )
    return await create_task(db, task_data)
