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