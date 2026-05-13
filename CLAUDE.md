# Pedro OS — Contexto do Projeto

## O que é

Sistema pessoal de captura/organização de tarefas para Pedro (motion designer Hotmart, TDAH). Captura via WhatsApp na reunião, organização via dashboard depois. Tarefas têm estado `reviewed` (0 = inbox, 1 = organizada).

## Stack

- **Backend:** Python 3.11 + FastAPI + SQLAlchemy + SQLite (arquivo único)
- **WhatsApp:** Node.js + Baileys (auto-reconnect, sessão persistida)
- **IA:** OpenAI gpt-4o-mini para parse de linguagem natural
- **Frontend:** HTML single-file + Alpine.js + Tailwind via CDN (zero build)
- **Hosting:** Railway free tier

## Estrutura

```
backend/app/
├── main.py            # FastAPI factory + CORS + lifespan
├── db.py              # engine, Base, get_db dependency
├── config.py          # Settings (pydantic-settings)
├── features/
│   ├── tasks/         # router.py + service.py + schemas.py + models.py
│   ├── projects/
│   ├── inbox/
│   └── whatsapp/      # webhook + ai_parser.py + commands.py
└── shared/            # short_id, datas em BRT
```

## Convenções

- **Async-first:** rotas e dependências `async def`. SQLAlchemy 2.0 async.
- **Schemas Pydantic** separados de modelos SQLAlchemy. Request vs Response distintos.
- **Repositories não necessários** neste tamanho — service.py consulta direto.
- **IDs:** UUIDs como TEXT no SQLite. `short_id` = primeiros 4 chars do UUID, único.
- **Timezone:** BRT (America/Sao_Paulo) em todo lugar. Datas YYYY-MM-DD.
- **Erros:** HTTPException com mensagem em PT-BR no `detail`.

## Comandos

```bash
# Backend
uvicorn app.main:app --reload --port 8000
pytest                                    # tests/

# WhatsApp
cd whatsapp && npm start

# Lint
ruff check backend/
```

## Regras importantes

- **NUNCA** crie tasks duplicadas — sempre cheque `wa_processed.message_id` antes.
- **NUNCA** processe mensagens de grupos (`@g.us`) ou de outras pessoas — só `MY_WHATSAPP_JID`.
- **SEMPRE** salve `raw_input` original do WhatsApp mesmo quando a IA estruturar.
- **SEMPRE** marque `reviewed=0` em tasks criadas via WhatsApp.
- A pasta `whatsapp/auth_info_baileys/` é a sessão — backup ela, não commite.
- SQLite usa `check_same_thread=False` e modo WAL.

## Verificação

Antes de considerar uma feature pronta:
1. Endpoint testado com `curl` (ou `httpx` em pytest)
2. Frontend atualiza após a ação sem F5
3. Funciona pelo celular (WhatsApp + dashboard mobile)

## Referências

- Especificação completa: `@SPEC.md`
- README: `@README.md`
