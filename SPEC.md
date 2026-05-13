# Pedro OS — Especificação Completa

> Este documento é a fonte da verdade do projeto. Toda decisão de arquitetura, schema, endpoint e UI está aqui. O Claude Code deve seguir esta spec para implementar.

---

## 1. Problema e Filosofia

### 1.1 O problema
Pedro é motion designer na Hotmart, tem TDAH, trabalha com projetos simultâneos (FIRE, Galaxy, Spark, Hotmart, Motion Kit) e recebe demandas por WhatsApp, reuniões, Jira e conversas informais. Sem sistema centralizado, demandas se perdem. Dupla entrada (anotar em dois lugares) leva ao abandono.

### 1.2 Insight central
Existem **dois momentos mentais distintos** que precisam de **duas interfaces distintas**:

| Momento     | Onde        | Como funciona                                              |
|-------------|-------------|------------------------------------------------------------|
| Captura     | WhatsApp    | Texto cru, 3s, IA palpita, vai pra inbox                  |
| Organização | Dashboard   | Revisão deliberada: projeto, prazo, notas, checklist, links|

Tarefas têm um campo `reviewed` (0 = inbox, 1 = organizada). WhatsApp sempre cria com `reviewed=0`. O ato de revisar promove a tarefa.

### 1.3 Princípios
1. Uma coisa só, bem feita — captura e organização de tarefas.
2. Custo zero — Baileys (não Whapi), SQLite (não Postgres pago), HTML puro.
3. Fricção zero na captura — IA pode errar, dashboard corrige.
4. Organização é deliberada — não automática, não obrigatória, mas viciante.
5. TDAH-friendly — micro-steps, atalhos de teclado, feedback imediato.

---

## 2. Stack

```
Backend:    Python 3.11 + FastAPI + SQLAlchemy 2.0 (async) + SQLite + aiosqlite
WhatsApp:   Node.js 20+ + @whiskeysockets/baileys + axios
IA:         OpenAI gpt-4o-mini via httpx
Frontend:   HTML5 + Alpine.js 3 + Tailwind CSS (ambos via CDN)
Fonts:      Space Grotesk (UI) + JetBrains Mono (dados/IDs)
Hosting:    Railway (free tier) — dois serviços
Dev:        uvicorn --reload, npm start
```

---

## 3. Schema (SQLite)

