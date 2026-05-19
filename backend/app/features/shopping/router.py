from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.db import get_db
from app.features.shopping import service
from app.features.shopping.schemas import ShoppingItemCreate, ShoppingItemUpdate, ShoppingItemResponse

router = APIRouter(prefix="/api/shopping", tags=["shopping"])


@router.get("", response_model=List[ShoppingItemResponse])
async def list_items(include_done: bool = Query(False), db: AsyncSession = Depends(get_db)):
    return await service.list_items(db, include_done=include_done)


@router.post("", response_model=ShoppingItemResponse, status_code=201)
async def create_item(data: ShoppingItemCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_item(db, data)


@router.post("/bulk", response_model=List[ShoppingItemResponse], status_code=201)
async def create_items_bulk(data: dict, db: AsyncSession = Depends(get_db)):
    texts = data.get("items", [])
    category = data.get("category")
    if not texts:
        raise HTTPException(400, "Lista vazia")
    return await service.create_items_bulk(db, texts, category)


@router.patch("/{item_id}", response_model=ShoppingItemResponse)
async def update_item(item_id: str, data: ShoppingItemUpdate, db: AsyncSession = Depends(get_db)):
    item = await service.update_item(db, item_id, data)
    if not item:
        raise HTTPException(404, "Item não encontrado")
    return item


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: str, db: AsyncSession = Depends(get_db)):
    if not await service.delete_item(db, item_id):
        raise HTTPException(404, "Item não encontrado")


@router.post("/clear-done")
async def clear_done(db: AsyncSession = Depends(get_db)):
    count = await service.clear_done(db)
    return {"cleared": count}
