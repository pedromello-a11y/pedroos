"""Modelos para o sistema de IA: focus sessions, brain dumps, memories, check-ins."""
from sqlalchemy import Column, Text, Integer, Float, Boolean, Index
from app.db import Base


class FocusSession(Base):
    __tablename__ = "focus_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(Text, nullable=False)
    ended_at = Column(Text, nullable=True)
    status = Column(Text, default="active")       # active, completed, abandoned
    source = Column(Text, default="dashboard")    # dashboard, whatsapp
    messages = Column(Text, default="[]")         # JSON serializado
    outcome_summary = Column(Text, nullable=True)
    mood_start = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    created_at = Column(Text, nullable=False)

    __table_args__ = (Index("idx_focus_sessions_status", "status", "created_at"),)


class BrainDump(Base):
    __tablename__ = "brain_dumps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_input = Column(Text, nullable=False)
    parsed_items = Column(Text, default="[]")    # JSON serializado
    tasks_created = Column(Text, default="[]")   # JSON serializado
    tasks_updated = Column(Text, default="[]")   # JSON serializado
    source = Column(Text, default="whatsapp")
    status = Column(Text, default="pending")     # pending, processed, confirmed, error
    created_at = Column(Text, nullable=False)

    __table_args__ = (Index("idx_brain_dumps_status", "status", "created_at"),)


class AIMemory(Base):
    __tablename__ = "ai_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(Text, nullable=False)   # productivity, preference, pattern, blocker
    content = Column(Text, nullable=False)
    confidence = Column(Float, default=0.5)   # 0-1
    evidence_count = Column(Integer, default=1)
    last_seen = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    extra = Column(Text, default="{}")        # JSON serializado (metadata)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    __table_args__ = (Index("idx_ai_memories_active", "is_active", "confidence"),)


class CheckIn(Base):
    __tablename__ = "check_ins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(Text, nullable=False)          # progress, reminder, nudge, eod_review
    trigger_reason = Column(Text, nullable=True)
    message_sent = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    response_at = Column(Text, nullable=True)
    task_id = Column(Text, nullable=True)
    was_helpful = Column(Boolean, nullable=True)
    sent_at = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)

    __table_args__ = (Index("idx_check_ins_sent_at", "sent_at"),)


class DailyReview(Base):
    __tablename__ = "daily_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Text, nullable=False, unique=True)   # YYYY-MM-DD
    tasks_completed = Column(Text, default="[]")       # JSON
    tasks_in_progress = Column(Text, default="[]")     # JSON
    tasks_not_touched = Column(Text, default="[]")     # JSON
    ai_summary = Column(Text, nullable=True)
    ai_suggestions_tomorrow = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