```sql
-- Tabela principal de tarefas
CREATE TABLE tasks (
  id              TEXT PRIMARY KEY,                                  -- UUID
  short_id        TEXT NOT NULL UNIQUE,                              -- 4 chars do UUID
  
  -- Conteúdo
  title           TEXT NOT NULL,                                     -- título limpo
  raw_input       TEXT,                                              -- texto cru do WhatsApp
  description     TEXT,                                              -- notas longas (markdown)
  
  -- Organização
  project_slug    TEXT REFERENCES projects(slug),
  deadline        DATE,
  priority        TEXT CHECK(priority IN ('p1','p2','p3','backlog')) DEFAULT 'p3',
  
  -- Estados
  status          TEXT CHECK(status IN ('todo','doing','blocked','done')) DEFAULT 'todo',
  reviewed        INTEGER DEFAULT 0 CHECK(reviewed IN (0,1)),       -- 0=inbox, 1=organizada
  snoozed_until   DATE,                                              -- pra "adiar revisar"
  
  -- Vínculos
  parent_id       TEXT REFERENCES tasks(id),                         -- subtask
  
  -- Meta
  source          TEXT CHECK(source IN ('whatsapp','dashboard')) DEFAULT 'dashboard',
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  reviewed_at     TEXT,
  completed_at    TEXT,
  updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_tasks_reviewed ON tasks(reviewed, created_at);
CREATE INDEX idx_tasks_status_deadline ON tasks(status, deadline);
CREATE INDEX idx_tasks_project ON tasks(project_slug);
CREATE INDEX idx_tasks_parent ON tasks(parent_id);

-- Projetos guarda-chuva
CREATE TABLE projects (
  slug            TEXT PRIMARY KEY,         -- 'fire-26'
  name            TEXT NOT NULL,            -- 'FIRE 26'
  description     TEXT,                     -- briefing curto
  deadline        DATE,                     -- deadline final do projeto
  color           TEXT,                     -- hex pra UI
  active          INTEGER DEFAULT 1 CHECK(active IN (0,1)),
  position        INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_projects_active ON projects(active, position);

-- Checklist dentro de uma tarefa (não é subtask)
CREATE TABLE checklist (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  text            TEXT NOT NULL,
  done            INTEGER DEFAULT 0 CHECK(done IN (0,1)),
  position        INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_checklist_task ON checklist(task_id, position);

-- Links externos (Drive, Figma, Frame.io)
CREATE TABLE task_links (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  url             TEXT NOT NULL,
  label           TEXT,                     -- "Drive", "Figma", "Frame.io"
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_links_task ON task_links(task_id);

-- Idempotência do WhatsApp (evita task duplicada por re-envio do Baileys)
CREATE TABLE wa_processed (
  message_id      TEXT PRIMARY KEY,
  processed_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.1 Seed inicial (projetos)
Ao subir o banco pela primeira vez, popular:
```python
SEED_PROJECTS = [
    ("galaxy-26", "Galaxy 26", "Evento corporativo com vídeos personalizados", "#8B5CF6"),
    ("fire-26", "FIRE 26", "Evento principal Hotmart, filme de abertura", "#EF4444"),
    ("spark", "Spark", "Evento menor, screensaver e countdown", "#F59E0B"),
    ("hotmart", "Hotmart", "Demandas gerais da marca", "#FF4000"),
    ("motion-kit", "Motion Kit", "Sistema de componentes reutilizáveis", "#10B981"),
    ("aftermovie-q1", "Aftermovie Q1", "Vídeo de retrospectiva do trimestre", "#06B6D4"),
    ("pessoal", "Pessoal", "Tarefas pessoais e administrativas", "#6B7280"),
]
```

---

## 4. API

Todas as rotas têm prefixo `/api`. Todas retornam JSON. Erros como `{ "detail": "mensagem em PT-BR" }`.

### 4.1 Tarefas

```
GET    /api/tasks                          # lista tasks
       ?reviewed=0|1                       # inbox vs organizadas
       ?status=todo|doing|blocked|done
       ?project=<slug>
       ?deadline=today|overdue|week|null
       ?parent_id=<id>                     # buscar subtasks de uma task

POST   /api/tasks                          # cria task (dashboard)
       body: { title, project_slug?, deadline?, priority?, description?, source?='dashboard', reviewed?=1 }

GET    /api/tasks/{id}                     # detalhe incluindo checklist + links + subtasks
PATCH  /api/tasks/{id}                     # atualiza campos parciais
DELETE /api/tasks/{id}                     # remove permanentemente

POST   /api/tasks/{id}/review              # marca reviewed=1, seta reviewed_at
POST   /api/tasks/{id}/done                # marca status=done, seta completed_at
POST   /api/tasks/{id}/snooze              # body: { days: 1 } — seta snoozed_until
```

### 4.2 Checklist e Links

```
POST   /api/tasks/{id}/checklist           # body: { text }
PATCH  /api/checklist/{item_id}            # body: { text?, done?, position? }
DELETE /api/checklist/{item_id}

POST   /api/tasks/{id}/links               # body: { url, label? }
DELETE /api/links/{link_id}
```

### 4.3 Projetos

```
GET    /api/projects                       # lista todos ativos por position
       ?active=0|1
POST   /api/projects                       # body: { name, description?, deadline?, color? }
PATCH  /api/projects/{slug}                # atualiza
DELETE /api/projects/{slug}                # só se active=0 e sem tasks
```

### 4.4 WhatsApp

```
POST   /api/whatsapp/webhook               # chamado pelo Baileys
       body: { message_id, from, text }
       comportamento:
         1. cheque idempotência em wa_processed
         2. detecte comando (?, hoje, done X, prazo X, cancelar)
         3. se não for comando, mande pra IA parsear
         4. crie task com reviewed=0, source=whatsapp, raw_input=text
         5. responda via /send do Baileys
