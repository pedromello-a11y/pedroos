from pydantic import BaseModel
from typing import Optional


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    color: Optional[str] = None
    position: int = 0


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    color: Optional[str] = None
    active: Optional[int] = None
    position: Optional[int] = None


class ProjectResponse(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    color: Optional[str] = None
    active: int
    position: int
    created_at: str

    model_config = {"from_attributes": True}
