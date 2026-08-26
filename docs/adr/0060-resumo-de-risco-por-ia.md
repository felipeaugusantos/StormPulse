# ADR-0060 — Resumo de risco em linguagem natural via Claude

- **Status:** Aceito
- **Data:** 2026-08-27

## Contexto

Levantamento competitivo (ver artifact "Radar Competitivo") apontou que
concorrentes de peso (Tomorrow.io com o "Gale", Solinftec com a "Alice")
já oferecem um resumo/assistente por IA sobre os dados que calculam. O
`StormRiskEngine` já calcula tudo que seria necessário — severidade,
score por perigo (chuva/vento/granizo/raio), distância, velocidade, ETA —
só nunca traduz isso pra uma frase legível.

## Decisão

### Nunca uma segunda fonte de risco

`workers/ai_summary.py::generate_summary` monta o prompt **só** com os
números que a própria linha de `StormRisk` já tem — nunca deixa o modelo
inventar distância, velocidade ou horário que não estejam explicitamente
na mensagem. O papel do Claude aqui é só frasear um número já calculado,
nunca prever nada novo — evita confundir isto com um "modelo de
nowcasting", que é um problema completamente diferente (e muito mais
caro, ver o próprio Radar Competitivo).

### Modelo: Haiku, fixo

`claude-haiku-4-5`, não configurável. É um resumo curto e determinístico
de dados já calculados — não uma tarefa que justifique um modelo maior.
Custo estimado (ver conversa que motivou esta ADR): ~US$0,0015 por
resumo gerado.

### Pré-computado, nunca sob demanda

Gerado de forma assíncrona (Celery, fire-and-forget) logo depois que
`run_ingestion_cycle` cria um `StormRisk`, nunca quando o frontend abre o
dashboard — o dashboard só lê `StormRisk.ai_summary`, já pronto.
Só dispara para severidade amarela/laranja/vermelha (verde não tem o que
explicar, e evita uma chamada de API por ciclo por local monitorado sem
necessidade).

### Uma condição de corrida real, pega antes de subir

A primeira versão despachava a task Celery **de dentro** de
`run_ingestion_cycle`, logo após `session.add(StormRisk(...))` +
`session.flush()`. `flush()` só torna a linha visível *dentro da mesma
transação* — a transação inteira só commita quando `session_scope()`
(no chamador, `run_ingestion_cycle_task`) sai do `with`, bem depois de
todos os locais do ciclo serem processados. Despachar ali significava que
a task de resumo (rodando numa conexão de banco separada) podia tentar
buscar a linha antes dela existir de verdade pro resto do sistema.

Corrigido: `run_ingestion_cycle` só **coleta** os IDs elegíveis em
`CycleSummary.risk_ids_for_ai_summary`; o disparo de verdade
(`generate_risk_ai_summary_task.delay(...)`) acontece em
`run_ingestion_cycle_task`, depois que o bloco `with session_scope()`
já fechou (commit garantido). Coberto por
`test_run_ingestion_cycle_task_dispatches_ai_summaries_after_commit`.

### Opcional, nunca bloqueia, nunca finge

Sem `ANTHROPIC_API_KEY`, `generate_summary` retorna `None` imediatamente
— mesmo padrão de VAPID/SES/hCaptcha. Uma falha da API (rede, rate limit,
erro do lado do Claude) também vira `None`, logada, nunca propaga — o
ciclo de ingestão inteiro não pode quebrar por causa de um resumo de
texto que não é essencial.

## Verificação

`tests/test_ai_summary.py` (5 testes: não configurado, sucesso via
`httpx2.MockTransport`-equivalente com `anthropic.Anthropic` mockado,
erro de API, resposta sem bloco de texto) e
`tests/test_tasks.py` (3 testes novos: task salva o resumo, lida com
risco não encontrado, lida com geração falha/não configurada; mais o
teste específico da condição de corrida acima) — nenhuma chamada real à
API da Anthropic em nenhum teste. Migração `c3a7f9e1b5d8` adiciona
`storm_risks.ai_summary`, guardada com checagem de existência (mesmo
padrão das outras).

## Consequências

- Um resumo de texto a mais no card de risco do dashboard — puramente
  aditivo, não muda nenhum contrato de API existente
  (`StormRiskOut.ai_summary` é opcional, `None` por padrão).
- Custo real só existe quando `ANTHROPIC_API_KEY` é configurada — decisão
  e conta são do responsável pelo projeto, documentado como pendência
  manual (mesma categoria de SES/hCaptcha).