```

### 4.5 Health

```
GET    /api/health                         # { status: "ok", db: "ok", ts: <iso> }
```

---

## 5. Lógica do WhatsApp

### 5.1 Comandos (parseados antes da IA)

| Input do usuário          | Ação                                                      | Resposta                                              |
|---------------------------|-----------------------------------------------------------|-------------------------------------------------------|
| `?` ou `hoje`             | Lista tasks com deadline ≤ hoje, status=todo              | Lista compacta numerada                              |
| `atrasadas`               | Lista deadline < hoje                                     | Lista                                                |
| `inbox`                   | Conta tasks reviewed=0                                    | "📥 5 tarefas pra revisar"                            |
| `done <short_id>`         | Marca task como done                                      | "✅ #a3f2 concluída"                                  |
| `prazo <data>`            | Atualiza deadline da última task criada                   | "📅 #a3f2 · prazo atualizado pra qui 14 mai"          |
| `cancelar` ou `desfazer`  | Delete a última task criada nos últimos 60s               | "🗑️ #a3f2 cancelada"                                  |
| `projeto <slug>`          | Atribui projeto à última task                             | "📁 #a3f2 · FIRE 26"                                  |
| Qualquer outro texto      | Manda pra IA parsear                                      | Ver 5.3                                              |

### 5.2 System prompt da IA (gpt-4o-mini)

```
Você é um parser de tarefas para Pedro, motion designer da Hotmart.

Hoje é {data_atual_brt} ({dia_semana}).

Projetos ativos:
{lista_projetos_com_slug}

Extraia da mensagem:
- title: reescrita clara, verbo no infinitivo, máx 60 chars
- project_slug: APENAS um dos slugs acima ou null se duvidar
- deadline: YYYY-MM-DD ou null. Interprete "sexta", "amanhã", "semana que vem", "dia 15", "fim de semana"
- priority: 
  - "p1" se urgente, hoje, ASAP, pegando fogo, crítico
  - "p2" se essa semana, importante, alta
  - "p3" padrão (sempre que não houver indicação clara)
  - "backlog" se sem pressa, futuro, quando der

Regras:
- Se a mensagem mencionar projeto que NÃO está na lista, retorne project_slug=null
- Se a data for ambígua, retorne deadline=null (errar pra menos)
- Se não conseguir extrair um título sensato, retorne {"error": "unclear"}

Responda APENAS JSON, sem markdown, sem ```.
Formato: {"title": "...", "project_slug": "...", "deadline": "...", "priority": "..."}
```

### 5.3 Formato de resposta

**Sucesso, tudo parseado:**
```
📥 #a3f2 · FIRE 26 · qui 14 mai · 🔺
"editar abertura do FIRE"
```

**Sucesso, projeto null:**
```
📥 #a3f2 · sem projeto · qui 14 mai · 🔺
"editar abertura FIRE"
💡 manda "projeto fire-26" pra ajustar
```

**Sucesso, deadline null:**
```
📥 #a3f2 · FIRE 26 · sem prazo
"editar abertura FIRE"
💡 manda "prazo sexta" pra ajustar
```

**Erro de parse:**
```
❓ não entendi. tenta: "editar abertura FIRE até sexta urgente"
```

**Listagem (comando `?` ou `hoje`):**
```
📋 hoje · 3 tarefas

🔺 #a3f2 · FIRE 26 · editar abertura
🔸 #b7c1 · Galaxy · revisar projetor
⚪ #d4e8 · Motion Kit · ajustar template

⚠️ 1 atrasada
🔺 #f2a1 · Spark · countdown (-2 dias)
```

---

## 6. Dashboard

### 6.1 Layout geral

