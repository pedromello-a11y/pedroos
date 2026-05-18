"""Simple SSE broadcaster for real-time inbox updates."""
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["sse"])

_subscribers: list[asyncio.Queue] = []


def broadcast(event_type: str, data: str = "1"):
    msg = f"event: {event_type}\ndata: {data}\n\n"
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


@router.get("/api/sse/inbox")
async def task_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=20)
    _subscribers.append(q)

    async def generator():
        try:
            yield "event: connected\ndata: ok\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if q in _subscribers:
                _subscribers.remove(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
