from sqlalchemy import Column, Text, Integer, Float, Boolean
from app.db import Base


class OuraDaily(Base):
    """Dados diários do Oura Ring."""
    __tablename__ = "oura_daily"

    date = Column(Text, primary_key=True)  # YYYY-MM-DD

    # Sleep
    sleep_score = Column(Integer)        # 0–100
    sleep_duration = Column(Float)       # horas
    rem_sleep = Column(Float)            # horas
    deep_sleep = Column(Float)           # horas
    sleep_efficiency = Column(Float)     # %
    sleep_latency = Column(Integer)      # minutos até dormir
    awakenings = Column(Integer)

    # Readiness
    readiness_score = Column(Integer)    # 0–100
    hrv_balance = Column(Integer)        # 0–100 (componente do readiness)
    recovery_index = Column(Integer)     # 0–100
    resting_hr = Column(Float)           # bpm
    hrv_rmssd = Column(Float)            # ms

    # Activity
    activity_score = Column(Integer)     # 0–100
    steps = Column(Integer)
    active_calories = Column(Integer)    # kcal
    total_calories = Column(Integer)
    active_time = Column(Float)          # minutos de atividade moderada+
    inactivity_alerts = Column(Integer)

    # Meta
    synced_at = Column(Text)
    raw_json = Column(Text)              # JSON completo do Oura para debugging


class Medication(Base):
    """Cadastro de medicamentos/suplementos."""
    __tablename__ = "medications"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    dose_label = Column(Text)            # ex: "10mg", "1 comprimido"
    unit = Column(Text, default="unidade")
    daily_target = Column(Float, default=1.0)   # quantidade alvo por dia
    baseline_30d = Column(Float)                # média dos últimos 30 dias (atualizado semanalmente)
    alert_days = Column(Integer, default=7)     # alertar se tomado X dias consecutivos
    color = Column(Text, default="#6366F1")
    active = Column(Integer, default=1)         # 1=ativo, 0=arquivado
    position = Column(Integer, default=0)


class MedicationLog(Base):
    """Registro de tomada de medicamento."""
    __tablename__ = "medication_logs"

    id = Column(Text, primary_key=True)
    medication_id = Column(Text, nullable=False)
    date = Column(Text, nullable=False)   # YYYY-MM-DD
    quantity = Column(Float, default=1.0)
    time = Column(Text)                   # HH:MM
    note = Column(Text)


class MentalCheckin(Base):
    """Check-in diário de saúde mental."""
    __tablename__ = "mental_checkins"

    id = Column(Text, primary_key=True)
    date = Column(Text, unique=True, nullable=False)  # YYYY-MM-DD

    # Métricas principais (obrigatórias no check-in rápido)
    mood = Column(Integer)           # 1–10
    energy = Column(Integer)         # 1–5
    stress = Column(Integer)         # 1–5
    pain = Column(Integer)           # 1–5 (0=sem dor)

    # Comportamentos (opcionais — whatsapp rápido)
    sleep_hours = Column(Float)      # horas dormidas (pode vir do Oura)
    exercise = Column(Integer)       # 0=não, 1=sim
    alcohol = Column(Integer, default=0)   # unidades
    cigarettes = Column(Integer, default=0)
    social = Column(Integer)         # 1–5 nível de conexão social
    food_quality = Column(Integer)   # 1–5

    # Texto
    note_text = Column(Text)
    note_ai_summary = Column(Text)   # resumo gerado por IA do note_text

    # Meta
    tags = Column(Text)              # JSON array de strings: ["ansiedade", "tdah-flow"]
    streak = Column(Integer, default=0)   # dias consecutivos com check-in
    source = Column(Text, default="web")  # "web" | "whatsapp"
    created_at = Column(Text)


class HealthScore(Base):
    """Pontuação diária composta de saúde."""
    __tablename__ = "health_scores"

    date = Column(Text, primary_key=True)  # YYYY-MM-DD

    # Score geral e dimensões (0–100)
    score_total = Column(Float)
    score_body = Column(Float)       # 25% — Oura
    score_mind = Column(Float)       # 25% — check-in mental
    score_movement = Column(Float)   # 20% — exercício + passos
    score_productivity = Column(Float)  # 15% — tarefas
    score_selfcare = Column(Float)   # 15% — medicação + hábitos

    components = Column(Text)        # JSON com breakdown detalhado
    calculated_at = Column(Text)


class HealthAlert(Base):
    """Alertas gerados pelo engine de análise."""
    __tablename__ = "health_alerts"

    id = Column(Text, primary_key=True)
    type = Column(Text, nullable=False)   # low_period | med_consecutive | sleep_deprivation | low_score
    severity = Column(Text)               # critical | warning | info
    title = Column(Text)
    description = Column(Text)
    data = Column(Text)                   # JSON com contexto do alerta
    active = Column(Integer, default=1)   # 1=ativo
    acknowledged = Column(Integer, default=0)
    triggered_at = Column(Text)


class HealthCorrelation(Base):
    """Correlações identificadas entre fatores de saúde."""
    __tablename__ = "health_correlations"

    id = Column(Text, primary_key=True)
    factor_a = Column(Text)               # ex: "exercise", "alcohol", "natacao"
    factor_b = Column(Text)               # ex: "mood", "sleep_score", "hrv"
    correlation = Column(Float)           # -1.0 a 1.0
    effect_size = Column(Float)           # Cohen's d ou diferença de médias
    description = Column(Text)            # texto legível: "Dias com exercício: mood 7.2 vs 5.1"
    sample_size = Column(Integer)
    confidence = Column(Float)            # 0–1
    updated_at = Column(Text)


class OuraToken(Base):
    """Token OAuth2 do Oura (singleton, id=1)."""
    __tablename__ = "oura_tokens"

    id = Column(Integer, primary_key=True, default=1)
    access_token = Column(Text)
    refresh_token = Column(Text)
    expires_at = Column(Text)            # ISO datetime BRT