```
┌─────────────────────────────────────────────────────────────────────┐
│ Pedro OS                                       🟢 conectado     ⚙️  │
├─────────────────────────────────────────────────────────────────────┤
│ [📥 Inbox 5] [☀️ Hoje 3] [📅 Próximas] [📦 Backlog] [📁 Projetos] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   <conteúdo da aba ativa>                                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

- Badge no título do navegador: `(5) Pedro OS` mostra contador da inbox
- Auto-abertura: se `inbox.count > 8`, abre direto na aba Inbox; senão, abre em Hoje
- Atalhos: `I`=inbox, `H`=hoje, `P`=próximas, `B`=backlog, `J`=projetos, `N`=nova task

### 6.2 Aba INBOX (a mais importante)

A inbox é onde o trabalho real de organização acontece. Cada card mostra:

```
┌──────────────────────────────────────────────────────────────────┐
│ #a3f2                                          criado 14:32 hoje │
│                                                                  │
│ ┌─ texto original ─────────────────────────────────────────────┐│
│ │ "editar a abertura do FIRE até quinta urgente"               ││
│ └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│ Título: [editar abertura FIRE                              ]    │
│ Projeto: [📁 FIRE 26              ▼]                            │
│ Prazo:   [📅 14/05/2026 ▼]   Prioridade: [🔺 Urgente ▼]         │
│                                                                  │
│ Notas:   [_____________________________________________]         │
│          [_____________________________________________]         │
│                                                                  │
│ [+ checklist]  [+ link]  [+ subtask]                             │
│                                                                  │
│                  [🗑️ descartar]  [⏰ snooze 1d]  [✓ revisada]    │
└──────────────────────────────────────────────────────────────────┘
```

**Comportamento:**
- Cada card já vem pré-preenchido com o palpite da IA
- Edição é inline e auto-save (debounce 500ms) — sem botão "salvar"
- Botão "revisada" marca `reviewed=1` e remove da inbox com fade-out
- "Snooze 1d" tira da inbox até amanhã
- "Descartar" deleta a task (com undo de 5s via toast)
- Ordem: criadas mais recentes primeiro

### 6.3 Aba HOJE

```
┌─────────────────────────────────────────────────────────────────┐
│ ☀️ Hoje · 10 mai · domingo                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ⚠️ Atrasadas (1)                                                │
│ ┌─────────────────────────────────────────────────────────────┐│
│ │ 🔺 #f2a1 · Spark · countdown        atrasada 2 dias    [✓] ││
│ └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│ Hoje (3)                                                        │
│ ┌─────────────────────────────────────────────────────────────┐│
│ │ 🔺 #a3f2 · FIRE 26 · editar abertura              hoje [✓] ││
│ │ 🔸 #b7c1 · Galaxy · revisar projetor              hoje [✓] ││
│ │ ⚪ #d4e8 · Motion Kit · ajustar template          hoje [✓] ││
│ └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

- Clique no card → abre modal de edição (ver 6.6)
- Botão `[✓]` no canto → marca como done com animação
- Mostra só `reviewed=1` (tarefas inbox NÃO aparecem aqui)

### 6.4 Aba PRÓXIMAS

Tasks com `deadline > hoje`, reviewed=1, ordenadas por deadline crescente. Agrupadas por semana:

```
📅 Esta semana
  qua 13 mai · 🔸 #b7c1 · Galaxy · revisar com Marcela
  qui 14 mai · 🔺 #a3f2 · FIRE 26 · editar abertura

📅 Próxima semana
  seg 18 mai · ⚪ #c2d5 · Motion Kit · documentar template
```

### 6.5 Aba BACKLOG

Tasks com `deadline=NULL`, reviewed=1, agrupadas por projeto. Útil pra capacidade ociosa.

### 6.6 Modal de edição completa

Quando clica em qualquer card (de qualquer aba), abre modal full:

