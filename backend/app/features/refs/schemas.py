from pydantic import BaseModel
from typing import Optional, List


class RefCreate(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    note: Optional[str] = None
    thumbnail: Optional[str] = None
    source_type: Optional[str] = None
    boards: List[str] = []
    source: str = "dashboard"
    raw_input: Optional[str] = None


class RefUpdate(BaseModel):
    title: Optional[str] = None
    note: Optional[str] = None
    thumbnail: Optional[str] = None
    boards: Optional[List[str]] = None


class RefResponse(BaseModel):
    id: str
    short_id: str
    url: Optional[str] = None
    title: Optional[str] = None
    note: Optional[str] = None
    thumbnail: Optional[str] = None
    source_type: Optional[str] = None
    domain: Optional[str] = None
    source: str
    boards: List[str] = []
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class RefBoardCreate(BaseModel):
    name: str
    color: Optional[str] = None


class RefBoardUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None


class RefBoardResponse(BaseModel):
    id: str
    name: str
    color: Optional[str] = None
    position: int
    count: int = 0
    created_at: str

    model_config = {"from_attributes": True}


class ExtractResponse(BaseModel):
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    source_type: Optional[str] = None
    domain: Optional[str] = None
