import uuid
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.features.habits.models import Habit, HabitLog, DayScore
from app.features.habits.schemas import HabitCreate, HabitUpdate
from app.features.tasks.models import Task
from app.shared.dates import now_brt, today_brt

DAYS_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
EFFORT_POINTS = {1: 1, 2: 3, 3: 5}
EFFORT_MISS = {1: -1, 2: -2, 3: -3}


def _habit_days(frequency: str) -> list[int]:
    if frequency == "daily":
        return [0, 1, 2, 3, 4, 5, 6]
    return [DAYS_MAP[d.strip().lower()] for d in frequency.split(",") if d.strip().lower() in DAYS_MAP]


def _is_habit_day(habit: Habit, d: date) -> bool:
    return d.weekday() in _habit_days(habit.frequency)


async def create_habit(db: AsyncSession, data: HabitCreate) -> Habit:
    habit = Habit(
        id=str(uuid.uuid4()),
        name=data.name,
        frequency=data.frequency,
        points_done=data.points_done,
        points_missed=data.points_missed,
        active=1,
        created_at=now_brt().isoformat(),
    )
    db.add(habit)
    await db.commit()
    await db.refresh(habit)
    return habit


async def list_habits(db: AsyncSession, active_only: bool = True) -> list[Habit]:
    q = select(Habit)
    if active_only:
        q = q.where(Habit.active == 1)
    q = q.order_by(Habit.created_at)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_habit(db: AsyncSession, habit_id: str, data: HabitUpdate) -> Optional[Habit]:
    result = await db.execute(select(Habit).where(Habit.id == habit_id))
    habit = result.scalar_one_or_none()
    if not habit:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(habit, field, value)
    await db.commit()
    await db.refresh(habit)
    return habit


async def delete_habit(db: AsyncSession, habit_id: str) -> bool:
    result = await db.execute(select(Habit).where(Habit.id == habit_id))
    habit = result.scalar_one_or_none()
    if not habit:
        return False
    await db.delete(habit)
    await db.commit()
    return True


async def mark_habit(db: AsyncSession, habit_id: str, d: date = None, done: int = 1) -> Optional[HabitLog]:
    if d is None:
        d = today_brt()
    date_str = d.isoformat()

    result = await db.execute(select(Habit).where(Habit.id == habit_id))
    habit = result.scalar_one_or_none()
    if not habit:
        return None

    existing = await db.execute(
        select(HabitLog).where(HabitLog.habit_id == habit_id, HabitLog.date == date_str)
    )
    log = existing.scalar_one_or_none()

    points = habit.points_done if done else habit.points_missed

    if log:
        log.done = done
        log.points = points
    else:
        log = HabitLog(
            id=str(uuid.uuid4()),
            habit_id=habit_id,
            date=date_str,
            done=done,
            points=points,
            created_at=now_brt().isoformat(),
        )
        db.add(log)

    await db.commit()
    await db.refresh(log)
    return log


async def get_habits_for_date(db: AsyncSession, d: date = None) -> list[dict]:
    if d is None:
        d = today_brt()
    date_str = d.isoformat()

    habits = await list_habits(db, active_only=True)
    result = []

    for habit in habits:
        if not _is_habit_day(habit, d):
            continue

        log_result = await db.execute(
            select(HabitLog).where(HabitLog.habit_id == habit.id, HabitLog.date == date_str)
        )
        log = log_result.scalar_one_or_none()

        result.append({
            "habit_id": habit.id,
            "name": habit.name,
            "frequency": habit.frequency,
            "points_done": habit.points_done,
            "points_missed": habit.points_missed,
            "done": log.done if log else 0,
            "logged": log is not None,
        })

    return result


