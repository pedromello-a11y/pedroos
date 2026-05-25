"""
Engine de alertas de saúde.
Detecta padrões preocupantes e cria HealthAlert no DB.
Auto-resolve quando condições melhoram.
"""
import json
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.dates import now_brt

logger = logging.getLogger(__name__)


async def check_alerts(db: AsyncSession) -> list[dict]:
    """Verifica todas as condições de alerta e persiste novos alertas. Retorna lista de alertas criados."""
    from app.features.health.models import HealthAlert, MentalCheckin, OuraDaily, MedicationLog, Medication, HealthScore

    today = now_brt().date().isoformat()
    created: list[dict] = []

    # ── 1. low_period: mood ≤ 3 por 2+ dias consecutivos ──────────────────────
    low_mood_days = await _count_consecutive_low_mood(db, today, threshold=3)
    if low_mood_days >= 2:
        alert = await _ensure_alert(
            db=db,
            alert_type="low_period",
            severity="critical",
            title=f"Período difícil detectado — {low_mood_days} dias com humor baixo",
            description="Mood ≤ 3 por múltiplos dias consecutivos. Considera conversar com alguém.",
            data={"days": low_mood_days, "threshold": 3},
        )
        if alert:
            created.append(alert)

    # ── 2. med_consecutive: N+ dias consecutivos com medicamento ──────────────
    res = await db.execute(select(Medication).where(Medication.active == 1))
    meds = [m for m in res.scalars().all() if m.alert_days and m.alert_days > 0]

    for med in meds:
        consec = await _count_consecutive_med_days(db, today, med.id)
        if consec >= med.alert_days:
            alert = await _ensure_alert(
                db=db,
                alert_type="med_consecutive",
                severity="warning",
                title=f"{med.name}: {consec} dias consecutivos",
                description=f"Tomando {med.name} há {consec} dias seguidos (limite configurado: {med.alert_days}).",
                data={"medication_id": med.id, "medication_name": med.name, "days": consec},
            )
            if alert:
                created.append(alert)

    # ── 3. sleep_deprivation: sono < 6h por 2+ dias ──────────────────────────
    short_sleep_days = await _count_consecutive_short_sleep(db, today, min_hours=6.0)
    if short_sleep_days >= 2:
        alert = await _ensure_alert(
            db=db,
            alert_type="sleep_deprivation",
            severity="warning",
            title=f"Privação de sono — {short_sleep_days} noites curtas",
            description="Sono < 6h por múltiplos dias. Prioriza descanso hoje à noite.",
            data={"days": short_sleep_days, "min_hours": 6.0},
        )
        if alert:
            created.append(alert)

    # ── 4. low_score: score < 40 por 2+ dias ─────────────────────────────────
    low_score_days = await _count_consecutive_low_score(db, today, threshold=40)
    if low_score_days >= 2:
        alert = await _ensure_alert(
            db=db,
            alert_type="low_score",
            severity="critical",
            title=f"Score baixo há {low_score_days} dias",
            description="Pedro Score < 40 por múltiplos dias consecutivos. Revisa rotina e hábitos.",
            data={"days": low_score_days, "threshold": 40},
        )
        if alert:
            created.append(alert)

    # ── Auto-resolve alertas que melhoraram ───────────────────────────────────
    await _check_recoveries(db, today)

    await db.commit()
    return created


async def _ensure_alert(
    db: AsyncSession,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    data: dict,
) -> dict | None:
    """Cria alerta se não existe um ativo do mesmo tipo. Retorna None se já existe."""
    from app.features.health.models import HealthAlert

    res = await db.execute(
        select(HealthAlert).where(
            HealthAlert.type == alert_type,
            HealthAlert.active == 1,
            HealthAlert.acknowledged == 0,
        )
    )
    existing = res.scalar_one_or_none()

    if existing:
        # Atualiza description/data caso piore
        existing.title = title
        existing.description = description
        existing.data = json.dumps(data)
        return None  # não é "novo"

    import uuid
    alert = HealthAlert(
        id=str(uuid.uuid4()),
        type=alert_type,
        severity=severity,
        title=title,
        description=description,
        data=json.dumps(data),
        active=1,
        acknowledged=0,
        triggered_at=now_brt().isoformat(),
    )
    db.add(alert)
    logger.info(f"[alerts] novo alerta: {alert_type} — {title}")
    return {"type": alert_type, "severity": severity, "title": title}


