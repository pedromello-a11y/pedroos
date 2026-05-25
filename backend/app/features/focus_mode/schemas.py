from typing import List, Optional
from pydantic import BaseModel, Field


class Checkpoint(BaseModel):
    label: str
    weight: int  # 0-100
    done: bool = False
    done_at: Optional[str] = None


class FocusStart(BaseModel):
    task_id: str
    planned_minutes: int = Field(gt=0, le=480)
    checkpoints: List[Checkpoint] = Field(default_factory=list)


class FocusSessionOut(BaseModel):
    id: str
    task_id: str
    planned_minutes: int
    paused_seconds: int
    state: str
    checkpoints: List[Checkpoint]
    started_at: str
    paused_at: Optional[str] = None
    ended_at: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class FocusEnd(BaseModel):
    state: str = "completed"  # completed or aborted
