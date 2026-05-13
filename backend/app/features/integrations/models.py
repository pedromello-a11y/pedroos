from sqlalchemy import Column, Text, Float
from app.db import Base


class PendingCalendarEvent(Base):
    __tablename__ = "pending_calendar_events"

    id           = Column(Text, primary_key=True)
    title        = Column(Text, nullable=False)
    event_date   = Column(Text, nullable=False)
    event_time   = Column(Text, nullable=False)
    duration_hours = Column(Float, default=1.0)
    created_at   = Column(Text, nullable=False)
