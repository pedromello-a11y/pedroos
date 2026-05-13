# Pedro OS

Sistema pessoal de captura e organização de tarefas para motion designer com TDAH.

**Duas ferramentas, dois momentos:**
- **WhatsApp** → captura crua em reunião (3 segundos, zero pensamento)
- **Dashboard** → organização deliberada (depois, em bloco)

Tarefas nascem em uma **inbox** com palpite da IA e só viram "organizadas" quando você revisa.

---

## Quick start

```bash
# 1. Clone e configure
cp .env.example .env  # preencher OPENAI_API_KEY e MY_WHATSAPP_JID

# 2. Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. WhatsApp (novo terminal)
cd whatsapp
npm install
npm start  # escaneia o QR code que aparece no terminal

# 4. Frontend
# Abrir frontend/index.html direto no navegador, ou:
cd frontend && python -m http.server 5500
```

---

## Stack

| Camada    | Tech                                          | Por quê                             |
|-----------|-----------------------------------------------|-------------------------------------|
| Backend   | Python 3.11 + FastAPI + SQLAlchemy + SQLite   | Simples, async, banco em arquivo    |
| WhatsApp  | Node.js + Baileys                             | Grátis, funciona                    |
| IA        | OpenAI gpt-4o-mini                            | Parse barato e suficiente           |
| Frontend  | HTML + Alpine.js + Tailwind (CDN)             | Zero build step, reatividade leve   |
| Hosting   | Railway (free tier)                           | Deploy git push                     |

**Custo total:** $0–1/mês (só OpenAI API)

---

## Estrutura

```
pedro-os/
├── CLAUDE.md              # Contexto para Claude Code
├── SPEC.md                # Especificação completa do sistema
├── README.md              # Este arquivo
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI entry point
│   │   ├── db.py          # SQLAlchemy + SQLite
│   │   ├── config.py      # Settings via env
│   │   ├── features/
│   │   │   ├── tasks/     # CRUD de tarefas
│   │   │   ├── projects/  # Projetos guarda-chuva
│   │   │   ├── inbox/     # Inbox / revisão
│   │   │   └── whatsapp/  # Webhook + parser IA
│   │   └── shared/        # Utils, IDs, datas
│   └── requirements.txt
├── whatsapp/
│   ├── index.js           # Baileys com auto-reconnect
│   ├── package.json
│   └── auth_info_baileys/ # sessão (gitignore)
├── frontend/
│   └── index.html         # Dashboard single-file
├── data/
│   └── pedro.db           # SQLite (gitignore)
└── .env.example
```

---

## Filosofia

1. **Uma coisa só, bem feita** — captura e organização de tarefas. Mais nada.
2. **Custo zero** — Baileys e SQLite, sem serviços pagos.
3. **Fricção zero na captura** — WhatsApp aceita texto cru, IA palpita.
4. **Organização deliberada** — dashboard é onde você pensa.
5. **TDAH-friendly** — micro-steps, feedback imediato, atalhos de teclado.

---

## Próximos passos

Ver `SPEC.md` para especificação completa e roadmap em micro-steps.
