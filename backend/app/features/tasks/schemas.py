from pydantic import BaseModel, field_validator
from typing import Optional, List, Literal


class TaskCreate(BaseModel):
    title: str
    raw_input: Optional[str] = None
    description: Optional[str] = None
    project_slug: Optional[str] = None
    deadline: Optional[str] = None
    priority: Literal["p1", "p2", "p3", "backlog"] = "p3"
    status: Literal["raw", "todo", "doing", "queued", "backlog", "done"] = "raw"
    reviewed: int = 1
    source: Literal["whatsapp", "dashboard", "jira"] = "dashboard"
    parent_id: Optional[str] = None
    jira_key: Optional[str] = None
    effort: int = 1


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    project_slug: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[Literal["p1", "p2", "p3", "backlog"]] = None
    status: Optional[Literal["raw", "todo", "doing", "queued", "backlog", "done"]] = None
    reviewed: Optional[int] = None
    snoozed_until: Optional[str] = None
    parent_id: Optional[str] = None
    jira_key: Optional[str] = None
    status_note: Optional[str] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    position: Optional[int] = None
    remind_at: Optional[str] = None
    effort: Optional[int] = None

    @field_validator("deadline", "snoozed_until", "remind_at", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        return None if v == "" else v


class SnoozeRequest(BaseModel):
    days: int = 1


class ChecklistItemCreate(BaseModel):
    text: str


class ChecklistItemUpdate(BaseModel):
    text: Optional[str] = None
    done: Optional[int] = None
    position: Optional[int] = None


class ChecklistItemResponse(BaseModel):
    id: str
    task_id: str
    text: str
    done: int
    position: int
    created_at: str

    model_config = {"from_attributes": True}


class TaskLinkCreate(BaseModel):
    url: str
    label: Optional[str] = None


class TaskLinkResponse(BaseModel):
    id: str
    task_id: str
    url: str
    label: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    id: str
    short_id: str
    title: str
    raw_input: Optional[str] = None
    description: Optional[str] = None
    project_slug: Optional[str] = None
    deadline: Optional[str] = None
    priority: str
    status: str
    reviewed: int
    snoozed_until: Optional[str] = None
    parent_id: Optional[str] = None
    jira_key: Optional[str] = None
    status_note: Optional[str] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    position: Optional[int] = None
    remind_at: Optional[str] = None
    effort: int = 1
    source: str
    created_at: str
    reviewed_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: str

    model_config = {"from_attributes": True}


class TaskImageResponse(BaseModel):
    id: str
    task_id: str
    filename: str
    original_name: str
    mime_type: str
    size: int
    created_at: str

    model_config = {"from_attributes": True}


class TaskDetailResponse(TaskResponse):
    checklist: List[ChecklistItemResponse] = []
    links: List[TaskLinkResponse] = []
    subtasks: List[TaskResponse] = []

    model_config = {"from_attributes": True}
