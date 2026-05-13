import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.db import Base, get_db

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
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── health ────────────────────────────────────────────────────────────────
async def test_health(client):
    async with client as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── create + list ─────────────────────────────────────────────────────────
async def test_create_and_list_task(client):
    async with client as c:
        r = await c.post("/api/tasks", json={"title": "Fazer abertura FIRE", "reviewed": 1})
        assert r.status_code == 201
        task = r.json()
        assert task["title"] == "Fazer abertura FIRE"
        assert len(task["short_id"]) == 4

        r = await c.get("/api/tasks")
        assert len(r.json()) == 1


# ── review idempotency ────────────────────────────────────────────────────
async def test_review_idempotent(client):
    async with client as c:
        r = await c.post("/api/tasks", json={"title": "Inbox task", "reviewed": 0})
        tid = r.json()["id"]

        r1 = await c.post(f"/api/tasks/{tid}/review")
        assert r1.json()["reviewed"] == 1
        ts1 = r1.json()["reviewed_at"]

        r2 = await c.post(f"/api/tasks/{tid}/review")
        assert r2.json()["reviewed_at"] == ts1  # unchanged


# ── done ─────────────────────────────────────────────────────────────────
async def test_done_task(client):
    async with client as c:
        r = await c.post("/api/tasks", json={"title": "Tarefa"})
        tid = r.json()["id"]
        r = await c.post(f"/api/tasks/{tid}/done")
        assert r.json()["status"] == "done"
        assert r.json()["completed_at"] is not None


# ── snooze ────────────────────────────────────────────────────────────────
async def test_snooze_task(client):
    async with client as c:
        r = await c.post("/api/tasks", json={"title": "Tarefa"})
        tid = r.json()["id"]
        r = await c.post(f"/api/tasks/{tid}/snooze", json={"days": 2})
        assert r.json()["snoozed_until"] is not None


# ── filter by reviewed ────────────────────────────────────────────────────
async def test_filter_reviewed(client):
    async with client as c:
        await c.post("/api/tasks", json={"title": "Inbox", "reviewed": 0})
        await c.post("/api/tasks", json={"title": "Reviewed", "reviewed": 1})

        inbox = (await c.get("/api/tasks?reviewed=0")).json()
        done = (await c.get("/api/tasks?reviewed=1")).json()
        assert len(inbox) == 1 and inbox[0]["title"] == "Inbox"
        assert len(done) == 1 and done[0]["title"] == "Reviewed"


# ── checklist cascade delete ──────────────────────────────────────────────
async def test_cascade_delete(client):
    async with client as c:
        r = await c.post("/api/tasks", json={"title": "Task com tudo"})
        tid = r.json()["id"]

        ci = await c.post(f"/api/tasks/{tid}/checklist", json={"text": "item 1"})
        assert ci.status_code == 201

        li = await c.post(f"/api/tasks/{tid}/links", json={"url": "https://example.com", "label": "Drive"})
        assert li.status_code == 201

        r = await c.delete(f"/api/tasks/{tid}")
        assert r.status_code == 204

        r = await c.get(f"/api/tasks/{tid}")
        assert r.status_code == 404


# ── task detail includes checklist + links ────────────────────────────────
async def test_task_detail(client):
    async with client as c:
        r = await c.post("/api/tasks", json={"title": "Detalhe"})
        tid = r.json()["id"]
        await c.post(f"/api/tasks/{tid}/checklist", json={"text": "Passo 1"})
        await c.post(f"/api/tasks/{tid}/links", json={"url": "https://drive.com", "label": "Drive"})

        r = await c.get(f"/api/tasks/{tid}")
        assert r.status_code == 200
        detail = r.json()
        assert len(detail["checklist"]) == 1
        assert len(detail["links"]) == 1


# ── projects CRUD ─────────────────────────────────────────────────────────
async def test_projects_list_empty(client):
    async with client as c:
        r = await c.get("/api/projects")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


async def test_patch_task(client):
    async with client as c:
        r = await c.post("/api/tasks", json={"title": "Original"})
        tid = r.json()["id"]
        r = await c.patch(f"/api/tasks/{tid}", json={"title": "Atualizado", "priority": "p1"})
        assert r.json()["title"] == "Atualizado"
        assert r.json()["priority"] == "p1"
