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
    from app.features.tasks.models import Task, Checklist, TaskLink, TaskImage, WaProcessed  # noqa: F401
    from app.features.integrations.models import PendingCalendarEvent  # noqa: F401
    from app.features.notes.models import Note  # noqa: F401
    from app.features.habits.models import Habit, HabitLog, DayScore  # noqa: F401
    from app.features.shopping.models import ShoppingItem  # noqa: F401

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
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN remind_at TEXT"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN effort INTEGER DEFAULT 1"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE habits ADD COLUMN icon TEXT DEFAULT '⭐'"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE habits ADD COLUMN difficulty INTEGER DEFAULT 2"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE habits ADD COLUMN weekly_target INTEGER"))
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

    async with AsyncSessionLocal() as db:
        from app.features.habits.models import Habit
        result = await db.execute(select(Habit).limit(1))
        if not result.scalar_one_or_none():
            now = now_brt().isoformat()
            db.add(Habit(id="habit-natacao", name="Natação", icon="🏊", frequency="mon,wed", difficulty=2, active=1, created_at=now))
            db.add(Habit(id="habit-corrida", name="Corrida", icon="🏃", frequency="flex", difficulty=2, active=1, created_at=now))
            await db.commit()

    from app.scheduler import start_scheduler
    start_scheduler()

    yield


app = FastAPI(title="Pedro OS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.features.tasks.router import router as tasks_router, checklist_router, links_router, images_router
from app.features.tasks.sse import router as sse_router
from app.features.projects.router import router as projects_router
from app.features.whatsapp.router import router as whatsapp_router
from app.features.integrations.router import router as integrations_router
from app.features.notes.router import router as notes_router
from app.features.habits.router import router as habits_router
from app.features.shopping.router import router as shopping_router

app.include_router(tasks_router)
app.include_router(checklist_router)
app.include_router(links_router)
app.include_router(images_router)
app.include_router(sse_router)
app.include_router(projects_router)
app.include_router(whatsapp_router)
app.include_router(integrations_router)
app.include_router(notes_router)
app.include_router(habits_router)
app.include_router(shopping_router)


UPLOADS_DIR = os.environ.get("UPLOADS_DIR") or os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_dashboard():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.post("/api/scheduler/test-daily")
async def test_daily():
    from app.scheduler import _build_daily_summary
    from app.features.whatsapp.sender import send_whatsapp
    from app.config import settings
    msg = await _build_daily_summary()
    jid = settings.my_whatsapp_jid or settings.alfred_group_jid
    if jid:
        await send_whatsapp(jid, msg)
    return JSONResponse({"ok": True, "preview": msg})


@app.post("/api/scheduler/test-tomorrow")
async def test_tomorrow():
    from app.scheduler import _build_tomorrow_meetings
    from app.features.whatsapp.sender import send_whatsapp
    from app.config import settings
    msg = await _build_tomorrow_meetings()
    jid = settings.my_whatsapp_jid or settings.alfred_group_jid
    if jid:
        await send_whatsapp(jid, msg)
    return JSONResponse({"ok": True, "preview": msg})


@app.post("/api/scheduler/test-weekly")
async def test_weekly():
    from app.scheduler import _build_weekly_summary
    from app.features.whatsapp.sender import send_whatsapp
    from app.config import settings
    msg = await _build_weekly_summary()
    jid = settings.my_whatsapp_jid or settings.alfred_group_jid
    if jid:
        await send_whatsapp(jid, msg)
    return JSONResponse({"ok": True, "preview": msg})


@app.post("/api/scheduler/test-eod")
async def test_eod():
    from app.scheduler import _build_eod_summary
    from app.features.whatsapp.sender import send_whatsapp
    from app.config import settings
    msg = await _build_eod_summary()
    jid = settings.my_whatsapp_jid or settings.alfred_group_jid
    if jid:
        await send_whatsapp(jid, msg)
    return JSONResponse({"ok": True, "preview": msg})


@app.get("/api/health")
async def health():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return JSONResponse({"status": "ok", "db": db_status, "ts": now_brt().isoformat()})
