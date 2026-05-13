from datetime import datetime, date, timedelta
import zoneinfo
from typing import Optional

BRT = zoneinfo.ZoneInfo("America/Sao_Paulo")

DAYS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
DAYS_PT_FULL = [
    "segunda-feira", "terça-feira", "quarta-feira",
    "quinta-feira", "sexta-feira", "sábado", "domingo",
]
MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]


def now_brt() -> datetime:
    return datetime.now(BRT)


def today_brt() -> date:
    return datetime.now(BRT).date()


def format_date_pt(d: date) -> str:
    return f"{DAYS_PT[d.weekday()]} {d.day} {MONTHS_PT[d.month - 1]}"


def parse_date_str(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def days_overdue(d: date) -> int:
    return (today_brt() - d).days
