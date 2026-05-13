import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from app.config import settings
from app.db import engine, Base, AsyncSessionLocal
from app.shared.dates import now_brt

SEED_PROJECTS = [
    ("galaxy-26", "Galaxy 26", "Evento corporativo com vídeos personalizados", "#8B5CF6", 0),
    ("fire-26",   "FIRE 26",   "Evento principal Hotmart, filme de abertura",   "#EF4444", 1),
    ("spark",     "Spark",     "Evento menor, screensaver e countdown",          "#F59E0B", 2),
    ("hotmart",   "Hotmart",   "Demandas gerais da marca",                       "#FF4000", 3),
    ("motion-kit","Motion Kit","Sistema de componentes reutilizáveis",           "#10B981", 4),
    ("aftermovie-q1","Aftermovie Q1","Vídeo de retrospectiva do trimestre",      "#06B6D4", 5),
    ("pessoal",   "Pessoal",   "Tarefas pessoais e administrativas",             "#6B7280", 6),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # register models
    from app.features.projects.models import Project
    from app.features.tasks.models import Task, Checklist, TaskLink, WaProcessed  # noqa: F401
    from app.features.integrations.models import PendingCalendarEvent  # noqa: F401

    os.makedirs("data", exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # add jira_key column if it doesn't exist yet (sqlite doesn't support IF NOT EXISTS on ADD COLUMN)
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN jira_key TEXT"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN estimated_hours REAL"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN actual_hours REAL"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN position INTEGER"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN status_note TEXT"))
        except Exception:
            pass

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).limit(1))
        if not result.scalar_one_or_none():
            now = now_brt().isoformat()
            for slug, name, desc, color, pos in SEED_PROJECTS:
                db.add(Project(
                    slug=slug, name=name, description=desc,
                    color=color, position=pos, created_at=now,
                ))
            await db.commit()

    yield


app = FastAPI(title="Pedro OS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.features.tasks.router import router as tasks_router, checklist_router, links_router
from app.features.projects.router import router as projects_router
from app.features.whatsapp.router import router as whatsapp_router
from app.features.integrations.router import router as integrations_router

app.include_router(tasks_router)
app.include_router(checklist_router)
app.include_router(links_router)
app.include_router(projects_router)
app.include_router(whatsapp_router)
app.include_router(integrations_router)


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_dashboard():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/api/health")
async def health():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return JSONResponse({"status": "ok", "db": db_status, "ts": now_brt().isoformat()})
