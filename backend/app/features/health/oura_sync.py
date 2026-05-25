"""
Sincronização com a API Oura Ring v2.
OAuth2 com refresh token — tokens armazenados no DB (OuraToken, id=1).
"""
import json
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.shared.dates import now_brt

logger = logging.getLogger(__name__)

OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
OURA_API_BASE = "https://api.ouraring.com/v2"


async def _get_token(db: AsyncSession) -> str | None:
    """Retorna access_token válido, renovando se necessário."""
    from app.features.health.models import OuraToken

    res = await db.execute(select(OuraToken).where(OuraToken.id == 1))
    token_row = res.scalar_one_or_none()

    if not token_row:
        # Tenta usar refresh_token das settings (configurado no Fly.io)
        refresh = getattr(settings, "oura_refresh_token", "")
        if not refresh:
            logger.warning("[oura] nenhum refresh_token configurado")
            return None
        # Bootstrap: cria linha com refresh_token das settings
        token_row = OuraToken(id=1, refresh_token=refresh)
        db.add(token_row)
        await db.flush()

    # Verifica validade do access_token
    if token_row.access_token and token_row.expires_at:
        try:
            expires = datetime.fromisoformat(token_row.expires_at)
            if now_brt() < expires - timedelta(minutes=5):
                return token_row.access_token
        except ValueError:
            pass

    # Renova via refresh_token
    if not token_row.refresh_token:
        logger.warning("[oura] sem refresh_token para renovar")
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                OURA_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token_row.refresh_token,
                    "client_id": settings.oura_client_id,
                    "client_secret": settings.oura_client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        token_row.access_token = data["access_token"]
        token_row.refresh_token = data.get("refresh_token", token_row.refresh_token)
        expires_in = data.get("expires_in", 3600)
        token_row.expires_at = (now_brt() + timedelta(seconds=expires_in)).isoformat()
        await db.commit()
        logger.info("[oura] token renovado")
        return token_row.access_token

    except Exception as exc:
        logger.error(f"[oura] erro ao renovar token: {exc}")
        return None


