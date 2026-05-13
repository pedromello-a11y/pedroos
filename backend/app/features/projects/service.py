import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.features.projects.models import Project
from app.features.tasks.models import Task
from app.features.projects.schemas import ProjectCreate, ProjectUpdate
from app.shared.ids import make_id
from app.shared.dates import now_brt


async def list_projects(db: AsyncSession, active: Optional[int] = None) -> list[Project]:
    q = select(Project)
    if active is not None:
        q = q.where(Project.active == active)
    q = q.order_by(Project.position, Project.name)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_project(db: AsyncSession, slug: str) -> Optional[Project]:
    result = await db.execute(select(Project).where(Project.slug == slug))
    return result.scalar_one_or_none()


async def create_project(db: AsyncSession, data: ProjectCreate) -> Project:
    slug = _make_slug(data.name)
    if await get_project(db, slug):
        slug = f"{slug}-{make_id()[:4]}"

    proj = Project(
        slug=slug,
        name=data.name,
        description=data.description,
        deadline=data.deadline,
        color=data.color,
        position=data.position,
        created_at=now_brt().isoformat(),
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def update_project(db: AsyncSession, slug: str, data: ProjectUpdate) -> Optional[Project]:
    proj = await get_project(db, slug)
    if not proj:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(proj, field, value)
    await db.commit()
    await db.refresh(proj)
    return proj


async def delete_project(db: AsyncSession, slug: str):
    """Returns True on success, None on constraint violation, False if not found."""
    proj = await get_project(db, slug)
    if not proj:
        return False
    if proj.active:
        return None
    count_result = await db.execute(
        select(func.count()).where(Task.project_slug == slug, Task.status != "done")
    )
    if (count_result.scalar() or 0) > 0:
        return None
    await db.delete(proj)
    await db.commit()
    return True


def _make_slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s\-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug[:50]