async def calculate_day_score(db: AsyncSession, d: date = None) -> DayScore:
    if d is None:
        d = today_brt()
    date_str = d.isoformat()

    result = await db.execute(
        select(Task).where(
            Task.deadline == date_str,
            Task.reviewed == 1,
            Task.project_slug == "pessoal",
        )
    )
    proposed_tasks = list(result.scalars().all())

    tasks_proposed = len(proposed_tasks)
    tasks_done = len([t for t in proposed_tasks if t.status == "done"])

    points_earned = 0
    points_lost = 0

    for task in proposed_tasks:
        effort = getattr(task, "effort", None) or 1
        if task.status == "done":
            points_earned += EFFORT_POINTS.get(effort, 1)
        else:
            points_lost += abs(EFFORT_MISS.get(effort, -1))

    habits_today = await get_habits_for_date(db, d)
    habits_done = 0
    habits_missed = 0

    for h in habits_today:
        if h["done"]:
            habits_done += 1
            points_earned += h["points_done"]
        elif h["logged"] and not h["done"]:
            habits_missed += 1
            points_lost += abs(h["points_missed"])
        else:
            from datetime import datetime
            now = now_brt()
            if now.date() > d or (now.date() == d and now.hour >= 23):
                habits_missed += 1
                points_lost += abs(h["points_missed"])

    total_items = tasks_proposed + len(habits_today)
    done_items = tasks_done + habits_done
    if total_items == 0:
        grade = "neutral"
    else:
        pct = int((done_items / total_items) * 100)
        if pct >= 70:
            grade = "good"
        elif pct >= 40:
            grade = "neutral"
        else:
            grade = "bad"

    yesterday = (d - timedelta(days=1)).isoformat()
    prev_result = await db.execute(select(DayScore).where(DayScore.date == yesterday))
    prev = prev_result.scalar_one_or_none()
    prev_streak = prev.streak if prev else 0

    if grade == "good":
        streak = prev_streak + 1
    elif grade == "neutral":
        streak = prev_streak
    else:
        streak = max(0, prev_streak - 3)

    existing = await db.execute(select(DayScore).where(DayScore.date == date_str))
    score = existing.scalar_one_or_none()

    if score:
        score.tasks_proposed = tasks_proposed
        score.tasks_done = tasks_done
        score.habits_done = habits_done
        score.habits_missed = habits_missed
        score.points_earned = points_earned
        score.points_lost = points_lost
        score.streak = streak
        score.grade = grade
    else:
        score = DayScore(
            date=date_str,
            tasks_proposed=tasks_proposed,
            tasks_done=tasks_done,
            habits_done=habits_done,
            habits_missed=habits_missed,
            points_earned=points_earned,
            points_lost=points_lost,
            streak=streak,
            grade=grade,
        )
        db.add(score)

    await db.commit()
    await db.refresh(score)
    return score


async def get_today_status(db: AsyncSession) -> dict:
    today = today_brt()
    date_str = today.isoformat()

    score = await calculate_day_score(db, today)

    total_result = await db.execute(
        select(
            func.coalesce(func.sum(DayScore.points_earned), 0),
            func.coalesce(func.sum(DayScore.points_lost), 0),
        )
    )
    row = total_result.one()
    total_points = row[0] - row[1]

    habits = await get_habits_for_date(db, today)

    week = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.isoformat()
        res = await db.execute(select(DayScore).where(DayScore.date == d_str))
        ds = res.scalar_one_or_none()
        week.append({
            "date": d_str,
            "day": ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"][d.weekday()],
            "grade": ds.grade if ds else None,
            "points": (ds.points_earned - ds.points_lost) if ds else 0,
        })

    total_items = score.tasks_proposed + score.habits_done + score.habits_missed
    done_items = score.tasks_done + score.habits_done
    pct = int((done_items / total_items) * 100) if total_items > 0 else 0

    return {
        "date": date_str,
        "streak": score.streak,
        "total_points": total_points,
        "today_points": score.points_earned - score.points_lost,
        "tasks_proposed": score.tasks_proposed,
        "tasks_done": score.tasks_done,
        "completion_pct": pct,
        "grade": score.grade or "neutral",
        "habits": habits,
        "week": week,
    }


async def get_week_scores(db: AsyncSession) -> list[dict]:
    today = today_brt()
    week = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.isoformat()
        res = await db.execute(select(DayScore).where(DayScore.date == d_str))
        ds = res.scalar_one_or_none()
        week.append({
            "date": d_str,
            "day": ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"][d.weekday()],
            "grade": ds.grade if ds else None,
            "points": (ds.points_earned - ds.points_lost) if ds else 0,
            "streak": ds.streak if ds else 0,
        })
    return week
