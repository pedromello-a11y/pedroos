from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/pedro.db"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    wa_gateway_url: str = "http://localhost:3000"
    my_whatsapp_jid: str = ""
    alfred_group_jid: str = "120363426318370449@g.us"
    cors_origins: List[str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
    ]
    timezone: str = "America/Sao_Paulo"

    # Jira integration
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_jql: str = 'assignee = currentUser() AND status in ("Em andamento", "In Progress", "Pending", "PENDING", "To Do") ORDER BY updated DESC'

    # Google Calendar (OAuth2)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    google_refresh_token: str = ""  # preenchido automaticamente após o primeiro login

    # Google Calendar (fallback ICS — só funciona se a agenda for pública)
    google_calendar_ics_url: str = ""

    # Agenda pessoal (ICS privado)
    personal_calendar_ics_url: str = ""

    # Agenda pessoal (Google Calendar ID para escrita via OAuth2)
    personal_calendar_id: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