```
┌────────────────────────────────────────────────────────────────┐
│ editar abertura FIRE                              #a3f2    [✕] │
│ ──────────────────────────                                     │
│                                                                │
│  📁 FIRE 26 ▼    📅 qui 14 mai ▼    🔺 Urgente ▼               │
│  Status: ⚪ a fazer · 🟡 fazendo · 🔴 bloqueada · ✅ feita      │
│                                                                │
│  ─── Notas (markdown) ─────────────────────────────────────    │
│  Léo entrega arte até quarta.                                  │
│  Cavazza aprovou referência Apple Vision.                      │
│  Exportar 4K com legenda embutida.                             │
│                                                                │
│  ─── Checklist ────────────────────────────────────────────    │
│  ☑ Receber arte do Léo                                         │
│  ☐ Gravar VO                                                   │
│  ☐ Importar trilha do Artlist                                  │
│  ☐ Exportar 4K                                                 │
│  [+ adicionar item]                                            │
│                                                                │
│  ─── Links ────────────────────────────────────────────────    │
│  🔗 Drive — pasta do projeto                              [✕]  │
│  🔗 Frame.io — review                                     [✕]  │
│  [+ adicionar link]                                            │
│                                                                │
│  ─── Subtasks ─────────────────────────────────────────────    │
│  ☐ #b7c1 · revisar com Cavazza · sex 15 mai               [→]  │
│  [+ adicionar subtask]                                         │
│                                                                │
│  ─── Histórico ────────────────────────────────────────────    │
│  Capturada 10/05 14:32 via WhatsApp                            │
│  Original: "editar a abertura do FIRE até quinta urgente"      │
│  Revisada 10/05 18:05                                          │
│                                                                │
│  [🗑️ excluir]                              [Esc para fechar]   │
└────────────────────────────────────────────────────────────────┘
```

**Atalhos no modal:**
- `Esc` fecha
- `Cmd+Enter` salva e fecha
- `Tab` navega campos
- `Cmd+K` foco no campo de notas

### 6.7 Aba PROJETOS

Lista todos os projetos ativos com contador de tasks. Clique abre página do projeto:

```
┌─────────────────────────────────────────────────────────────────┐
│ 📁 FIRE 26                                            [✏️ editar]│
│ Evento principal Hotmart · 🎯 prazo final: 12 jun 2026         │
│                                                                 │
│ ─── Briefing ───────────────────────────────────────────────    │
│ Filme de abertura motivacional, tradição Nike/Apple.           │
│ Target: criadores digitais. Tema: "nunca mais para".            │
│                                                                 │
│ ─── 8 tarefas ativas ──────────────────────────────────────    │
│ 🔺 hoje      · editar abertura                                 │
│ 🔸 qui 14    · gravar VO Léo                                   │
│ ⚪ seg 18    · exportar 4K                                     │
│ ...                                                             │
│                                                                 │
│ ─── 3 concluídas (últimos 30 dias) ────────────────────────    │
│ ✓ aprovar referência (concluído 8 mai)                         │
│ ...                                                             │
└─────────────────────────────────────────────────────────────────┘
```

### 6.8 Dump rápido (presente em todas as abas)

Floating button no canto inferior direito ou input fixo no header:
```
[+ nova tarefa rápida...                          ⏎]
```
- Enter cria task com `reviewed=1` (não vai pra inbox, já é organizada)
- Se quiser detalhes, botão `[+]` abre modal de criação

---

## 7. Baileys (whatsapp/index.js)

Comportamento obrigatório:

```js
// 1. Conexão com auto-reconnect
function connect() {
  // useMultiFileAuthState('auth_info_baileys')
  // listener 'connection.update':
  //   - if qr → print no terminal (qrcode-terminal)
  //   - if 'open' → log conectado
  //   - if 'close' → checar DisconnectReason
  //     - se loggedOut → log e parar
  //     - senão → reconnect com backoff de 3s
}

// 2. Filtros obrigatórios em messages.upsert
//    - type !== 'notify' → ignora
//    - msg.key.fromMe → ignora
//    - msg.key.remoteJid !== process.env.MY_WHATSAPP_JID → ignora
//    - msg.key.remoteJid.endsWith('@g.us') → ignora (grupos)
//    - sem texto extraível → ignora

// 3. POST pro backend com idempotência
//    axios.post(`${BACKEND_URL}/api/whatsapp/webhook`, {
//      message_id: msg.key.id,
//      from: msg.key.remoteJid,
//      text: text
//    })
//    timeout 10s, log erros mas não trava

// 4. Endpoint /send (Express ou Fastify)
//    POST /send { to, text } → sock.sendMessage(to, { text })
//    chamado pelo backend pra responder ao usuário
```

