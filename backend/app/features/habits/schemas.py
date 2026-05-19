from pydantic import BaseModel
from typing import Optional, List


class HabitCreate(BaseModel):
    name: str
    frequency: str = "daily"
    points_done: int = 3
    points_missed: int = -2


class HabitUpdate(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    points_done: Optional[int] = None
    points_missed: Optional[int] = None
    active: Optional[int] = None


class HabitResponse(BaseModel):
    id: str
    name: str
    frequency: str
    points_done: int
    points_missed: int
    active: int
    created_at: str

    model_config = {"from_attributes": True}


class HabitLogResponse(BaseModel):
    id: str
    habit_id: str
    date: str
    done: int
    points: int
    created_at: str

    model_config = {"from_attributes": True}


class DayScoreResponse(BaseModel):
    date: str
    tasks_proposed: int
    tasks_done: int
    habits_done: int
    habits_missed: int
    points_earned: int
    points_lost: int
    streak: int
    grade: Optional[str] = None

    model_config = {"from_attributes": True}


class TodayStatus(BaseModel):
    date: str
    streak: int
    total_points: int
    today_points: int
    tasks_proposed: int
    tasks_done: int
    completion_pct: int
    grade: str
    habits: List[dict]
    week: List[dict]
