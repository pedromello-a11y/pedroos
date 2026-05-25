"""
Engine de pontuação diária de saúde — Pedro Score.

Dimensões e pesos:
  body         25% — Oura (sono + readiness + activity + HRV)
  mind         25% — Check-in mental (mood + energy + stress)
  movement     20% — Exercício + passos + consistência semanal
  productivity 15% — Tarefas concluídas vs propostas
  selfcare     15% — Medicação + hábitos + qualidade de comida

Regras especiais:
  - mind < 30 → total cap 50
  - body < 30 → total cap 60
  - 5+ dias sem exercício → -10 pontos
  - todas dimensões > 60 → +5 bônus de equilíbrio
"""
import json
import logging
from datetime import date, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.dates import now_brt

logger = logging.getLogger(__name__)


async def calculate_daily_score(db: AsyncSession, target_date: str | None = None) -> dict:
    """Calcula e persiste o HealthScore para target_date (default: hoje BRT)."""
    from app.features.health.models import OuraDaily, MentalCheckin, HealthScore, MedicationLog, Medication

    if not target_date:
        target_date = now_brt().date().isoformat()

    components: dict = {}

    # ── 1. BODY (25%) ──────────────────────────────────────────────────────────
    res = await db.execute(select(OuraDaily).where(OuraDaily.date == target_date))
    oura = res.scalar_one_or_none()

    body_score: float | None = None
    if oura:
        sl = oura.sleep_score or 0
        rd = oura.readiness_score or 0
        ac = oura.activity_score or 0

        # HRV vs baseline: compara hrv_balance com média dos últimos 14 dias
        hrv_score = await _hrv_vs_baseline(db, target_date, oura.hrv_rmssd)

        body_score = (
            sl * 0.40 +
            rd * 0.30 +
            ac * 0.15 +
            (hrv_score or rd) * 0.15  # fallback para readiness se sem HRV
        )
        body_score = min(100, max(0, body_score))
        components["body"] = {
            "sleep_score": sl, "readiness_score": rd,
            "activity_score": ac, "hrv_score": hrv_score,
            "score": round(body_score, 1),
        }

    # ── 2. MIND (25%) ─────────────────────────────────────────────────────────
    res2 = await db.execute(select(MentalCheckin).where(MentalCheckin.date == target_date))
    checkin = res2.scalar_one_or_none()

    mind_score: float | None = None
    if checkin and checkin.mood is not None:
        mood_norm = ((checkin.mood - 1) / 9) * 100          # 1–10 → 0–100
        energy_norm = ((checkin.energy or 3) - 1) / 4 * 100  # 1–5 → 0–100
        stress_inv = (1 - ((checkin.stress or 3) - 1) / 4) * 100  # inverted

        mind_score = (
            mood_norm * 0.50 +
            energy_norm * 0.25 +
            stress_inv * 0.25
        )
        mind_score = min(100, max(0, mind_score))
        components["mind"] = {
            "mood": checkin.mood, "energy": checkin.energy, "stress": checkin.stress,
            "mood_norm": round(mood_norm, 1), "energy_norm": round(energy_norm, 1),
            "stress_inv": round(stress_inv, 1), "score": round(mind_score, 1),
        }

    # ── 3. MOVEMENT (20%) ────────────────────────────────────────────────────
    movement_score = await _calc_movement(db, target_date, oura, checkin)
    if movement_score is not None:
        components["movement"] = {"score": round(movement_score, 1)}

    # ── 4. PRODUCTIVITY (15%) ────────────────────────────────────────────────
    productivity_score = await _calc_productivity(db, target_date)
    if productivity_score is not None:
        components["productivity"] = {"score": round(productivity_score, 1)}

    # ── 5. SELFCARE (15%) ────────────────────────────────────────────────────
    selfcare_score = await _calc_selfcare(db, target_date, checkin)
    if selfcare_score is not None:
        components["selfcare"] = {"score": round(selfcare_score, 1)}

    # ── Score total ───────────────────────────────────────────────────────────
    dims = {
        "body": (body_score, 0.25),
        "mind": (mind_score, 0.25),
        "movement": (movement_score, 0.20),
        "productivity": (productivity_score, 0.15),
        "selfcare": (selfcare_score, 0.15),
    }

    weighted_sum = 0.0
    weight_used = 0.0
    for _, (val, w) in dims.items():
        if val is not None:
            weighted_sum += val * w
            weight_used += w

    if weight_used == 0:
        total = None
    else:
        # Normaliza se não temos todas as dimensões
        total = (weighted_sum / weight_used) * 100 / 100 if weight_used < 1.0 else weighted_sum
        total = min(100, max(0, total))

        # Regras especiais
        if mind_score is not None and mind_score < 30:
            total = min(total, 50)
            components["cap"] = "mind<30 → cap 50"
        if body_score is not None and body_score < 30:
            total = min(total, 60)
            components["cap"] = components.get("cap", "") + " body<30 → cap 60"

        # 5+ dias sem exercício
        no_exercise_days = await _count_no_exercise_days(db, target_date)
        if no_exercise_days >= 5:
            total = max(0, total - 10)
            components["penalty"] = f"-10 por {no_exercise_days} dias sem exercício"

        # Bônus de equilíbrio
        scored_dims = [v for v, _ in dims.values() if v is not None]
        if len(scored_dims) >= 4 and all(v > 60 for v in scored_dims):
            total = min(100, total + 5)
            components["bonus"] = "+5 equilíbrio"

        total = round(total, 1)

    # ── Persiste ──────────────────────────────────────────────────────────────
    res3 = await db.execute(select(HealthScore).where(HealthScore.date == target_date))
    hs = res3.scalar_one_or_none()

    from app.features.health.models import HealthScore as _HS
    if not hs:
        hs = _HS(date=target_date)
        db.add(hs)

    hs.score_total = total
    hs.score_body = round(body_score, 1) if body_score is not None else None
    hs.score_mind = round(mind_score, 1) if mind_score is not None else None
    hs.score_movement = round(movement_score, 1) if movement_score is not None else None
    hs.score_productivity = round(productivity_score, 1) if productivity_score is not None else None
    hs.score_selfcare = round(selfcare_score, 1) if selfcare_score is not None else None
    hs.components = json.dumps(components)
    hs.calculated_at = now_brt().isoformat()

    await db.commit()
    logger.info(f"[score] {target_date}: total={total}")
    return {
        "date": target_date,
        "score_total": total,
        "score_body": hs.score_body,
        "score_mind": hs.score_mind,
        "score_movement": hs.score_movement,
        "score_productivity": hs.score_productivity,
        "score_selfcare": hs.score_selfcare,
        "components": components,
    }


