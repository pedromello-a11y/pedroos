import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.db import Base, get_db
from app.shared.dates import now_brt

TEST_DB = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(TEST_DB)
_SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def override_db():
    async with _SessionLocal() as s:
        yield s


app.dependency_overrides[get_db] = override_db


@pytest_asyncio.fixture(autouse=True)
async def _reset_db():
    from app.features.projects.models import Project  # noqa
    from app.features.tasks.models import Task, Checklist, TaskLink, WaProcessed  # noqa
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _SessionLocal() as db:
        from app.features.projects.models import Project
        db.add(Project(
            slug="fire-26", name="FIRE 26", description="Teste",
            color="#EF4444", position=0, created_at=now_brt().isoformat(),
        ))
        await db.commit()

    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


AI_RESPONSE = {
    "title": "Editar abertura FIRE",
    "project_slug": "fire-26",
    "deadline": "2026-05-14",
    "priority": "p1",
}


# ── webhook creates task ──────────────────────────────────────────────────
async def test_webhook_creates_task(client):
    with patch("app.features.whatsapp.ai_parser.parse_message", return_value=AI_RESPONSE), \
         patch("app.features.whatsapp.sender.send_whatsapp", return_value=True):
        async with client as c:
            r = await c.post("/api/whatsapp/webhook", json={
                "message_id": "msg001",
                "from": "5531999999999@s.whatsapp.net",
                "text": "editar abertura do FIRE até quinta urgente",
            })
            assert r.status_code == 200
            assert r.json()["ok"] is True

            tasks = (await c.get("/api/tasks?reviewed=0")).json()
            assert len(tasks) == 1
            assert tasks[0]["title"] == "Editar abertura FIRE"
            assert tasks[0]["project_slug"] == "fire-26"
            assert tasks[0]["source"] == "whatsapp"


# ── webhook idempotency ───────────────────────────────────────────────────
async def test_webhook_idempotency(client):
    with patch("app.features.whatsapp.ai_parser.parse_message", return_value=AI_RESPONSE), \
         patch("app.features.whatsapp.sender.send_whatsapp", return_value=True):
        async with client as c:
            payload = {
                "message_id": "dup-msg",
                "from": "5531999999999@s.whatsapp.net",
                "text": "tarefa duplicada",
            }
            r1 = await c.post("/api/whatsapp/webhook", json=payload)
            r2 = await c.post("/api/whatsapp/webhook", json=payload)

            assert r1.json()["ok"] is True
            assert r2.json().get("duplicate") is True

            tasks = (await c.get("/api/tasks")).json()
            assert len(tasks) == 1


# ── comando hoje ──────────────────────────────────────────────────────────
async def test_comando_hoje(client):
    with patch("app.features.whatsapp.sender.send_whatsapp", return_value=True):
        async with client as c:
            r = await c.post("/api/whatsapp/webhook", json={
                "message_id": "cmd-hoje",
                "from": "5531999999999@s.whatsapp.net",
                "text": "hoje",
            })
            assert r.status_code == 200
            assert "📋" in r.json().get("response", "")


# ── comando inbox ─────────────────────────────────────────────────────────
async def test_comando_inbox(client):
    with patch("app.features.whatsapp.sender.send_whatsapp", return_value=True):
        async with client as c:
            r = await c.post("/api/whatsapp/webhook", json={
                "message_id": "cmd-inbox",
                "from": "5531999999999@s.whatsapp.net",
                "text": "inbox",
            })
            assert r.status_code == 200
            assert "📥" in r.json().get("response", "")
