from pydantic import BaseModel
from typing import Optional, Literal


VALID_TAGS = ("decisão", "referência", "ideia", "reunião")


class NoteCreate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    raw_input: Optional[str] = None
    project_slug: Optional[str] = None
    tag: Optional[str] = None
    pinned: int = 0
    source: Literal["dashboard", "whatsapp"] = "dashboard"


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    project_slug: Optional[str] = None
    tag: Optional[str] = None
    pinned: Optional[int] = None


class NoteResponse(BaseModel):
    id: str
    short_id: str
    title: Optional[str] = None
    content: Optional[str] = None
    raw_input: Optional[str] = None
    project_slug: Optional[str] = None
    tag: Optional[str] = None
    pinned: int
    source: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