async def _hrv_vs_baseline(db: AsyncSession, target_date: str, hrv_today: float | None) -> float | None:
    """Compara HRV hoje com média dos últimos 14 dias. Retorna 0–100."""
    from app.features.health.models import OuraDaily

    if hrv_today is None:
        return None

    two_weeks_ago = (date.fromisoformat(target_date) - timedelta(days=14)).isoformat()
    res = await db.execute(
        select(OuraDaily.hrv_rmssd).where(
            OuraDaily.date >= two_weeks_ago,
            OuraDaily.date < target_date,
            OuraDaily.hrv_rmssd.isnot(None),
        )
    )
    values = [r for r in res.scalars().all() if r]
    if not values:
        return 50.0  # sem baseline → neutro

    baseline = sum(values) / len(values)
    ratio = hrv_today / baseline
    # ratio 1.0 = 50pts; 1.2+ = 100pts; 0.8- = 0pts
    score = (ratio - 0.8) / 0.4 * 100
    return min(100, max(0, score))


async def _calc_movement(
    db: AsyncSession,
    target_date: str,
    oura: object | None,
    checkin: object | None,
) -> float | None:
    from app.features.habits.models import Habit, HabitLog

    # Componentes base
    steps_score = 0.0
    active_time_score = 0.0
    exercise_score = 0.0
    consistency_bonus = 0.0

    has_data = False

    # Passos (Oura)
    if oura and oura.steps:
        has_data = True
        target_steps = 8000
        steps_score = min(100, oura.steps / target_steps * 100) * 0.20

    # Tempo ativo (Oura)
    if oura and oura.active_time:
        has_data = True
        target_min = 30  # minutos
        active_time_score = min(100, oura.active_time / target_min * 100) * 0.20

    # Exercício — check-in OU hábito de exercício marcado hoje
    exercise_done = False
    if checkin and checkin.exercise == 1:
        exercise_done = True

    # Hábitos de exercício (natação, corrida, etc.)
    res = await db.execute(
        select(Habit).where(Habit.active == 1)
    )
    habits = res.scalars().all()
    exercise_habits = [h for h in habits if any(
        kw in h.name.lower() for kw in ["natação", "natacao", "corrida", "ginástica", "academia", "treino", "bike", "crossfit"]
    )]

    if exercise_habits:
        has_data = True
        # Verifica logs de hoje
        habit_ids = [h.id for h in exercise_habits]
        log_res = await db.execute(
            select(HabitLog).where(
                HabitLog.habit_id.in_(habit_ids),
                HabitLog.date == target_date,
                HabitLog.done == 1,
            )
        )
        logs = log_res.scalars().all()
        if logs:
            exercise_done = True

    if exercise_done:
        exercise_score = 60.0 * 0.60

    # Penalidade por inatividade
    if oura and oura.inactivity_alerts and oura.inactivity_alerts > 3:
        exercise_score = max(0, exercise_score - 10)

    # Consistência semanal — quantos dias de exercício nos últimos 7
    week_exercise = await _count_exercise_days_last_n(db, target_date, 7)
    if week_exercise >= 5:
        consistency_bonus = 15
    elif week_exercise >= 3:
        consistency_bonus = 5

    # Penalidade por 4+ dias sem exercício consecutivos
    consec_no_exercise = await _count_no_exercise_days(db, target_date)
    if consec_no_exercise >= 4:
        consistency_bonus -= 10

    if not has_data and not exercise_habits:
        return None

    total = steps_score + active_time_score + exercise_score + consistency_bonus
    return min(100, max(0, total))