async def _check_recoveries(db: AsyncSession, today: str) -> None:
    """Resolve alertas automaticamente quando condições melhoram."""
    from app.features.health.models import HealthAlert, MentalCheckin, OuraDaily, HealthScore

    res = await db.execute(
        select(HealthAlert).where(HealthAlert.active == 1, HealthAlert.acknowledged == 0)
    )
    active_alerts = res.scalars().all()

    for alert in active_alerts:
        resolved = False

        if alert.type == "low_period":
            # Resolve se humor > 5 hoje
            checkin_res = await db.execute(
                select(MentalCheckin.mood).where(MentalCheckin.date == today)
            )
            mood = checkin_res.scalar_one_or_none()
            if mood and mood > 5:
                resolved = True

        elif alert.type == "sleep_deprivation":
            # Resolve se sono > 7h hoje
            oura_res = await db.execute(
                select(OuraDaily.sleep_duration).where(OuraDaily.date == today)
            )
            duration = oura_res.scalar_one_or_none()
            if duration and duration >= 7.0:
                resolved = True

        elif alert.type == "low_score":
            # Resolve se score > 50 hoje
            score_res = await db.execute(
                select(HealthScore.score_total).where(HealthScore.date == today)
            )
            score = score_res.scalar_one_or_none()
            if score and score >= 50:
                resolved = True

        elif alert.type == "med_consecutive":
            # Resolve se não tomou o medicamento hoje
            data = json.loads(alert.data or "{}")
            med_id = data.get("medication_id")
            if med_id:
                from app.features.health.models import MedicationLog
                log_res = await db.execute(
                    select(MedicationLog).where(
                        MedicationLog.medication_id == med_id,
                        MedicationLog.date == today,
                    )
                )
                if not log_res.scalar_one_or_none():
                    resolved = True

        if resolved:
            alert.active = 0
            logger.info(f"[alerts] resolvido: {alert.type}")


# ── Contadores auxiliares ─────────────────────────────────────────────────────

async def _count_consecutive_low_mood(db: AsyncSession, today: str, threshold: int) -> int:
    from app.features.health.models import MentalCheckin

    count = 0
    for i in range(1, 15):
        d = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
        res = await db.execute(
            select(MentalCheckin.mood).where(MentalCheckin.date == d)
        )
        mood = res.scalar_one_or_none()
        if mood is None:
            break  # dia sem check-in interrompe a contagem
        if mood > threshold:
            break
        count += 1

    # Inclui hoje
    res = await db.execute(
        select(MentalCheckin.mood).where(MentalCheckin.date == today)
    )
    mood_today = res.scalar_one_or_none()
    if mood_today is not None and mood_today <= threshold:
        count += 1

    return count


async def _count_consecutive_med_days(db: AsyncSession, today: str, medication_id: str) -> int:
    from app.features.health.models import MedicationLog

    count = 0
    for i in range(0, 60):
        d = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
        res = await db.execute(
            select(MedicationLog.id).where(
                MedicationLog.medication_id == medication_id,
                MedicationLog.date == d,
            ).limit(1)
        )
        if not res.scalar_one_or_none():
            break
        count += 1

    return count


async def _count_consecutive_short_sleep(db: AsyncSession, today: str, min_hours: float) -> int:
    from app.features.health.models import OuraDaily

    count = 0
    for i in range(0, 14):
        d = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
        res = await db.execute(
            select(OuraDaily.sleep_duration).where(OuraDaily.date == d)
        )
        dur = res.scalar_one_or_none()
        if dur is None:
            break
        if dur >= min_hours:
            break
        count += 1

    return count


async def _count_consecutive_low_score(db: AsyncSession, today: str, threshold: int) -> int:
    from app.features.health.models import HealthScore

    count = 0
    for i in range(0, 14):
        d = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
        res = await db.execute(
            select(HealthScore.score_total).where(HealthScore.date == d)
        )
        score = res.scalar_one_or_none()
        if score is None:
            break
        if score >= threshold:
            break
        count += 1

    return count
