import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.features.shopping.models import ShoppingItem
from app.features.shopping.schemas import ShoppingItemCreate, ShoppingItemUpdate
from app.shared.dates import now_brt


async def create_item(db: AsyncSession, data: ShoppingItemCreate) -> ShoppingItem:
    item = ShoppingItem(
        id=str(uuid.uuid4()),
        text=data.text.strip(),
        category=data.category,
        done=0,
        created_at=now_brt().isoformat(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def create_items_bulk(db: AsyncSession, texts: list[str], category: str = None) -> list[ShoppingItem]:
    items = []
    now = now_brt().isoformat()
    for text in texts:
        text = text.strip()
        if not text:
            continue
        item = ShoppingItem(
            id=str(uuid.uuid4()),
            text=text,
            category=category,
            done=0,
            created_at=now,
        )
        db.add(item)
        items.append(item)
    await db.commit()
    for item in items:
        await db.refresh(item)
    return items


async def list_items(db: AsyncSession, include_done: bool = False) -> list[ShoppingItem]:
    q = select(ShoppingItem)
    if not include_done:
        q = q.where(ShoppingItem.done == 0)
    q = q.order_by(ShoppingItem.done, ShoppingItem.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_item(db: AsyncSession, item_id: str, data: ShoppingItemUpdate) -> ShoppingItem | None:
    result = await db.execute(select(ShoppingItem).where(ShoppingItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    if data.done == 1 and not item.completed_at:
        item.completed_at = now_brt().isoformat()
    elif data.done == 0:
        item.completed_at = None
    await db.commit()
    await db.refresh(item)
    return item


async def delete_item(db: AsyncSession, item_id: str) -> bool:
    result = await db.execute(select(ShoppingItem).where(ShoppingItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return False
    await db.delete(item)
    await db.commit()
    return True


async def clear_done(db: AsyncSession) -> int:
    result = await db.execute(select(ShoppingItem).where(ShoppingItem.done == 1))
    items = result.scalars().all()
    count = len(items)
    for item in items:
        await db.delete(item)
    await db.commit()
    return count
