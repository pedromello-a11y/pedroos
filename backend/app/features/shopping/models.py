from sqlalchemy import Column, Text, Integer, Index
from app.db import Base


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id = Column(Text, primary_key=True)
    text = Column(Text, nullable=False)
    category = Column(Text)
    done = Column(Integer, default=0)
    created_at = Column(Text, nullable=False)
    completed_at = Column(Text)

    __table_args__ = (
        Index("idx_shopping_done", "done", "created_at"),
    )
