from sqlalchemy import Column, Text, Integer
from app.db import Base


class Project(Base):
    __tablename__ = "projects"

    slug = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    deadline = Column(Text)
    color = Column(Text)
    active = Column(Integer, default=1)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(Text, nullable=False)
