"""
Router de saúde — Pedro Score, Oura Ring, Medicação, Check-in Mental, Alertas, Correlações.
"""
import json
import uuid
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.shared.dates import now_brt

from .models import (
    OuraDaily, Medication, MedicationLog, MentalCheckin,
    HealthScore, HealthAlert, HealthCorrelation, OuraToken,
)
from .schemas import (
    MedicationCreate, MedicationResponse, MedicationLogCreate, MedicationLogResponse,
    CheckinCreate, CheckinUpdate, CheckinResponse,
    HealthScoreResponse, HealthScoreHeader,
    AlertResponse, CorrelationResponse,
    OuraDailyResponse, HealthDashboard,
)

router = APIRouter(prefix="/api/health", tags=["health"])


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard", response_model=HealthDashboard)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """Retorna tudo que o frontend da aba Saúde precisa em uma chamada."""
    today = now_brt().date().isoformat()

    # Scores recentes
    res = await db.execute(
        select(HealthScore).where(HealthScore.date <= today).order_by(HealthScore.date.desc()).limit(30)
    )
    recent_scores = res.scalars().all()

    # Score hoje
    today_score = next((s for s in recent_scores if s.date == today), None)

    # Oura hoje
    res2 = await db.execute(select(OuraDaily).where(OuraDaily.date == today))
    oura_today = res2.scalar_one_or_none()

    # Check-in hoje
    res3 = await db.execute(select(MentalCheckin).where(MentalCheckin.date == today))
    checkin_today = res3.scalar_one_or_none()

    # Medicamentos ativos
    res4 = await db.execute(select(Medication).where(Medication.active == 1).order_by(Medication.position))
    meds = res4.scalars().all()

    # Logs de medicação hoje
    res5 = await db.execute(select(MedicationLog).where(MedicationLog.date == today))
    med_logs_today = res5.scalars().all()

    # Alertas ativos
    res6 = await db.execute(
        select(HealthAlert).where(HealthAlert.active == 1).order_by(HealthAlert.triggered_at.desc())
    )
    alerts = res6.scalars().all()

    # Top correlações
    res7 = await db.execute(
        select(HealthCorrelation).order_by(
            func.abs(HealthCorrelation.effect_size).desc()
        ).limit(10)
    )
    correlations = res7.scalars().all()

    return HealthDashboard(
        today_score=_parse_score(today_score),
        oura_today=OuraDailyResponse.model_validate(oura_today) if oura_today else None,
        checkin_today=_parse_checkin(checkin_today),
        medications=[MedicationResponse.model_validate(m) for m in meds],
        medication_logs_today=[MedicationLogResponse.model_validate(l) for l in med_logs_today],
        active_alerts=[_parse_alert(a) for a in alerts],
        recent_scores=[_parse_score(s) for s in recent_scores],
        top_correlations=[_parse_correlation(c) for c in correlations],
    )


@router.get("/score/header", response_model=HealthScoreHeader)
async def get_score_header(db: AsyncSession = Depends(get_db)):
    """Endpoint leve para o header do dashboard — score de hoje + alertas ativos."""
    today = now_brt().date().isoformat()

    res = await db.execute(select(HealthScore).where(HealthScore.date == today))
    hs = res.scalar_one_or_none()

    res2 = await db.execute(
        select(func.count()).where(HealthAlert.active == 1, HealthAlert.acknowledged == 0)
    )
    alert_count = res2.scalar() or 0

    return HealthScoreHeader(
        date=today,
        score_total=hs.score_total if hs else None,
        score_body=hs.score_body if hs else None,
        score_mind=hs.score_mind if hs else None,
        alert_count=alert_count,
    )


@router.post("/score/calculate")
async def trigger_score_calculation(
    target_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Dispara cálculo do score manualmente."""
    from .score_engine import calculate_daily_score
    result = await calculate_daily_score(db, target_date)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# MEDICAMENTOS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/medications", response_model=List[MedicationResponse])
async def list_medications(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
):
    q = select(Medication).order_by(Medication.position)
    if not include_archived:
        q = q.where(Medication.active == 1)
    res = await db.execute(q)
    return [MedicationResponse.model_validate(m) for m in res.scalars().all()]


