import httpx
from app.config import settings


async def send_whatsapp(to: str, text: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.wa_gateway_url}/send",
                json={"to": to, "text": text},
            )
            return resp.status_code == 200
    except Exception as exc:
        print(f"[sender] failed to send to {to}: {exc}")
        return False
