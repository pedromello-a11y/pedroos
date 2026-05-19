from pydantic import BaseModel
from typing import Optional


class ShoppingItemCreate(BaseModel):
    text: str
    category: Optional[str] = None


class ShoppingItemUpdate(BaseModel):
    text: Optional[str] = None
    category: Optional[str] = None
    done: Optional[int] = None


class ShoppingItemResponse(BaseModel):
    id: str
    text: str
    category: Optional[str] = None
    done: int
    created_at: str
    completed_at: Optional[str] = None

    model_config = {"from_attributes": True}
