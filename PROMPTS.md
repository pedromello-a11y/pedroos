# Prompt inicial para o Claude Code

Cole este prompt na primeira sessão do Claude Code dentro da pasta do projeto.

---

## PROMPT 1 — Sessão inicial (leitura e plano)

```
Leia CLAUDE.md e SPEC.md por completo. 

Antes de escrever qualquer código, me responda em texto:

1. Você entendeu a separação entre captura (WhatsApp, inbox) e organização (dashboard)?
2. Quais riscos técnicos você vê na spec que valem revisar agora?
3. Qual a primeira coisa que você implementaria (FDS 1 do roadmap)?

Não comece a codar. Quero validar entendimento primeiro.
```

---

## PROMPT 2 — Após validar entendimento (FDS 1)

```
Vamos começar pelo FDS 1 do SPEC.md (Backend base).

Crie a estrutura do backend conforme seção 8 da spec:
- backend/app/ com main.py, config.py, db.py
- features/tasks/, features/projects/, features/inbox/, features/whatsapp/
- shared/
- tests/ vazio por enquanto
- requirements.txt

Implemente:
1. config.py lendo .env (pydantic-settings)
2. db.py com async engine SQLAlchemy 2.0 + Base + dependency get_db
3. Modelos SQLAlchemy: Task, Project, Checklist, TaskLink (TODOS os campos da seção 3 da spec)
4. Migration automática no lifespan do FastAPI (create_all)
5. Seed dos projetos iniciais (seção 3.1) se a tabela estiver vazia
6. main.py com factory pattern e endpoint GET /api/health

Critério de aceite: rodar `uvicorn app.main:app --reload` e `curl localhost:8000/api/health` retornar `{"status":"ok","db":"ok","ts":"..."}`.

Não implemente CRUD de tasks ainda. Só fundação.
```

---

## PROMPT 3 — FDS 2 (CRUD de tasks)

```
FDS 2 do SPEC.md: CRUD completo de tasks.

Implemente em features/tasks/:
- schemas.py: TaskCreate, TaskUpdate, TaskResponse, TaskDetailResponse (com checklist + links + subtasks)
- service.py: create_task, get_task, list_tasks (com todos os filtros da seção 4.1), update_task, delete_task, review_task, done_task, snooze_task
- router.py: todos os endpoints da seção 4.1, 4.2 e 4.3

Implemente em features/projects/:
- CRUD completo de projetos conforme 4.3

Implemente checklist e links conforme 4.2.

Escreva tests/test_tasks.py cobrindo:
- Criar task, listar com filtros, marcar review, marcar done, snooze
- Idempotência de review (chamar 2x não duplica reviewed_at)
- Cascade delete: deletar task remove checklist e links

Critério de aceite: pytest passa, todos os endpoints funcionam via curl.
```

---

## PROMPTS 4-8

Seguir o roadmap em SPEC.md seção 11, um FDS por sessão limpa do Claude Code.

Importante: **abra uma nova sessão (`/clear` ou nova janela) entre cada FDS** para manter o contexto focado. A spec está no disco, o Claude Code lê de novo a cada sessão.
