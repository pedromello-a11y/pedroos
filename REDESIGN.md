# REDESIGN.md — Proposta de Redesign Pedro OS

## 1. Contexto e Dor Principal

### Quem é o Pedro
- Motion designer na Hotmart, trabalha com múltiplos projetos simultâneos (FIRE, Galaxy, Explorer, Spark, Hotmart, Motion Kit)
- Tem TDAH diagnosticado
- Memória muito ruim — se não anotar, esquece completamente (até coisas simples como enviar um email)
- Extremamente visual — texto puro não funciona, precisa de hierarquia espacial e peso visual

### O que o sistema resolve
O Pedro OS é um **segundo cérebro externo**. O benefício principal NÃO é "fazer tarefas mais rápido" — é dar **segurança psicológica** de que nada foi esquecido.

> "Quando olho pro dashboard quero ter clareza que tenho tudo que preciso ali nesse painel. Não preciso ficar com medo e ficar pensando e repensando se tem mais coisas pra fazer."

### A dor central
**Paralisia por falta de hierarquia.** Quando tudo parece ter o mesmo peso visual, o cérebro TDAH não consegue fazer triage e trava.

> "Tinham muitas tarefas ativas, fiquei sem saber o que priorizar pra onde ir. Só via texto e não uma organização. Não consegui decidir o que fazer e continuei paralisado."

### Duas necessidades opostas que coexistem
1. **"Está tudo aqui, posso relaxar"** → ver o volume total dá segurança
2. **"Sei exatamente o que fazer agora"** → hierarquia visual destrava a ação

---

## 2. O que "visual" significa pro Pedro

NÃO é:
- Cores decorativas (cores dos projetos não ajudam a categorizar)
- Muita informação bonita
- Cards enfeitados

É:
- **Peso e espaço** — o tamanho do elemento comunica importância
- **Ausência como informação** — o vazio na timeline da agenda comunica "tempo livre" melhor que um número
- **Hierarquia por opacidade/tamanho** — o que importa é grande e sólido, o que é secundário é pequeno e translúcido
- **Bater o olho e ter um sentimento** — não precisa ler cada item, o layout como um todo transmite o estado

Exemplo que funciona: a agenda vertical. A linha continua mesmo sem eventos, dando peso visual ao tempo. Não precisa de cards com horários escritos — a posição no eixo vertical JÁ É a informação.

---

## 3. Como o Pedro usa o sistema

### Rotina
- Dashboard fica na segunda tela (monitor secundário)
- Olha várias vezes ao dia entre tarefas
- Não é "abre de manhã e planeja" — é referência constante

### Como decide o que fazer
- Principalmente por **deadline** (o que vence primeiro)
- Às vezes por **demandas pequenas que destravam** (se não fizer, fico travado)
- O destaque do "Fazendo" ajuda a não perder o fio da meada

### Sobre tarefas em paralelo
- Às vezes coordena o trabalho de alguém enquanto faz outra coisa
- Isso não é "fazendo duas coisas" — é "uma ativa + outras no radar"
- Só pode ter **1 "Fazendo"** por vez (decisão de design)
- O que está coordenando/esperando vai pra "No Radar"

### Status note
- Usa bastante
- É crucial ver na lista (não só dentro do modal)
- Exemplos: "aguardando arte do Léo", "esperando resposta do dublador", "bater roteiro"
- Dá contexto instantâneo de por que aquela tarefa está parada ou o que falta

### Modal da tarefa
- Junta TODAS as informações sobre a tarefa: links, notas, referências, checklist
- Checklist é usado pra destravar: passos sequenciais do que precisa fazer
- Links são acessados durante execução (abre Drive, Frame.io, etc)
- Lembrete (remind_at) é muito importante

---

## 4. Sistema de Status (Novo)

| Status | Significado | Quando usar |
|---|---|---|
| **Fazendo** | Estou ativamente trabalhando nisso AGORA | Só 1 por vez |
| **A Fazer** | Depende de mim, é pra breve | Tarefas que preciso executar |
| **No Radar** | Depende de alguém/algo, estou monitorando | Esperando resposta, coordenando trabalho de outro |
| **Backlog** | Existe, sem urgência, não é pra agora | Gaveta de futuro |