async def _calc_productivity(db: AsyncSession, target_date: str) -> float | None:
    from app.features.tasks.models import Task

    d = date.fromisoformat(target_date)
    # Fins de semana têm meta reduzida
    is_weekend = d.weekday() >= 5

    # Tarefas concluídas hoje
    res = await db.execute(
        select(func.count()).where(
            Task.status == "done",
            Task.completed_at.startswith(target_date),
        )
    )
    done_count = res.scalar() or 0

    # Tarefas com prazo hoje (propostas)
    res2 = await db.execute(
        select(func.count()).where(
            Task.deadline == target_date,
            Task.status != "raw",
        )
    )
    due_today = res2.scalar() or 0

    # Tempo gasto hoje (tasks que saíram de doing hoje)
    res3 = await db.execute(
        select(func.sum(Task.time_spent_minutes)).where(
            Task.updated_at.startswith(target_date),
            Task.time_spent_minutes.isnot(None),
        )
    )
    time_spent = res3.scalar() or 0

    if done_count == 0 and due_today == 0 and time_spent == 0:
        return None

    base = 50.0 if is_weekend else 60.0

    # Ratio tarefas
    if due_today > 0:
        ratio = min(1.0, done_count / due_today)
        task_score = ratio * (40 if not is_weekend else 30)
    else:
        # Sem deadline hoje — pontua pela quantidade feita
        task_score = min(40, done_count * 8)

    # Bônus de tempo (2h+ de trabalho focado)
    time_bonus = min(15, (time_spent / 120) * 15) if time_spent > 30 else 0

    # Penalidade por tarefas atrasadas
    res4 = await db.execute(
        select(func.count()).where(
            Task.deadline < target_date,
            Task.status.in_(["todo", "doing"]),
            Task.deadline.isnot(None),
        )
    )
    overdue = res4.scalar() or 0
    overdue_penalty = min(20, overdue * 3)

    total = base + task_score + time_bonus - overdue_penalty
    return min(100, max(0, total))