### 7.1 Variáveis de ambiente
```
MY_WHATSAPP_JID=5531999999999@s.whatsapp.net
BACKEND_URL=http://localhost:8000
PORT=3000
```

### 7.2 package.json
```json
{
  "name": "pedro-os-whatsapp",
  "version": "0.1.0",
  "type": "module",
  "scripts": { "start": "node index.js" },
  "dependencies": {
    "@whiskeysockets/baileys": "^6.7.0",
    "axios": "^1.7.0",
    "express": "^4.19.0",
    "qrcode-terminal": "^0.12.0",
    "dotenv": "^16.4.0"
  }
}
```

---

## 8. Backend — arquitetura

### 8.1 Estrutura
```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # factory + lifespan + include_routers
│   ├── config.py            # Settings pydantic-settings
│   ├── db.py                # async engine + session + Base
│   ├── features/
│   │   ├── tasks/
│   │   │   ├── __init__.py
│   │   │   ├── models.py    # Task, Checklist, TaskLink (SQLAlchemy)
│   │   │   ├── schemas.py   # TaskCreate, TaskUpdate, TaskResponse
│   │   │   ├── service.py   # lógica de negócio
│   │   │   └── router.py    # endpoints
│   │   ├── projects/
│   │   ├── inbox/           # endpoints específicos de revisão
│   │   └── whatsapp/
│   │       ├── router.py    # webhook
│   │       ├── ai_parser.py # chamada gpt-4o-mini
│   │       ├── commands.py  # parser de comandos
│   │       └── sender.py    # chama /send do Baileys
│   └── shared/
│       ├── ids.py           # uuid + short_id
│       ├── dates.py         # parse PT-BR, BRT
│       └── responses.py     # formatadores de resposta WhatsApp
├── tests/
│   ├── test_tasks.py
│   └── test_whatsapp.py
├── requirements.txt
└── .env.example
```

### 8.2 requirements.txt
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.36
aiosqlite==0.20.0
pydantic==2.9.0
pydantic-settings==2.6.0
httpx==0.27.0
python-dotenv==1.0.0
pytest==8.3.0
pytest-asyncio==0.24.0
```

### 8.3 config.py
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/pedro.db"
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    whatsapp_send_url: str = "http://localhost:3000/send"
    my_whatsapp_jid: str
    cors_origins: list[str] = ["http://localhost:5500", "http://localhost:8000"]
    timezone: str = "America/Sao_Paulo"
    
    class Config:
        env_file = ".env"
```

### 8.4 .env.example
```
OPENAI_API_KEY=sk-...
MY_WHATSAPP_JID=5531999999999@s.whatsapp.net
DATABASE_URL=sqlite+aiosqlite:///./data/pedro.db
WHATSAPP_SEND_URL=http://localhost:3000/send
```

---

## 9. Frontend (single-file)

`frontend/index.html` com:
- Tailwind via CDN: `<script src="https://cdn.tailwindcss.com"></script>`
- Alpine.js via CDN: `<script defer src="https://unpkg.com/alpinejs@3"></script>`
- Google Fonts: Space Grotesk + JetBrains Mono
- Dark theme (default)

### 9.1 Estrutura do componente Alpine
```js
function pedroOS() {
  return {
    activeTab: 'inbox',
    tasks: [],
    inbox: [],
    projects: [],
    selectedTask: null,
    
    init() {
      this.loadAll();
      this.setupKeyboardShortcuts();
      this.startPolling();  // 30s, atualiza inbox e contador
    },
    
    async loadAll() { /* fetch /api/tasks, /api/projects */ },
    async reviewTask(id) { /* POST /api/tasks/:id/review */ },
    async doneTask(id) { /* POST /api/tasks/:id/done */ },
    // ...
  }
}
```