### Mudanças vs. sistema atual
- **Removido:** "Na Fila" (não tinha significado claro)
- **Removido:** "Queued" (confundia com "A Fazer")
- **Adicionado:** "No Radar" (substitui o "Esperando/Aguardando" genérico)
- **Mantido:** Backlog (colapsado visualmente)

### Regras
- "No Radar" SEMPRE tem status note (o que está esperando)
- "Fazendo" é limitado a 1 tarefa
- "A Fazer" é ordenado por deadline (mais urgente no topo)
- "Backlog" fica colapsado por padrão

---

## 5. Layout do Dashboard (Nova Proposta)

### Estrutura geral

```
HEADER: PedroOS · [Hotmart|Pessoal] · capture input · status dots

MAIN (flex-1)                          SIDEBAR (300px fixa)
├── FAZENDO (hero card, 1 tarefa)      ├── Data / Hora
├── A FAZER (lista, ordenada)          ├── Barra de tempo do dia
├── ┈┈ no radar ┈┈ (muted, inline)     ├── AGENDA (timeline vertical)
├── ▸ Backlog (colapsado)              ├── Alertas (atrasadas)
└── SEMANA (timeline semanal)          ├── JIRA (pendentes)
                                        └── INBOX (badge/mini)
```

### Zona FAZENDO (Hero Card)
- Card grande com padding generoso
- Título em 20px bold
- Nome do projeto
- Status note visível
- Checklist inline (próximos passos)
- Botão "✓ Concluir" proeminente
- Botão "↻ Trocar foco"
- Se vazio: estado zen com CTA "Escolher próxima"

### Zona A FAZER
- Lista de rows compactas mas legíveis
- Cada row: título · projeto · deadline (se houver)
- Ordenada por deadline crescente / prioridade
- Clique → abre modal
- Botão discreto pra "▶ Fazer agora" (promove a Fazendo)

### Zona NO RADAR
- Separada por divisor sutil: `┈┈┈ no radar ┈┈┈`
- Rows com opacity reduzida (~60%)
- Borda tracejada (dashed)
- Status note como informação principal (mais destaque que o título)
- Formato: `◌ Título · status note`
- Não tem deadline visível (não é pra agir)
- Não compete visualmente com "A Fazer"

### Zona BACKLOG
- Colapsado por padrão
- Apenas: `▸ Backlog (N)` clicável
- Quando expandido: lista ultra-compacta, opacity 50%

### SIDEBAR
- **Inalterada em conceito**: Data, hora, barra de tempo, agenda vertical
- **Adição**: Inbox como badge/mini-seção (quando tem itens não revisados)
- **Mantém**: Atrasadas como alerta, Jira como seção compacta
- Agenda vertical **EXATAMENTE como está hoje** (funciona bem)

---

## 6. Visão Semanal

### Conceito
Timeline vertical por dia (seg-sex), mostrando:
- **Reuniões** como blocos posicionados no horário (proporcional)
- **Deadlines de tarefas** como marcadores no dia, com peso visual proporcional às horas estimadas
- **Vazio = folga** (sem número explícito de "horas livres")

### Benchmarks
| App | Inspiração |
|---|---|
| **Amie** | Colunas de dia com blocos de tempo integrados a tarefas |
| **Sunsama** | Peso do dia baseado em horas estimadas, alerta visual de overload |
| **Akiflow** | Tarefas como blocos de tempo no calendário |
| **Morgen** | Integração tarefa ↔ calendário com duração estimada |
| **Notion Calendar** | Multi-day view limpa com densidade controlada |

