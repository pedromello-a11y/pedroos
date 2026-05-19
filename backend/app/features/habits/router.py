from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db import get_db
from app.features.habits import service
from app.features.habits.schemas import (
    HabitCreate, HabitUpdate, HabitResponse, HabitLogResponse, DayScoreResponse,
)

router = APIRouter(prefix="/api/habits", tags=["habits"])


@router.get("")
async def list_habits(active: Optional[int] = 1, db: AsyncSession = Depends(get_db)):
    habits = await service.list_habits(db, active_only=bool(active))
    return [HabitResponse.model_validate(h) for h in habits]


@router.post("", status_code=201)
async def create_habit(data: HabitCreate, db: AsyncSession = Depends(get_db)):
    habit = await service.create_habit(db, data)
    return HabitResponse.model_validate(habit)


@router.patch("/{habit_id}")
async def update_habit(habit_id: str, data: HabitUpdate, db: AsyncSession = Depends(get_db)):
    habit = await service.update_habit(db, habit_id, data)
    if not habit:
        raise HTTPException(404, "Hábito não encontrado")
    return HabitResponse.model_validate(habit)


@router.delete("/{habit_id}", status_code=204)
async def delete_habit(habit_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_habit(db, habit_id):
        raise HTTPException(404, "Hábito não encontrado")


@router.post("/{habit_id}/check")
async def check_habit(habit_id: str, done: int = 1, db: AsyncSession = Depends(get_db)):
    log = await service.mark_habit(db, habit_id, done=done)
    if not log:
        raise HTTPException(404, "Hábito não encontrado")
    return HabitLogResponse.model_validate(log)


@router.post("/{habit_id}/uncheck")
async def uncheck_habit(habit_id: str, db: AsyncSession = Depends(get_db)):
    log = await service.mark_habit(db, habit_id, done=0)
    if not log:
        raise HTTPException(404, "Hábito não encontrado")
    return HabitLogResponse.model_validate(log)


@router.get("/today")
async def today_status(db: AsyncSession = Depends(get_db)):
    return await service.get_today_status(db)


@router.get("/week")
async def week_scores(db: AsyncSession = Depends(get_db)):
    return await service.get_week_scores(db)


@router.post("/calculate")
async def force_calculate(db: AsyncSession = Depends(get_db)):
    score = await service.calculate_day_score(db)
    return DayScoreResponse.model_validate(score)
