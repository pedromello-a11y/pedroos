import uuid
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.features.habits.models import Habit, HabitLog, DayScore, PersonalRecord
from app.features.habits.schemas import HabitCreate, HabitUpdate, DIFFICULTY_POINTS, HabitTodayItem
from app.features.tasks.models import Task
from app.shared.dates import now_brt, today_brt

DAYS_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _count_week_done(db: AsyncSession, habit_id: str, d: date) -> int:
    ws = _week_start(d)
    result = await db.execute(
        select(func.count(HabitLog.id)).where(
            HabitLog.habit_id == habit_id,
            HabitLog.date >= ws.isoformat(),
            HabitLog.date <= d.isoformat(),
            HabitLog.done == 1,
        )
    )
    return result.scalar() or 0


def _habit_days(frequency: str) -> list[int]:
    if frequency == "daily":
        return [0, 1, 2, 3, 4, 5, 6]
    if frequency == "flex":
        return []
    return [DAYS_MAP[d.strip().lower()] for d in frequency.split(",") if d.strip().lower() in DAYS_MAP]


def _is_habit_day(habit: Habit, d: date) -> bool:
    if habit.frequency == "flex":
        return False
    return d.weekday() in _habit_days(habit.frequency)


def _get_points(difficulty: int) -> dict:
    return DIFFICULTY_POINTS.get(difficulty, DIFFICULTY_POINTS[2])