### Layout
```
SEG         TER         QUA         QUI         SEX
┃           ┃           ┃           ┃           ┃
┃           ┃ ░░ daily  ┃           ┃ ░░ 1:1    ┃ ░░ review
┃           ┃           ┃ ░░ reunião┃           ┃
┃           ┃           ┃           ┃ ░░ reunião┃
┃           ┃           ┃           ┃           ┃
┃           ┃           ┃   ▼       ┃   ▼       ┃
┃           ┃           ┃ Vídeo     ┃ Fora da   ┃
┃           ┃           ┃ Abertura  ┃ Caixa SM  ┃
┃           ┃           ┃ ▓▓▓(3h)   ┃ ▓▓(2h)    ┃
```

- Reuniões: blocos cinza/azul claro posicionados no horário
- Deadlines: marcador (▼) + nome + bloco proporcional às horas estimadas
- Sem números de "horas livres" — o vazio visual comunica
- Posição na tela: abaixo das tarefas (scroll) — testar se funciona, pode virar aba depois

---

## 7. Contexto Pessoal

### Diferenças visuais
- Layout mais relaxado (mais padding)
- Hábitos + gamificação como elemento principal da sidebar
- Sem Jira, sem agenda de reuniões
- Lista de compras permanece
- Mesmo sistema de status (Fazendo/A Fazer/No Radar/Backlog)

### Sidebar pessoal
```
├── Streak + pontos
├── Hábitos de hoje (cards glow)
├── Compras (mini lista)
└── Vence hoje
```

---

## 8. Decisões de Design

| Decisão | Escolha | Motivo |
|---|---|---|
| Cores de projeto | NÃO são sistema de navegação | Pedro disse que não ajudam a categorizar |
| Hierarquia | Por tamanho + opacidade + espaço | "Bato o olho e tenho um sentimento" |
| Status chips na lista | Discretos, não dominantes | O título e deadline importam mais |
| Deadline | Só aparece se relevante (amber/vermelho se próximo) | Ausência = sem urgência |
| Filtro por projeto | Removido do dashboard foco | Poucas tarefas visíveis, não precisa |
| Dashboard.html | Deletar | Unificar em index.html |
| Inbox | Badge/mini na sidebar | Não compete com foco no main |
| Notas/Refs | Mantém como abas no header | Funciona |

---

## 9. Informações na Row de Tarefa

### A Fazer (row compacta)
```
[prioridade] Título da tarefa · Projeto · deadline
```
- Prioridade: indicador visual (barra lateral colorida ou emoji)
- Título: 14px, weight 500
- Projeto: texto small, muted
- Deadline: badge com cor contextual (vermelho se atrasado, amber se hoje/amanhã, neutro se longe)

### No Radar (row muted)
```
◌ Título · status note em itálico
```
- Opacity 60%
- Borda tracejada
- Status note é mais proeminente que o título
- Sem deadline visível

### Modal da tarefa (ao clicar)
- Título editável
- Projeto (select)
- Status (select)
- Prioridade
- Deadline (date picker + chips rápidos: hoje/amanhã/sexta)
- Horas estimadas
- Status note
- Lembrete (remind_at) — chips de tempo rápido
- Notas/descrição (textarea markdown)
- Checklist (drag-drop, add inline)
- Links (url + label)
- Imagens (drag-drop)
- Subtasks
- Jira link (picker)
- Histórico (created_at, source, raw_input)

---

## 10. Implementação (Ordem)

1. **Mapear status "queued" → "todo" (a fazer) e criar "radar"** — migração de dados
2. **Novo layout do main**: Hero card + A Fazer + No Radar + Backlog colapsado
3. **Sidebar**: mover inbox pra sidebar, manter agenda
4. **Visão semanal**: componente de timeline multi-day abaixo das tarefas
5. **Deletar dashboard.html**
6. **Refinamento visual**: animações, transições, feedback de conclusão
7. **Mobile**: adaptar novo layout pra mobile

---

## 11. Métricas de Sucesso

O redesign funciona se:
- Pedro abre o dashboard e em <3 segundos sabe o que fazer
- Não sente ansiedade ao ver a lista (hierarquia clara)
- Usa o "No Radar" pra coisas que está monitorando (não mistura com "A Fazer")
- A visão semanal dá sensação de controle sobre a carga futura
- Não precisa de view alternativa pra organizar (tudo na mesma tela)
