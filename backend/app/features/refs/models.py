from sqlalchemy import Column, Text, Integer, Index
from app.db import Base


class Ref(Base):
    __tablename__ = "refs"

    id = Column(Text, primary_key=True)
    short_id = Column(Text, nullable=False, unique=True)

    url = Column(Text)
    title = Column(Text)
    note = Column(Text)
    thumbnail = Column(Text)

    source_type = Column(Text)  # vimeo, instagram, youtube, behance, image, link
    domain = Column(Text)

    raw_input = Column(Text)
    source = Column(Text, default="dashboard")  # whatsapp | dashboard

    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    __table_args__ = (
        Index("idx_refs_source_type", "source_type"),
        Index("idx_refs_created", "created_at"),
    )


class RefBoard(Base):
    __tablename__ = "ref_boards"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    color = Column(Text)
    position = Column(Integer, default=0)
    created_at = Column(Text, nullable=False)


class RefBoardItem(Base):
    __tablename__ = "ref_board_items"

    ref_id = Column(Text, primary_key=True)
    board_id = Column(Text, primary_key=True)
    position = Column(Integer, default=0)
    added_at = Column(Text, nullable=False)

    __table_args__ = (
        Index("idx_ref_board_items_board", "board_id", "position"),
    )
