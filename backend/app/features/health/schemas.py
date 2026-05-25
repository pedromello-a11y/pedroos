from pydantic import BaseModel
from typing import Optional, List, Any


# ── Medication ────────────────────────────────────────────────────────────────

class MedicationCreate(BaseModel):
    name: str
    dose_label: Optional[str] = None
    unit: str = "unidade"
    daily_target: float = 1.0
    alert_days: int = 7
    color: str = "#6366F1"
    active: int = 1
    position: int = 0


class MedicationResponse(BaseModel):
    id: str
    name: str
    dose_label: Optional[str]
    unit: str
    daily_target: float
    baseline_30d: Optional[float]
    alert_days: int
    color: str
    active: int
    position: int

    class Config:
        from_attributes = True


class MedicationLogCreate(BaseModel):
    medication_id: str
    date: str
    quantity: float = 1.0
    time: Optional[str] = None
    note: Optional[str] = None


class MedicationLogResponse(BaseModel):
    id: str
    medication_id: str
    date: str
    quantity: float
    time: Optional[str]
    note: Optional[str]

    class Config:
        from_attributes = True


# ── MentalCheckin ─────────────────────────────────────────────────────────────

class CheckinCreate(BaseModel):
    date: Optional[str] = None   # defaults to today
    mood: int                    # 1–10
    energy: Optional[int] = None
    stress: Optional[int] = None
    pain: Optional[int] = None
    sleep_hours: Optional[float] = None
    exercise: Optional[int] = None
    alcohol: Optional[int] = None
    cigarettes: Optional[int] = None
    social: Optional[int] = None
    food_quality: Optional[int] = None
    note_text: Optional[str] = None
    tags: Optional[List[str]] = None
    source: str = "web"


class CheckinUpdate(BaseModel):
    mood: Optional[int] = None
    energy: Optional[int] = None
    stress: Optional[int] = None
    pain: Optional[int] = None
    sleep_hours: Optional[float] = None
    exercise: Optional[int] = None
    alcohol: Optional[int] = None
    cigarettes: Optional[int] = None
    social: Optional[int] = None
    food_quality: Optional[int] = None
    note_text: Optional[str] = None
    tags: Optional[List[str]] = None


class CheckinResponse(BaseModel):
    id: str
    date: str
    mood: Optional[int]
    energy: Optional[int]
    stress: Optional[int]
    pain: Optional[int]
    sleep_hours: Optional[float]
    exercise: Optional[int]
    alcohol: Optional[int]
    cigarettes: Optional[int]
    social: Optional[int]
    food_quality: Optional[int]
    note_text: Optional[str]
    note_ai_summary: Optional[str]
    tags: Optional[Any]
    streak: int
    source: str

    class Config:
        from_attributes = True


# ── HealthScore ───────────────────────────────────────────────────────────────

class HealthScoreResponse(BaseModel):
    date: str
    score_total: Optional[float]
    score_body: Optional[float]
    score_mind: Optional[float]
    score_movement: Optional[float]
    score_productivity: Optional[float]
    score_selfcare: Optional[float]
    components: Optional[Any]
    calculated_at: Optional[str]

    class Config:
        from_attributes = True


class HealthScoreHeader(BaseModel):
    date: str
    score_total: Optional[float]
    score_body: Optional[float]
    score_mind: Optional[float]
    alert_count: int


# ── HealthAlert ───────────────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    description: Optional[str]
    data: Optional[Any]
    active: int
    acknowledged: int
    triggered_at: str

    class Config:
        from_attributes = True


# ── HealthCorrelation ─────────────────────────────────────────────────────────

class CorrelationResponse(BaseModel):
    id: str
    factor_a: str
    factor_b: str
    correlation: float
    effect_size: Optional[float]
    description: Optional[str]
    sample_size: int
    confidence: Optional[float]
    updated_at: str

    class Config:
        from_attributes = True


# ── OuraDaily ─────────────────────────────────────────────────────────────────

class OuraDailyResponse(BaseModel):
    date: str
    sleep_score: Optional[int]
    sleep_duration: Optional[float]
    rem_sleep: Optional[float]
    deep_sleep: Optional[float]
    sleep_efficiency: Optional[float]
    sleep_latency: Optional[int]
    awakenings: Optional[int]
    readiness_score: Optional[int]
    hrv_balance: Optional[int]
    recovery_index: Optional[int]
    resting_hr: Optional[float]
    hrv_rmssd: Optional[float]
    activity_score: Optional[int]
    steps: Optional[int]
    active_calories: Optional[int]
    total_calories: Optional[int]
    active_time: Optional[float]
    inactivity_alerts: Optional[int]
    synced_at: Optional[str]

    class Config:
        from_attributes = True


# ── Dashboard ─────────────────────────────────────────────────────────────────

class HealthDashboard(BaseModel):
    today_score: Optional[HealthScoreResponse]
    oura_today: Optional[OuraDailyResponse]
    checkin_today: Optional[CheckinResponse]
    medications: List[MedicationResponse]
    medication_logs_today: List[MedicationLogResponse]
    active_alerts: List[AlertResponse]
    recent_scores: List[HealthScoreResponse]
    top_correlations: List[CorrelationResponse]
