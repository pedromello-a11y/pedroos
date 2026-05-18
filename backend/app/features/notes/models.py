from sqlalchemy import Column, Text, Integer, Index
from app.db import Base


class Note(Base):
    __tablename__ = "notes"

    id = Column(Text, primary_key=True)
    short_id = Column(Text, nullable=False, unique=True)

    title = Column(Text)
    content = Column(Text)
    raw_input = Column(Text)

    project_slug = Column(Text)          # NULL = inbox
    tag = Column(Text)                   # decisão | referência | ideia | reunião | NULL
    pinned = Column(Integer, default=0)

    source = Column(Text, default="dashboard")   # dashboard | whatsapp
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    __table_args__ = (
        Index("idx_notes_project", "project_slug"),
        Index("idx_notes_pinned", "pinned", "created_at"),
    )
