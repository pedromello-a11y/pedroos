from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.features.projects import service
from app.features.projects.schemas import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    active: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_projects(db, active=active)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_project(db, data)


@router.patch("/{slug}", response_model=ProjectResponse)
async def update_project(slug: str, data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    proj = await service.update_project(db, slug, data)
    if not proj:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return proj


@router.delete("/{slug}", status_code=204)
async def delete_project(slug: str, db: AsyncSession = Depends(get_db)):
    result = await service.delete_project(db, slug)
    if result is False:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    if result is None:
        raise HTTPException(status_code=400, detail="Projeto ativo ou com tarefas pendentes não pode ser removido")
