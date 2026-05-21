from pydantic import BaseModel
from typing import Optional, List

DIFFICULTY_POINTS = {
    1: {"done": 1, "missed": -1},
    2: {"done": 3, "missed": -2},
    3: {"done": 5, "missed": -3},
}


class HabitCreate(BaseModel):
    name: str
    icon: str = "⭐"
    frequency: str = "daily"  # "daily", "mon,wed,fri", "tue,thu", "flex"
    difficulty: int = 2
    weekly_target: Optional[int] = None


class HabitUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    frequency: Optional[str] = None
    difficulty: Optional[int] = None
    weekly_target: Optional[int] = None
    active: Optional[int] = None


class HabitResponse(BaseModel):
    id: str
    name: str
    icon: str
    frequency: str
    difficulty: int
    weekly_target: Optional[int] = None
    active: int
    created_at: str
    points_done: int = 0
    points_missed: int = 0

    model_config = {"from_attributes": True}

    @classmethod
    def from_habit(cls, habit):
        pts = DIFFICULTY_POINTS.get(habit.difficulty, DIFFICULTY_POINTS[2])
        return cls(
            id=habit.id,
            name=habit.name,
            icon=habit.icon or "⭐",
            frequency=habit.frequency,
            difficulty=habit.difficulty,
            weekly_target=habit.weekly_target,
            active=habit.active,
            created_at=habit.created_at,
            points_done=pts["done"],
            points_missed=abs(pts["missed"]),
        )


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


class HabitTodayItem(BaseModel):
    habit_id: str
    name: str
    icon: str
    frequency: str
    difficulty: int
    weekly_target: Optional[int] = None
    week_done: int = 0
    points_done: int
    points_missed: int
    done: int        # 0=pendente, 1=feito
    proposed: bool   # True se é dia deste hábito ou foi proposto manualmente
    is_today_habit: bool = True  # False = não é dia agendado hoje (mas mostra na semana)
    streak: int
    week_progress: List[dict] = []  # [{label, done, is_today, date}]


class TodayStatus(BaseModel):
    date: str
    streak: int
    total_points: int
    today_points: int
    tasks_proposed: int
    tasks_done: int
    completion_pct: int
    grade: str
    habits: List[HabitTodayItem]
    week: List[dict]
