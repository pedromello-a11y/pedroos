from sqlalchemy import Column, Text, Integer, ForeignKey, Index
from app.db import Base


class FocusModeSession(Base):
    __tablename__ = "focus_mode_sessions"

    id = Column(Text, primary_key=True)
    task_id = Column(Text, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    planned_minutes = Column(Integer, nullable=False)
    paused_seconds = Column(Integer, default=0)
    state = Column(Text, default="active")   # active, paused, completed, aborted
    checkpoints = Column(Text, default="[]") # JSON: [{label, weight, done, done_at}]
    started_at = Column(Text, nullable=False)
    paused_at = Column(Text, nullable=True)
    ended_at = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)

    __table_args__ = (
        Index("idx_focus_mode_task", "task_id", "created_at"),
        Index("idx_focus_mode_state", "state"),
    )