### 9.2 Polling em vez de WebSocket
Para manter simples, frontend faz polling a cada 30s no `/api/health` e `/api/tasks?reviewed=0&count=1` pra atualizar o badge da inbox sem refresh total.

---

## 10. Deploy no Railway

### 10.1 railway.toml
```toml
[build]
builder = "nixpacks"

[[services]]
name = "backend"
source = "backend"

[services.backend.deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/api/health"

[[services]]
name = "whatsapp"
source = "whatsapp"

[services.whatsapp.deploy]
startCommand = "node index.js"
```

### 10.2 Volume persistente
Railway monta um volume em `/data` para persistir:
- `data/pedro.db` (SQLite)
- `whatsapp/auth_info_baileys/` (sessão WhatsApp)

Sem volume, perde tudo a cada deploy.

---

## 11. Roadmap em micro-steps

Calibrado para fins de semana de ~4h de trabalho focado.

### FDS 1 — Backend base
- [ ] Estrutura de pastas + venv + requirements
- [ ] `config.py` lendo .env
- [ ] `db.py` com engine async + Base + dependency
- [ ] Modelos SQLAlchemy: Task, Project, Checklist, TaskLink
- [ ] Migration inicial (criar tabelas no startup) + seed de projetos
- [ ] Endpoint `GET /api/health` funcionando
- [ ] **Critério:** `curl localhost:8000/api/health` retorna `{"status":"ok"}`

### FDS 2 — CRUD de tasks
- [ ] Schemas Pydantic (TaskCreate, TaskUpdate, TaskResponse)
- [ ] `features/tasks/service.py` com CRUD básico
- [ ] `features/tasks/router.py` com todos os endpoints
- [ ] `POST /api/tasks/:id/review`, `/done`, `/snooze`
- [ ] CRUD de checklist e links
- [ ] CRUD de projetos
- [ ] **Critério:** Suíte de testes pytest passando, criar/listar/marcar via curl

### FDS 3 — IA + WhatsApp webhook
- [ ] `features/whatsapp/ai_parser.py` chamando gpt-4o-mini
- [ ] `features/whatsapp/commands.py` parseando `?`, `done X`, `prazo X`, etc
- [ ] `features/whatsapp/router.py` com `POST /api/whatsapp/webhook`
- [ ] Lógica de idempotência (`wa_processed`)
- [ ] `sender.py` chamando `/send` do Baileys (mock por enquanto)
- [ ] **Critério:** POST manual no webhook cria task com palpite da IA

### FDS 4 — Baileys
- [ ] `whatsapp/index.js` com Baileys + Express
- [ ] Filtros: só DM, só meu JID, só texto, ignora própria mensagem
- [ ] Auto-reconnect com backoff
- [ ] Endpoint `/send` recebendo do backend
- [ ] **Critério:** Mando texto pelo celular, vira task no banco em <3s

### FDS 5 — Dashboard estrutura
- [ ] `frontend/index.html` com tabs (inbox, hoje, próximas, backlog, projetos)
- [ ] Alpine component conectado no backend
- [ ] Lista de tasks em cada aba renderizando certo
- [ ] Atalhos de teclado (I, H, P, B, J, N)
- [ ] Auto-redirect pra inbox se count > 8
- [ ] **Critério:** Navego entre abas, vejo tasks, contador na inbox correto

### FDS 6 — Inbox + revisão
- [ ] Cards da inbox com pré-preenchimento da IA
- [ ] Edição inline com auto-save (debounce 500ms)
- [ ] Botão "revisada" + animação fade-out
- [ ] Snooze 1d
- [ ] Descartar com toast de undo
- [ ] **Critério:** Reviso 5 tasks em sequência sem fricção

