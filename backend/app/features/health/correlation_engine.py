"""
Engine de correlações de saúde.
Analisa 30 dias de dados e calcula correlações entre fatores.
Executa domingo às 04:00 (silencioso).
"""
import json
import logging
import math
import uuid
from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.dates import now_brt

logger = logging.getLogger(__name__)


async def calculate_correlations(db: AsyncSession, days: int = 30) -> list[dict]:
    """Calcula correlações e persiste em HealthCorrelation. Retorna lista de correlações."""
    from app.features.health.models import (
        OuraDaily, MentalCheckin, MedicationLog, Medication, HealthCorrelation
    )
    from app.features.habits.models import Habit, HabitLog
    from app.features.tasks.models import Task

    today = now_brt().date()
    start_date = (today - timedelta(days=days)).isoformat()
    end_date = today.isoformat()
    updated_at = now_brt().isoformat()

    # ── Coleta de dados ──────────────────────────────────────────────────────
    # OuraDaily
    res = await db.execute(
        select(OuraDaily).where(OuraDaily.date >= start_date, OuraDaily.date <= end_date)
    )
    oura_rows = {r.date: r for r in res.scalars().all()}

    # MentalCheckin
    res2 = await db.execute(
        select(MentalCheckin).where(MentalCheckin.date >= start_date, MentalCheckin.date <= end_date)
    )
    checkin_rows = {r.date: r for r in res2.scalars().all()}

    # HabitLogs
    res3 = await db.execute(select(Habit).where(Habit.active == 1))
    habits = res3.scalars().all()

    habit_logs: dict[str, dict[str, bool]] = defaultdict(dict)  # habit_id -> date -> done
    for habit in habits:
        res4 = await db.execute(
            select(HabitLog).where(
                HabitLog.habit_id == habit.id,
                HabitLog.date >= start_date,
                HabitLog.date <= end_date,
            )
        )
        for log in res4.scalars().all():
            habit_logs[habit.id][log.date] = log.done == 1

    # MedicationLogs
    res5 = await db.execute(select(Medication).where(Medication.active == 1))
    meds = res5.scalars().all()

    med_logs: dict[str, dict[str, float]] = defaultdict(dict)  # med_id -> date -> qty
    for med in meds:
        res6 = await db.execute(
            select(MedicationLog).where(
                MedicationLog.medication_id == med.id,
                MedicationLog.date >= start_date,
                MedicationLog.date <= end_date,
            )
        )
        for log in res6.scalars().all():
            med_logs[med.id][log.date] = (med_logs[med.id].get(log.date, 0)) + log.quantity

    # Tarefas feitas por dia
    tasks_done_by_day: dict[str, int] = defaultdict(int)
    res7 = await db.execute(
        select(Task).where(
            Task.status == "done",
            Task.completed_at >= start_date,
        )
    )
    for t in res7.scalars().all():
        if t.completed_at:
            day = t.completed_at[:10]
            tasks_done_by_day[day] += 1

    # ── Calcula correlações ──────────────────────────────────────────────────
    correlations: list[dict] = []
    all_dates = sorted(set(oura_rows) | set(checkin_rows))

    # Fatores binários → métricas contínuas
    # Hábitos → mood, energy, sleep_score, hrv_rmssd
    for habit in habits:
        for metric, get_val in [
            ("mood", lambda d: getattr(checkin_rows.get(d), "mood", None)),
            ("energy", lambda d: getattr(checkin_rows.get(d), "energy", None)),
            ("sleep_score", lambda d: getattr(oura_rows.get(d), "sleep_score", None)),
            ("hrv_rmssd", lambda d: getattr(oura_rows.get(d), "hrv_rmssd", None)),
        ]:
            with_days = []
            without_days = []
            for d in all_dates:
                val = get_val(d)
                if val is None:
                    continue
                did_habit = habit_logs[habit.id].get(d, False)
                if did_habit:
                    with_days.append(val)
                else:
                    without_days.append(val)

            corr = _effect_size(with_days, without_days)
            if corr is not None and abs(corr.get("effect_size", 0)) > 0.3:
                correlations.append({
                    "factor_a": habit.name.lower(),
                    "factor_b": metric,
                    "correlation": corr["correlation"],
                    "effect_size": corr["effect_size"],
                    "description": (
                        f"Dias com {habit.name}: {metric} {corr['mean_with']:.1f} "
                        f"vs {corr['mean_without']:.1f}"
                    ),
                    "sample_size": corr["n"],
                    "confidence": corr["confidence"],
                })

    # Medicamentos → mood, sleep_score, hrv_rmssd, energy
    for med in meds:
        for metric, get_val in [
            ("mood", lambda d: getattr(checkin_rows.get(d), "mood", None)),
            ("sleep_score", lambda d: getattr(oura_rows.get(d), "sleep_score", None)),
            ("hrv_rmssd", lambda d: getattr(oura_rows.get(d), "hrv_rmssd", None)),
        ]:
            with_days = []
            without_days = []
            for d in all_dates:
                val = get_val(d)
                if val is None:
                    continue
                took_med = med_logs[med.id].get(d, 0) > 0
                if took_med:
                    with_days.append(val)
                else:
                    without_days.append(val)

            corr = _effect_size(with_days, without_days)
            if corr is not None and abs(corr.get("effect_size", 0)) > 0.3:
                correlations.append({
                    "factor_a": med.name.lower(),
                    "factor_b": metric,
                    "correlation": corr["correlation"],
                    "effect_size": corr["effect_size"],
                    "description": (
                        f"Dias com {med.name}: {metric} {corr['mean_with']:.1f} "
                        f"vs {corr['mean_without']:.1f}"
                    ),
                    "sample_size": corr["n"],
                    "confidence": corr["confidence"],
                })

    # Sono bom (>7h) → produtividade no dia seguinte
    next_day_prod = []
    next_day_no_prod = []
    for d in sorted(oura_rows.keys()):
        dur = oura_rows[d].sleep_duration
        if dur is None:
            continue
        next_d = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        tasks_next = tasks_done_by_day.get(next_d)
        if tasks_next is None:
            continue
        if dur >= 7.0:
            next_day_prod.append(tasks_next)
        else:
            next_day_no_prod.append(tasks_next)

    corr_sleep_prod = _effect_size(next_day_prod, next_day_no_prod)
    if corr_sleep_prod and abs(corr_sleep_prod.get("effect_size", 0)) > 0.2:
        correlations.append({
            "factor_a": "sleep_7h",
            "factor_b": "next_day_tasks",
            "correlation": corr_sleep_prod["correlation"],
            "effect_size": corr_sleep_prod["effect_size"],
            "description": (
                f"Noites com ≥7h: {corr_sleep_prod['mean_with']:.1f} tarefas feitas no dia seguinte "
                f"vs {corr_sleep_prod['mean_without']:.1f}"
            ),
            "sample_size": corr_sleep_prod["n"],
            "confidence": corr_sleep_prod["confidence"],
        })

    # Tags do check-in → métricas
    tag_data: dict[str, list[float]] = defaultdict(list)
    no_tag_data: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for d, ci in checkin_rows.items():
        if not ci.tags:
            continue
        try:
            tags = json.loads(ci.tags) if isinstance(ci.tags, str) else ci.tags
        except Exception:
            continue

        for tag in (tags or []):
            if ci.mood is not None:
                tag_data[f"tag:{tag}:mood"].append(ci.mood)
            oura = oura_rows.get(d)
            if oura and oura.sleep_score:
                tag_data[f"tag:{tag}:sleep"].append(oura.sleep_score)

    # ── Persiste ──────────────────────────────────────────────────────────────
    from app.features.health.models import HealthCorrelation as HC

    # Limpa correlações antigas
    await db.execute(select(HC))  # garante que a tabela existe
    res_old = await db.execute(select(HC))
    for old in res_old.scalars().all():
        await db.delete(old)

    saved = []
    for corr in correlations:
        hc = HC(
            id=str(uuid.uuid4()),
            factor_a=corr["factor_a"],
            factor_b=corr["factor_b"],
            correlation=round(corr.get("correlation", 0), 3),
            effect_size=round(corr.get("effect_size", 0), 3),
            description=corr.get("description"),
            sample_size=corr.get("sample_size", 0),
            confidence=round(corr.get("confidence", 0), 3),
            updated_at=updated_at,
        )
        db.add(hc)
        saved.append(corr)

    await db.commit()
    logger.info(f"[correlations] {len(saved)} correlações calculadas ({days} dias)")
    return saved


