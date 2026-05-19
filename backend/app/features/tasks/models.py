from sqlalchemy import Column, Text, Integer, Float, ForeignKey, Index
from app.db import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Text, primary_key=True)
    short_id = Column(Text, nullable=False, unique=True)

    title = Column(Text, nullable=False)
    raw_input = Column(Text)
    description = Column(Text)

    project_slug = Column(Text, ForeignKey("projects.slug"))
    deadline = Column(Text)
    priority = Column(Text, default="p3")

    status = Column(Text, default="todo")
    reviewed = Column(Integer, default=0)
    snoozed_until = Column(Text)

    parent_id = Column(Text, ForeignKey("tasks.id"))

    jira_key = Column(Text)
    status_note = Column(Text)
    estimated_hours = Column(Float, nullable=True)
    actual_hours = Column(Float, nullable=True)
    position = Column(Integer, nullable=True)
    effort = Column(Integer, default=1)  # 1=baixo, 2=médio, 3=alto

    remind_at = Column(Text)
    source = Column(Text, default="dashboard")
    created_at = Column(Text, nullable=False)
    reviewed_at = Column(Text)
    completed_at = Column(Text)
    updated_at = Column(Text, nullable=False)

    __table_args__ = (
        Index("idx_tasks_reviewed", "reviewed", "created_at"),
        Index("idx_tasks_status_deadline", "status", "deadline"),
        Index("idx_tasks_project", "project_slug"),
        Index("idx_tasks_parent", "parent_id"),
    )


class Checklist(Base):
    __tablename__ = "checklist"

    id = Column(Text, primary_key=True)
    task_id = Column(Text, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    text = Column(Text, nullable=False)
    done = Column(Integer, default=0)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(Text, nullable=False)

    __table_args__ = (Index("idx_checklist_task", "task_id", "position"),)


class TaskLink(Base):
    __tablename__ = "task_links"

    id = Column(Text, primary_key=True)
    task_id = Column(Text, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text, nullable=False)
    label = Column(Text)
    created_at = Column(Text, nullable=False)

    __table_args__ = (Index("idx_links_task", "task_id"),)


class TaskImage(Base):
    __tablename__ = "task_images"

    id = Column(Text, primary_key=True)
    task_id = Column(Text, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    filename = Column(Text, nullable=False)
    original_name = Column(Text, nullable=False)
    mime_type = Column(Text, nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(Text, nullable=False)

    __table_args__ = (Index("idx_images_task", "task_id"),)


class WaProcessed(Base):
    __tablename__ = "wa_processed"

    message_id = Column(Text, primary_key=True)
    processed_at = Column(Text, nullable=False)