@router.post("/medications", response_model=MedicationResponse)
async def create_medication(data: MedicationCreate, db: AsyncSession = Depends(get_db)):
    med = Medication(
        id=str(uuid.uuid4()),
        **data.model_dump(),
    )
    db.add(med)
    await db.commit()
    await db.refresh(med)
    return MedicationResponse.model_validate(med)


@router.patch("/medications/{med_id}", response_model=MedicationResponse)
async def update_medication(
    med_id: str, data: MedicationCreate, db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(Medication).where(Medication.id == med_id))
    med = res.scalar_one_or_none()
    if not med:
        raise HTTPException(404, "Medicamento não encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(med, k, v)
    await db.commit()
    await db.refresh(med)
    return MedicationResponse.model_validate(med)


@router.delete("/medications/{med_id}")
async def archive_medication(med_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Medication).where(Medication.id == med_id))
    med = res.scalar_one_or_none()
    if not med:
        raise HTTPException(404, "Medicamento não encontrado")
    med.active = 0
    await db.commit()
    return {"ok": True}


@router.post("/medications/log", response_model=MedicationLogResponse)
async def log_medication(data: MedicationLogCreate, db: AsyncSession = Depends(get_db)):
    log = MedicationLog(
        id=str(uuid.uuid4()),
        medication_id=data.medication_id,
        date=data.date or now_brt().date().isoformat(),
        quantity=data.quantity,
        time=data.time or now_brt().strftime("%H:%M"),
        note=data.note,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    # Recalcula score do dia
    try:
        from .score_engine import calculate_daily_score
        await calculate_daily_score(db, log.date)
    except Exception:
        pass

    return MedicationLogResponse.model_validate(log)


@router.get("/medications/logs", response_model=List[MedicationLogResponse])
async def list_medication_logs(
    date: Optional[str] = None,
    medication_id: Optional[str] = None,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    today = now_brt().date().isoformat()
    start = (now_brt().date() - timedelta(days=days)).isoformat()

    q = select(MedicationLog).where(MedicationLog.date >= start).order_by(MedicationLog.date.desc())
    if date:
        q = select(MedicationLog).where(MedicationLog.date == date)
    if medication_id:
        q = q.where(MedicationLog.medication_id == medication_id)

    res = await db.execute(q)
    return [MedicationLogResponse.model_validate(l) for l in res.scalars().all()]


@router.delete("/medications/log/{log_id}")
async def delete_medication_log(log_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(MedicationLog).where(MedicationLog.id == log_id))
    log = res.scalar_one_or_none()
    if not log:
        raise HTTPException(404, "Log não encontrado")
    await db.delete(log)
    await db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# CHECK-IN MENTAL
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/checkin", response_model=CheckinResponse)
async def create_checkin(data: CheckinCreate, db: AsyncSession = Depends(get_db)):
    today = now_brt().date().isoformat()
    checkin_date = data.date or today

    # Verifica se já existe
    res = await db.execute(select(MentalCheckin).where(MentalCheckin.date == checkin_date))
    existing = res.scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"Check-in para {checkin_date} já existe. Use PATCH para atualizar.")

    streak = await _calc_checkin_streak(db, checkin_date)

    checkin = MentalCheckin(
        id=str(uuid.uuid4()),
        date=checkin_date,
        mood=data.mood,
        energy=data.energy,
        stress=data.stress,
        pain=data.pain,
        sleep_hours=data.sleep_hours,
        exercise=data.exercise,
        alcohol=data.alcohol,
        cigarettes=data.cigarettes,
        social=data.social,
        food_quality=data.food_quality,
        note_text=data.note_text,
        tags=json.dumps(data.tags) if data.tags else None,
        streak=streak,
        source=data.source,
        created_at=now_brt().isoformat(),
    )
    db.add(checkin)
    await db.commit()
    await db.refresh(checkin)

    # Recalcula score do dia
    try:
        from .score_engine import calculate_daily_score
        from .alert_engine import check_alerts
        await calculate_daily_score(db, checkin_date)
        await check_alerts(db)
    except Exception:
        pass

    return _parse_checkin(checkin)


@router.patch("/checkin/{checkin_date}", response_model=CheckinResponse)
async def update_checkin(
    checkin_date: str, data: CheckinUpdate, db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(MentalCheckin).where(MentalCheckin.date == checkin_date))
    checkin = res.scalar_one_or_none()
    if not checkin:
        raise HTTPException(404, "Check-in não encontrado")

    for field, val in data.model_dump(exclude_unset=True).items():
        if field == "tags" and val is not None:
            setattr(checkin, "tags", json.dumps(val))
        else:
            setattr(checkin, field, val)

    await db.commit()
    await db.refresh(checkin)

    # Recalcula score
    try:
        from .score_engine import calculate_daily_score
        await calculate_daily_score(db, checkin_date)
    except Exception:
        pass

    return _parse_checkin(checkin)


@router.get("/checkin/today", response_model=Optional[CheckinResponse])
async def get_today_checkin(db: AsyncSession = Depends(get_db)):
    today = now_brt().date().isoformat()
    res = await db.execute(select(MentalCheckin).where(MentalCheckin.date == today))
    checkin = res.scalar_one_or_none()
    if not checkin:
        return None
    return _parse_checkin(checkin)


@router.get("/checkins", response_model=List[CheckinResponse])
async def list_checkins(days: int = 30, db: AsyncSession = Depends(get_db)):
    start = (now_brt().date() - timedelta(days=days)).isoformat()
    res = await db.execute(
        select(MentalCheckin).where(MentalCheckin.date >= start).order_by(MentalCheckin.date.desc())
    )
    return [_parse_checkin(c) for c in res.scalars().all()]


# ══════════════════════════════════════════════════════════════════════════════
# OURA RING
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/oura/auth")
async def oura_auth():
    """Redireciona para OAuth2 do Oura."""
    from .oura_sync import get_oura_auth_url
    url = await get_oura_auth_url()
    return RedirectResponse(url)


@router.get("/oura/callback")
async def oura_callback(code: str, db: AsyncSession = Depends(get_db)):
    """Callback OAuth2 — troca code por token e persiste."""
    from .oura_sync import handle_oura_callback
    result = await handle_oura_callback(db, code)
    return result


@router.get("/oura/status")
async def oura_status(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(OuraToken).where(OuraToken.id == 1))
    token = res.scalar_one_or_none()
    if not token or not token.access_token:
        return {"connected": False}
    return {
        "connected": True,
        "expires_at": token.expires_at,
    }


@router.post("/oura/sync")
async def sync_oura(days_back: int = 7, db: AsyncSession = Depends(get_db)):
    """Dispara sincronização manual com o Oura."""
    from .oura_sync import sync_daily
    result = await sync_daily(db, days_back=days_back)
    return result


@router.get("/oura/today", response_model=Optional[OuraDailyResponse])
async def get_oura_today(db: AsyncSession = Depends(get_db)):
    today = now_brt().date().isoformat()
    res = await db.execute(select(OuraDaily).where(OuraDaily.date == today))
    oura = res.scalar_one_or_none()
    if not oura:
        return None
    return OuraDailyResponse.model_validate(oura)


@router.get("/oura/range", response_model=List[OuraDailyResponse])
async def get_oura_range(
    start_date: str,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    if not end_date:
        end_date = now_brt().date().isoformat()
    res = await db.execute(
        select(OuraDaily).where(
            OuraDaily.date >= start_date,
            OuraDaily.date <= end_date,
        ).order_by(OuraDaily.date.desc())
    )
    return [OuraDailyResponse.model_validate(r) for r in res.scalars().all()]


# ══════════════════════════════════════════════════════════════════════════════
# ALERTAS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/alerts", response_model=List[AlertResponse])
async def list_alerts(
    include_resolved: bool = False,
    db: AsyncSession = Depends(get_db),
):
    q = select(HealthAlert).order_by(HealthAlert.triggered_at.desc())
    if not include_resolved:
        q = q.where(HealthAlert.active == 1)
    res = await db.execute(q)
    return [_parse_alert(a) for a in res.scalars().all()]


@router.post("/alerts/check")
async def trigger_alert_check(db: AsyncSession = Depends(get_db)):
    """Dispara verificação de alertas manualmente."""
    from .alert_engine import check_alerts
    created = await check_alerts(db)
    return {"ok": True, "new_alerts": len(created), "alerts": created}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(HealthAlert).where(HealthAlert.id == alert_id))
    alert = res.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alerta não encontrado")
    alert.acknowledged = 1
    alert.active = 0
    await db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# CORRELAÇÕES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/correlations", response_model=List[CorrelationResponse])
async def list_correlations(db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(HealthCorrelation).order_by(
            func.abs(HealthCorrelation.effect_size).desc()
        ).limit(20)
    )
    return [_parse_correlation(c) for c in res.scalars().all()]


@router.post("/correlations/calculate")
async def trigger_correlations(days: int = 30, db: AsyncSession = Depends(get_db)):
    from .correlation_engine import calculate_correlations
    result = await calculate_correlations(db, days=days)
    return {"ok": True, "correlations": len(result)}


# ══════════════════════════════════════════════════════════════════════════════
# SCORES (range)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/scores", response_model=List[HealthScoreResponse])
async def list_scores(days: int = 30, db: AsyncSession = Depends(get_db)):
    start = (now_brt().date() - timedelta(days=days)).isoformat()
    res = await db.execute(
        select(HealthScore).where(HealthScore.date >= start).order_by(HealthScore.date.desc())
    )
    return [_parse_score(s) for s in res.scalars().all()]


# ══════════════════════════════════════════════════════════════════════════════
# UTILS INTERNOS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_score(hs) -> Optional[HealthScoreResponse]:
    if not hs:
        return None
    components = None
    if hs.components:
        try:
            components = json.loads(hs.components)
        except Exception:
            pass
    return HealthScoreResponse(
        date=hs.date,
        score_total=hs.score_total,
        score_body=hs.score_body,
        score_mind=hs.score_mind,
        score_movement=hs.score_movement,
        score_productivity=hs.score_productivity,
        score_selfcare=hs.score_selfcare,
        components=components,
        calculated_at=hs.calculated_at,
    )


def _parse_checkin(ci) -> Optional[CheckinResponse]:
    if not ci:
        return None
    tags = None
    if ci.tags:
        try:
            tags = json.loads(ci.tags)
        except Exception:
            tags = ci.tags
    return CheckinResponse(
        id=ci.id,
        date=ci.date,
        mood=ci.mood,
        energy=ci.energy,
        stress=ci.stress,
        pain=ci.pain,
        sleep_hours=ci.sleep_hours,
        exercise=ci.exercise,
        alcohol=ci.alcohol,
        cigarettes=ci.cigarettes,
        social=ci.social,
        food_quality=ci.food_quality,
        note_text=ci.note_text,
        note_ai_summary=ci.note_ai_summary,
        tags=tags,
        streak=ci.streak or 0,
        source=ci.source or "web",
    )


def _parse_alert(a) -> AlertResponse:
    data = None
    if a.data:
        try:
            data = json.loads(a.data)
        except Exception:
            pass
    return AlertResponse(
        id=a.id,
        type=a.type,
        severity=a.severity,
        title=a.title,
        description=a.description,
        data=data,
        active=a.active,
        acknowledged=a.acknowledged,
        triggered_at=a.triggered_at,
    )


def _parse_correlation(c) -> CorrelationResponse:
    return CorrelationResponse(
        id=c.id,
        factor_a=c.factor_a,
        factor_b=c.factor_b,
        correlation=c.correlation,
        effect_size=c.effect_size,
        description=c.description,
        sample_size=c.sample_size,
        confidence=c.confidence,
        updated_at=c.updated_at,
    )


async def _calc_checkin_streak(db: AsyncSession, today: str) -> int:
    """Conta dias consecutivos de check-in terminando ontem."""
    streak = 0
    for i in range(1, 366):
        d = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
        res = await db.execute(
            select(MentalCheckin.id).where(MentalCheckin.date == d)
        )
        if not res.scalar_one_or_none():
            break
        streak += 1
    return streak + 1  # +1 pelo dia de hoje