async def _fetch_oura(access_token: str, path: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{OURA_API_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def sync_daily(db: AsyncSession, days_back: int = 7) -> dict:
    """
    Busca dados de sono, readiness e atividade do Oura e persiste em OuraDaily.
    Retorna dict com quantidade de registros inseridos/atualizados.
    """
    from app.features.health.models import OuraDaily

    access_token = await _get_token(db)
    if not access_token:
        return {"ok": False, "error": "sem token Oura"}

    start_date = (now_brt().date() - timedelta(days=days_back)).isoformat()
    end_date = now_brt().date().isoformat()
    params = {"start_date": start_date, "end_date": end_date}

    # Coleta dados de todas as categorias
    sleep_data: dict[str, dict] = {}
    readiness_data: dict[str, dict] = {}
    activity_data: dict[str, dict] = {}

    try:
        sl = await _fetch_oura(access_token, "/usercollection/daily_sleep", params)
        for item in sl.get("data", []):
            d = item.get("day") or item.get("date", "")
            if d:
                sleep_data[d] = item
    except Exception as exc:
        logger.warning(f"[oura] erro sleep: {exc}")

    try:
        rd = await _fetch_oura(access_token, "/usercollection/daily_readiness", params)
        for item in rd.get("data", []):
            d = item.get("day") or item.get("date", "")
            if d:
                readiness_data[d] = item
    except Exception as exc:
        logger.warning(f"[oura] erro readiness: {exc}")

    try:
        ac = await _fetch_oura(access_token, "/usercollection/daily_activity", params)
        for item in ac.get("data", []):
            d = item.get("day") or item.get("date", "")
            if d:
                activity_data[d] = item
    except Exception as exc:
        logger.warning(f"[oura] erro activity: {exc}")

    # Tenta buscar HRV do sleep_periods para calcular rmssd
    hrv_by_date: dict[str, float] = {}
    try:
        sp = await _fetch_oura(access_token, "/usercollection/sleep", params)
        for item in sp.get("data", []):
            d = item.get("day") or ""
            hrv = item.get("average_hrv")
            if d and hrv is not None:
                hrv_by_date[d] = float(hrv)
            rhr = item.get("lowest_heart_rate")
            if d and rhr:
                # Enrich readiness_data com resting HR do sleep
                readiness_data.setdefault(d, {})
                readiness_data[d].setdefault("_resting_hr", float(rhr))
    except Exception as exc:
        logger.warning(f"[oura] erro sleep_periods: {exc}")

    # Merge e upsert
    all_dates = set(sleep_data) | set(readiness_data) | set(activity_data)
    synced_at = now_brt().isoformat()
    upserted = 0

    for date_str in sorted(all_dates):
        sl = sleep_data.get(date_str, {})
        rd = readiness_data.get(date_str, {})
        ac = activity_data.get(date_str, {})

        # Sleep contributors
        sl_contrib = sl.get("contributors", {})
        rd_contrib = rd.get("contributors", {})

        res = await db.execute(select(OuraDaily).where(OuraDaily.date == date_str))
        row = res.scalar_one_or_none()
        if not row:
            row = OuraDaily(date=date_str)
            db.add(row)

        row.sleep_score = sl.get("score")
        row.sleep_duration = _minutes_to_hours(sl.get("total_sleep_duration") or sl_contrib.get("total_sleep") or 0)
        row.rem_sleep = _minutes_to_hours(sl.get("rem_sleep_duration", 0))
        row.deep_sleep = _minutes_to_hours(sl.get("deep_sleep_duration", 0))
        row.sleep_efficiency = sl.get("sleep_efficiency") or sl_contrib.get("efficiency")
        row.sleep_latency = sl.get("latency") or sl.get("onset_latency")
        row.awakenings = sl.get("awake_count") or sl.get("awakenings_count")

        row.readiness_score = rd.get("score")
        row.hrv_balance = rd_contrib.get("hrv_balance")
        row.recovery_index = rd_contrib.get("recovery_index")
        row.resting_hr = rd.get("resting_heart_rate") or rd.get("_resting_hr")
        row.hrv_rmssd = hrv_by_date.get(date_str)

        row.activity_score = ac.get("score")
        row.steps = ac.get("steps")
        row.active_calories = ac.get("active_calories")
        row.total_calories = ac.get("total_calories")
        row.active_time = _seconds_to_minutes(ac.get("high_activity_time", 0) + ac.get("medium_activity_time", 0))
        row.inactivity_alerts = ac.get("inactivity_alerts")

        row.synced_at = synced_at
        raw = {"sleep": sl, "readiness": rd, "activity": ac}
        row.raw_json = json.dumps(raw, default=str)

        upserted += 1

    await db.commit()
    logger.info(f"[oura] sync_daily: {upserted} registros para {start_date}…{end_date}")
    return {"ok": True, "upserted": upserted, "date_range": f"{start_date}…{end_date}"}


def _minutes_to_hours(seconds: int | float | None) -> float | None:
    """Oura v2 retorna durations em segundos — converte para horas."""
    if not seconds:
        return None
    return round(seconds / 3600, 2)


def _seconds_to_minutes(seconds: int | float | None) -> float | None:
    if not seconds:
        return None
    return round(seconds / 60, 1)


async def get_oura_auth_url() -> str:
    """Gera URL de autorização OAuth2 para o Oura."""
    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": settings.oura_client_id,
        "redirect_uri": settings.oura_redirect_uri,
        "scope": "daily heartrate workout tag session",
    }
    return f"https://cloud.ouraring.com/oauth/authorize?{urlencode(params)}"


async def handle_oura_callback(db: AsyncSession, code: str) -> dict:
    """Troca o code pelo access+refresh token e persiste no DB."""
    from app.features.health.models import OuraToken

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            OURA_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oura_redirect_uri,
                "client_id": settings.oura_client_id,
                "client_secret": settings.oura_client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    res = await db.execute(select(OuraToken).where(OuraToken.id == 1))
    row = res.scalar_one_or_none()
    if not row:
        row = OuraToken(id=1)
        db.add(row)

    row.access_token = data["access_token"]
    row.refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 3600)
    row.expires_at = (now_brt() + timedelta(seconds=expires_in)).isoformat()
    await db.commit()

    return {"ok": True, "message": "Token Oura salvo. Pode fechar esta janela."}