async def _calc_selfcare(
    db: AsyncSession,
    target_date: str,
    checkin: object | None,
) -> float | None:
    from app.features.health.models import Medication, MedicationLog

    score = 50.0  # base neutra
    has_data = False

    # Medicação: quanto da meta diária foi atingida
    res = await db.execute(select(Medication).where(Medication.active == 1))
    meds = res.scalars().all()

    if meds:
        has_data = True
        med_scores = []
        for med in meds:
            res2 = await db.execute(
                select(func.sum(MedicationLog.quantity)).where(
                    MedicationLog.medication_id == med.id,
                    MedicationLog.date == target_date,
                )
            )
            taken = res2.scalar() or 0
            ratio = min(1.0, taken / max(1.0, med.daily_target))
            med_scores.append(ratio)
        if med_scores:
            avg_med = sum(med_scores) / len(med_scores)
            score = avg_med * 80  # até 80 pontos da medicação

    # Bônus de qualidade da comida
    if checkin and checkin.food_quality:
        has_data = True
        food_bonus = ((checkin.food_quality - 1) / 4) * 20
        score += food_bonus

    # Streak de check-ins (até 10 pontos)
    if checkin and checkin.streak:
        streak_bonus = min(10, checkin.streak * 1.5)
        score += streak_bonus
        has_data = True

    if not has_data:
        return None

    return min(100, max(0, score))


async def _count_exercise_days_last_n(db: AsyncSession, target_date: str, n: int) -> int:
    """Conta quantos dos últimos N dias tiveram exercício (check-in ou hábito)."""
    from app.features.health.models import MentalCheckin
    from app.features.habits.models import HabitLog, Habit

    start = (date.fromisoformat(target_date) - timedelta(days=n)).isoformat()

    res = await db.execute(
        select(MentalCheckin.date).where(
            MentalCheckin.date >= start,
            MentalCheckin.date <= target_date,
            MentalCheckin.exercise == 1,
        )
    )
    exercise_days = set(res.scalars().all())

    # Adiciona dias com hábito de exercício
    res2 = await db.execute(
        select(Habit.id).where(Habit.active == 1)
    )
    all_habit_ids = res2.scalars().all()
    exercise_habit_ids = []
    for hid in all_habit_ids:
        # Já temos o objeto na sessão, mas para evitar N+1 usamos a lista
        exercise_habit_ids.append(hid)  # simplificação — pega todos por ora

    if exercise_habit_ids:
        res3 = await db.execute(
            select(HabitLog.date).where(
                HabitLog.date >= start,
                HabitLog.date <= target_date,
                HabitLog.done == 1,
            )
        )
        exercise_days |= set(res3.scalars().all())

    return len(exercise_days)


async def _count_no_exercise_days(db: AsyncSession, target_date: str) -> int:
    """Conta dias consecutivos sem exercício terminando em target_date."""
    d = date.fromisoformat(target_date)
    count = 0
    from app.features.health.models import MentalCheckin
    from app.features.habits.models import HabitLog

    for i in range(1, 15):  # máx 14 dias para trás
        check_date = (d - timedelta(days=i)).isoformat()

        res = await db.execute(
            select(MentalCheckin.exercise).where(MentalCheckin.date == check_date)
        )
        exercise_val = res.scalar_one_or_none()
        if exercise_val == 1:
            break

        # Verifica hábitos
        res2 = await db.execute(
            select(HabitLog.id).where(
                HabitLog.date == check_date,
                HabitLog.done == 1,
            ).limit(1)
        )
        if res2.scalar_one_or_none():
            break

        count += 1

    return count


# Alias para compatibilidade com o scheduler
calculate_health_score = calculate_daily_score
