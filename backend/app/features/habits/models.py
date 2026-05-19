from sqlalchemy import Column, Text, Integer
from app.db import Base


class Habit(Base):
    __tablename__ = "habits"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    frequency = Column(Text, nullable=False)  # "tue,thu" ou "mon,wed,fri" ou "daily"
    points_done = Column(Integer, default=3)
    points_missed = Column(Integer, default=-2)
    active = Column(Integer, default=1)
    created_at = Column(Text, nullable=False)


class HabitLog(Base):
    __tablename__ = "habit_log"

    id = Column(Text, primary_key=True)
    habit_id = Column(Text, nullable=False)
    date = Column(Text, nullable=False)
    done = Column(Integer, default=0)
    points = Column(Integer, default=0)
    created_at = Column(Text, nullable=False)


class DayScore(Base):
    __tablename__ = "day_scores"

    date = Column(Text, primary_key=True)
    tasks_proposed = Column(Integer, default=0)
    tasks_done = Column(Integer, default=0)
    habits_done = Column(Integer, default=0)
    habits_missed = Column(Integer, default=0)
    points_earned = Column(Integer, default=0)
    points_lost = Column(Integer, default=0)
    streak = Column(Integer, default=0)
    grade = Column(Text)  # "good", "neutral", "bad"