### FDS 7 — Modal de edição completa
- [ ] Modal abre ao clicar em qualquer task
- [ ] Edição de todos os campos
- [ ] CRUD de checklist e links no modal
- [ ] Atribuir subtask
- [ ] Histórico (raw_input + datas)
- [ ] Atalhos no modal (Esc, Cmd+Enter)
- [ ] **Critério:** Modal é prazeroso de usar com teclado

### FDS 8 — Página de projeto + deploy
- [ ] `/projetos/:slug` no frontend
- [ ] Briefing editável
- [ ] Lista de tasks ativas + concluídas
- [ ] `railway.toml` configurado
- [ ] Volume persistente montado
- [ ] Deploy funcionando, sessão Baileys persistida
- [ ] **Critério:** URL pública funciona pelo celular, mando WhatsApp, vejo no celular

### FDS 9 — Uso real (2 semanas, NÃO MEXE NO CÓDIGO)
- [ ] Use o sistema diariamente
- [ ] Anote fricções num arquivo `IDEIAS.md`
- [ ] Não implemente nada novo
- [ ] **Critério:** No fim das 2 semanas, decida o que vale construir

### FDS 10+ — Iteração baseada no uso real

---

## 12. Decisões e trade-offs documentados

| Decisão                              | Por quê                                    | Trade-off                            |
|--------------------------------------|--------------------------------------------|--------------------------------------|
| SQLite em vez de Postgres            | Custo zero, arquivo único, suficiente      | Migration futura se quiser multi-user|
| Baileys em vez de Whapi              | Grátis                                     | Fragilidade quando WhatsApp atualiza |
| Polling em vez de WebSocket          | Simplicidade                               | Latência de 30s para updates         |
| HTML single-file em vez de framework | Zero build, fácil deploy                   | Pode ficar grande se o app crescer   |
| Alpine em vez de vanilla JS          | Reatividade leve sem build                 | +15kb na página                      |
| Tabs em vez de coluna fixa pra inbox | Foco em um trabalho por vez (TDAH)         | Mais cliques                         |
| IA palpita em vez de inbox crua      | Aproveita captura pra acelerar revisão     | Pode confundir se errar muito        |
| Sem auth                             | Single-user, deploy privado                | Não compartilhável                   |

---

## 13. O que NÃO está no escopo (não construir)

- ❌ Integração Google Calendar (Fase 1)
- ❌ Integração Jira (Fase 1)
- ❌ Captura de áudio (Whisper) (Fase 1)
- ❌ Captura de imagem (visão GPT-4o) (Fase 2)
- ❌ Resumo diário às 9h via WhatsApp (Fase 1)
- ❌ Capacidade do dia / score / agendamento inteligente (Fase 3)
- ❌ Multi-usuário (provavelmente nunca)
- ❌ Mobile app nativo (PWA é suficiente)

Adicionar essas features antes de validar o core é o caminho mais curto pro abandono. **Use 2 semanas antes de adicionar qualquer coisa.**

---

## 14. Riscos conhecidos

1. **Baileys quebra periodicamente** quando o WhatsApp atualiza o protocolo. Solução: atualizar `@whiskeysockets/baileys`, possivelmente re-scan do QR. Esperado a cada 3-6 meses.

2. **Dupla entrada com Jira.** Tarefas do squad estão no Jira E no Pedro OS. Sem integração na Fase 0, é aceito como custo até a Fase 1.

3. **Captura demais sem revisar.** Risco real: inbox enche e vira ruído. Mitigação: badge no título do navegador + auto-redirect se >8 itens criam pressão saudável.

4. **TDAH e novidade.** O prazer está em construir. Disciplina: parar em FDS 8, usar 2 semanas, decidir.

---

## 15. Critério de sucesso

Em 4 semanas de uso real:
- ✅ Mais de 70% das tarefas reais entraram via Pedro OS → **continua**
- ❌ Menos que isso → **mata o projeto, volta pro Jira/papel**

Honestidade aqui é mais valiosa que orgulho. O sistema é meio, não fim.
