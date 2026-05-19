import re
from datetime import date, timedelta
from app.shared.dates import today_brt


_DEADLINE_PATTERNS = [
    (r"\baté\s+", ""),
    (r"\bpara\s+", ""),
    (r"\bpor\s+", ""),
    (r"\bentrega\s+", ""),
]

_PRIORITY_WORDS = {
    "urgente": "p1", "urgência": "p1", "urgencia": "p1", "asap": "p1",
    "crítico": "p1", "critico": "p1", "pegando fogo": "p1", "hoje": "p1",
    "importante": "p2", "alta": "p2", "essa semana": "p2",
    "sem pressa": "backlog", "backlog": "backlog", "quando der": "backlog",
    "futuro": "backlog",
}

_WEEKDAYS = {
    "segunda": 0, "seg": 0,
    "terça": 1, "terca": 1, "ter": 1,
    "quarta": 2, "qua": 2,
    "quinta": 3, "qui": 3,
    "sexta": 4, "sex": 4,
    "sábado": 5, "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}


def _parse_date(token: str) -> date | None:
    today = today_brt()
    t = token.strip().lower()

    if t in ("hoje", "hj", "today"):
        return today
    if t in ("amanhã", "amanha", "manha", "tmr", "tomorrow"):
        return today + timedelta(days=1)
    if t in ("depois de amanhã", "depois de amanha"):
        return today + timedelta(days=2)
    if t in ("semana que vem", "próxima semana", "proxima semana"):
        return today + timedelta(days=7)
    if t in ("fim de semana", "fds"):
        days = (5 - today.weekday()) % 7 or 7
        return today + timedelta(days=days)
    if t in _WEEKDAYS:
        target = _WEEKDAYS[t]
        days_ahead = (target - today.weekday()) % 7 or 7
        return today + timedelta(days=days_ahead)

    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{4}))?$", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            return date(year, month, day)
        except ValueError:
            return None

    m = re.match(r"^dia\s+(\d{1,2})$", t)
    if m:
        day = int(m.group(1))
        try:
            d = date(today.year, today.month, day)
            if d < today:
                month = today.month % 12 + 1
                year = today.year + (1 if today.month == 12 else 0)
                d = date(year, month, day)
            return d
        except ValueError:
            return None

    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def _local_parse(text: str, projects: list) -> dict:
    raw = text.strip()
    working = raw.lower()

    # --- deadline ---
    deadline = None
    deadline_str = None

    # "até/para/por <date_token>" — greedy: grab up to 3 words after keyword
    m = re.search(
        r"\b(?:até|ate|para|por|entrega)\s+((?:dia\s+)?\S+(?:\s+\S+){0,2})",
        working,
    )
    if m:
        candidate = m.group(1)
        # try progressively shorter tokens
        tokens = candidate.split()
        for length in range(len(tokens), 0, -1):
            token = " ".join(tokens[:length])
            d = _parse_date(token)
            if d:
                deadline = d
                deadline_str = m.group(0)
                break

    # standalone weekday / "hoje" / "amanhã" with no prefix
    if not deadline:
        for word in list(_WEEKDAYS.keys()) + ["hoje", "amanhã", "amanha", "fds", "fim de semana"]:
            if re.search(rf"\b{re.escape(word)}\b", working):
                d = _parse_date(word)
                if d:
                    deadline = d
                    deadline_str = word
                    break

    # --- priority ---
    priority = "p3"
    priority_str = None
    for word, pval in _PRIORITY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", working):
            if priority == "p3" or (pval == "p1" and priority != "p1"):
                priority = pval
                priority_str = word

    # --- project slug ---
    project_slug = None
    for proj in projects:
        slug_lower = proj.slug.lower()
        name_lower = proj.name.lower()
        if slug_lower in working or any(w in working for w in name_lower.split() if len(w) > 3):
            project_slug = proj.slug
            break

    # --- build title: strip matched noise from raw text ---
    title = raw
    if deadline_str:
        title = re.sub(re.escape(deadline_str), "", title, flags=re.IGNORECASE).strip()
    if priority_str and priority_str not in ("hoje",):
        title = re.sub(rf"\b{re.escape(priority_str)}\b", "", title, flags=re.IGNORECASE).strip()
    if project_slug:
        title = re.sub(rf"\b{re.escape(project_slug)}\b", "", title, flags=re.IGNORECASE).strip()
        for proj in projects:
            if proj.slug == project_slug:
                title = re.sub(rf"\b{re.escape(proj.name)}\b", "", title, flags=re.IGNORECASE).strip()
                break

    title = re.sub(r"\s{2,}", " ", title).strip(" ,-")
    if not title:
        return {"error": "unclear"}

    title = title[:60]

    return {
        "title": title,
        "project_slug": project_slug,
        "deadline": deadline.isoformat() if deadline else None,
        "priority": priority,
    }


async def parse_message(text: str, projects: list) -> dict:
    from app.config import settings
    import httpx, json

    if settings.openai_api_key:
        today = today_brt()
        projects_list = "\n".join(f"- {p.slug}: {p.name}" for p in projects)
        system_prompt = f"""Você é um parser de tarefas para Pedro, motion designer da Hotmart.

Hoje é {today.strftime('%Y-%m-%d')}.

Projetos ativos:
{projects_list}

Extraia da mensagem:
- title: reescrita clara, verbo no infinitivo, máx 60 chars
- project_slug: APENAS um dos slugs acima ou null
- deadline: YYYY-MM-DD ou null. Interprete "sexta", "amanhã", "semana que vem", "dia 15", "fim de semana", "hoje"
- priority: "p1" se urgente/hoje/ASAP, "p2" se essa semana/importante, "p3" padrão, "backlog" se sem pressa

Se não conseguir extrair um título sensato, retorne {{"error": "unclear"}}.
Responda APENAS JSON, sem markdown."""

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
                    json={
                        "model": settings.openai_model,
                        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
                        "temperature": 0.1,
                        "max_tokens": 200,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                return json.loads(content)
        except Exception as exc:
            print(f"[ai_parser] openai error: {exc} — falling back to local parser")

    return _local_parse(text, projects)