def _effect_size(with_vals: list, without_vals: list) -> dict | None:
    """Calcula efeito Cohen's d simplificado e correlação ponto-bisserial."""
    if len(with_vals) < 3 or len(without_vals) < 3:
        return None

    mean_with = sum(with_vals) / len(with_vals)
    mean_without = sum(without_vals) / len(without_vals)

    # Desvio padrão pooled
    all_vals = with_vals + without_vals
    grand_mean = sum(all_vals) / len(all_vals)
    variance = sum((x - grand_mean) ** 2 for x in all_vals) / max(1, len(all_vals) - 1)
    std_dev = math.sqrt(variance) if variance > 0 else 0

    if std_dev == 0:
        return None

    effect_size = (mean_with - mean_without) / std_dev

    # Correlação ponto-bisserial aproximada
    n = len(all_vals)
    n1 = len(with_vals)
    n0 = len(without_vals)
    r_pb = effect_size * math.sqrt(n1 * n0 / (n * n))

    # Confiança: proporção de N (mais dados = mais confiança)
    confidence = min(1.0, n / 30)

    return {
        "effect_size": round(effect_size, 3),
        "correlation": round(max(-1.0, min(1.0, r_pb)), 3),
        "mean_with": mean_with,
        "mean_without": mean_without,
        "n": n,
        "confidence": round(confidence, 2),
    }