async def create_habit(db: AsyncSession, data: HabitCreate) -> Habit:
    habit = Habit(
        id=str(uuid.uuid4()),
        name=data.name,
        icon=data.icon,
        frequency=data.frequency,
        difficulty=data.difficulty,
        weekly_target=data.weekly_target,
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


async def propose_habit(db: AsyncSession, habit_id: str, d: date = None) -> Optional[HabitLog]:
    """Propõe um hábito flex para o dia (ex: 'hoje vou correr')."""
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
    if log:
        return log

    log = HabitLog(
        id=str(uuid.uuid4()),
        habit_id=habit_id,
        date=date_str,
        done=0,
        points=0,
        created_at=now_brt().isoformat(),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def mark_habit(db: AsyncSession, habit_id: str, d: date = None, done: int = 1) -> Optional[HabitLog]:
    if d is None:
        d = today_brt()
    date_str = d.isoformat()

    result = await db.execute(select(Habit).where(Habit.id == habit_id))
    habit = result.scalar_one_or_none()
    if not habit:
        return None

    pts = _get_points(habit.difficulty)

    # Weekly-target flex habits: append-mode (multiple logs per week allowed)
    if habit.weekly_target and habit.frequency == "flex":
        if done == 1:
            week_done = await _count_week_done(db, habit_id, d)
            if week_done >= habit.weekly_target:
                # Already at target — return most recent log without creating new
                last = await db.execute(
                    select(HabitLog).where(HabitLog.habit_id == habit_id, HabitLog.done == 1)
                    .order_by(HabitLog.created_at.desc()).limit(1)
                )
                return last.scalar_one_or_none()
            log = HabitLog(
                id=str(uuid.uuid4()),
                habit_id=habit_id,
                date=date_str,
                done=1,
                points=pts["done"],
                created_at=now_brt().isoformat(),
            )
            db.add(log)
            await db.commit()
            await db.refresh(log)
            return log
        else:  # uncheck: delete last done log of the week
            ws = _week_start(d)
            last = await db.execute(
                select(HabitLog).where(
                    HabitLog.habit_id == habit_id,
                    HabitLog.date >= ws.isoformat(),
                    HabitLog.done == 1,
                ).order_by(HabitLog.created_at.desc()).limit(1)
            )
            log = last.scalar_one_or_none()
            if log:
                await db.delete(log)
                await db.commit()
            return log

    # Regular habits: upsert per day
    points = pts["done"] if done else pts["missed"]
    existing = await db.execute(
        select(HabitLog).where(HabitLog.habit_id == habit_id, HabitLog.date == date_str)
    )
    log = existing.scalar_one_or_none()

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


async def get_habit_streak(db: AsyncSession, habit_id: str, from_date: date = None) -> int:
    """Calcula streak individual de um hábito (dias consecutivos feito)."""
    if from_date is None:
        from_date = today_brt()

    result = await db.execute(select(Habit).where(Habit.id == habit_id))
    habit = result.scalar_one_or_none()
    if not habit:
        return 0

    streak = 0
    d = from_date

    for _ in range(90):
        d_str = d.isoformat()
        is_day = _is_habit_day(habit, d)

        if habit.frequency == "flex":
            log_res = await db.execute(
                select(HabitLog).where(HabitLog.habit_id == habit_id, HabitLog.date == d_str)
            )
            log = log_res.scalar_one_or_none()
            if log:
                if log.done:
                    streak += 1
                else:
                    break
        elif is_day:
            log_res = await db.execute(
                select(HabitLog).where(HabitLog.habit_id == habit_id, HabitLog.date == d_str)
            )
            log = log_res.scalar_one_or_none()
            if log and log.done:
                streak += 1
            elif d < from_date:
                break
            else:
                break

        d -= timedelta(days=1)

    return streak


async def get_habits_for_date(db: AsyncSession, d: date = None) -> list[HabitTodayItem]:
    if d is None:
        d = today_brt()
    date_str = d.isoformat()

    habits = await list_habits(db, active_only=True)
    result = []

    for habit in habits:
        is_day = _is_habit_day(habit, d)
        pts = _get_points(habit.difficulty)

        log_result = await db.execute(
            select(HabitLog).where(HabitLog.habit_id == habit.id, HabitLog.date == date_str)
        )
        log = log_result.scalar_one_or_none()

        if habit.frequency == "flex" and habit.weekly_target:
            week_done = await _count_week_done(db, habit.id, d)
            result.append(HabitTodayItem(
                habit_id=habit.id,
                name=habit.name,
                icon=habit.icon or "⭐",
                frequency=habit.frequency,
                difficulty=habit.difficulty,
                weekly_target=habit.weekly_target,
                week_done=week_done,
                points_done=pts["done"],
                points_missed=abs(pts["missed"]),
                done=1 if week_done >= habit.weekly_target else 0,
                proposed=True,
                streak=0,
            ))
            continue

        if habit.frequency == "flex" and not log:
            result.append(HabitTodayItem(
                habit_id=habit.id,
                name=habit.name,
                icon=habit.icon or "⭐",
                frequency=habit.frequency,
                difficulty=habit.difficulty,
                points_done=pts["done"],
                points_missed=abs(pts["missed"]),
                done=0,
                proposed=False,
                streak=await get_habit_streak(db, habit.id, d - timedelta(days=1)),
            ))
            continue

        if not is_day and not log:
            continue

        streak = await get_habit_streak(db, habit.id, d - timedelta(days=1))

        result.append(HabitTodayItem(
            habit_id=habit.id,
            name=habit.name,
            icon=habit.icon or "⭐",
            frequency=habit.frequency,
            difficulty=habit.difficulty,
            points_done=pts["done"],
            points_missed=abs(pts["missed"]),
            done=log.done if log else 0,
            proposed=True,
            streak=streak + (1 if log and log.done else 0),
        ))

    return result


async def calculate_day_score(db: AsyncSession, d: date = None) -> DayScore:
    if d is None:
        d = today_brt()
    date_str = d.isoformat()

    result = await db.execute(
        select(Task).where(Task.deadline == date_str, Task.reviewed == 1)
    )
    all_tasks = list(result.scalars().all())
    personal_slugs = {"pessoal"}
    proposed_tasks = [t for t in all_tasks if t.project_slug in personal_slugs or t.project_slug is None]

    tasks_proposed = len(proposed_tasks)
    tasks_done = len([t for t in proposed_tasks if t.status == "done"])

    points_earned = 0
    points_lost = 0

    for task in proposed_tasks:
        effort = getattr(task, "effort", None) or 1
        task_pts = DIFFICULTY_POINTS.get(effort, DIFFICULTY_POINTS[1])
        if task.status == "done":
            points_earned += task_pts["done"]
        else:
            now = now_brt()
            if now.date() > d or (now.date() == d and now.hour >= 23):
                points_lost += abs(task_pts["missed"])

    habits_today = await get_habits_for_date(db, d)
    habits_done = 0
    habits_missed = 0

    for h in habits_today:
        if not h.proposed:
            continue
        if h.done:
            habits_done += 1
            points_earned += h.points_done
        else:
            now = now_brt()
            if now.date() > d or (now.date() == d and now.hour >= 23):
                habits_missed += 1
                points_lost += h.points_missed

    total_items = tasks_proposed + habits_done + habits_missed
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


def _compute_combo(tasks_done: int, habits_done: int) -> dict:
    pos = tasks_done + habits_done
    if pos <= 2:
        mult = 1.0
    elif pos <= 4:
        mult = 1.5
    elif pos <= 6:
        mult = 2.0
    else:
        mult = 4.0
    next_mult = None if pos >= 7 else (1.0 if pos < 2 else 1.5 if pos < 4 else 2.0 if pos < 6 else 4.0)
    return {
        "current_position": pos,
        "current_multiplier": mult,
        "next_multiplier": next_mult,
        "is_frenzy": pos >= 7,
        "until_frenzy": max(0, 7 - pos),
    }


async def _check_and_update_records(db: AsyncSession, today: date, score: DayScore, combo: dict) -> list[dict]:
    new_records = []
    checks = [
        ("max_tasks_day", score.tasks_done),
        ("max_streak", score.streak),
        ("max_combo", combo["current_position"]),
    ]
    for record_type, today_value in checks:
        if today_value <= 0:
            continue
        res = await db.execute(select(PersonalRecord).where(PersonalRecord.record_type == record_type))
        rec = res.scalar_one_or_none()
        if rec is None:
            db.add(PersonalRecord(record_type=record_type, value=today_value, achieved_at=today.isoformat()))
        elif today_value > rec.value:
            rec.value = today_value
            rec.achieved_at = today.isoformat()
            new_records.append({"record_type": record_type, "value": today_value})
    await db.commit()
    return new_records


def _get_milestones(score: DayScore, combo: dict) -> list[str]:
    milestones = []
    pos = combo["current_position"]
    if pos == 7:
        milestones.append("🔥 Frenzy ativado — modo lendário!")
    if score.streak in (7, 14, 30, 60, 100):
        milestones.append(f"🗓 {score.streak} dias de streak — incrível!")
    return milestones


async def get_today_status(db: AsyncSession) -> dict:
    today = today_brt()

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
            "is_today": d == today,
        })

    total_items = score.tasks_proposed + score.habits_done + score.habits_missed
    done_items = score.tasks_done + score.habits_done
    pct = int((done_items / total_items) * 100) if total_items > 0 else 0

    combo = _compute_combo(score.tasks_done, score.habits_done)
    new_records = await _check_and_update_records(db, today, score, combo)
    milestones = _get_milestones(score, combo)

    return {
        "date": today.isoformat(),
        "streak": score.streak,
        "total_points": total_points,
        "today_points": score.points_earned - score.points_lost,
        "today_base_points": score.points_earned,
        "tasks_proposed": score.tasks_proposed,
        "tasks_done": score.tasks_done,
        "completion_pct": pct,
        "grade": score.grade or "neutral",
        "combo": combo,
        "habits": [h.model_dump() for h in habits],
        "week": week,
        "new_records": new_records,
        "milestones": milestones,
    }
