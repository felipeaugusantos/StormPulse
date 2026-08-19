# ADR-0002 — Celery como orquestrador de workers

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 0 (implementação na FASE 10)

## Contexto

O pipeline meteorológico precisa rodar fora do request e, sobretudo, em
**intervalos agendados** (puxar frames de radar a cada N minutos, reavaliar
riscos, expirar alertas). Precisamos de uma fila de tarefas com broker Redis
(já presente na stack) e agendamento periódico.

## Opções consideradas

1. **Celery** (+ Celery Beat para agendamento).
2. **Dramatiq** (+ periodiq/APScheduler para agendamento).
3. **RQ** (Redis Queue).

## Decisão

Adotar **Celery** com **Celery Beat**, broker e backend em **Redis**.

## Justificativa

- **A necessidade dominante é agendamento periódico confiável.** Celery Beat é
  uma solução madura e nativa exatamente para isso (ingestão a cada N minutos),
  enquanto Dramatiq exige um componente externo (periodiq/APScheduler) e RQ não
  tem agendador de primeira classe.
- **Ecossistema e maturidade:** Celery tem a maior base de documentação,
  integrações (Flower para monitorar workers, retries, rate limits por tarefa,
  roteamento por fila) e experiência operacional acumulada.
- **Broker Redis** já faz parte da stack (cache), evitando adicionar RabbitMQ.

### Desvantagens aceitas

- Celery é mais "pesado"/configurável que Dramatiq e sua API é mais verbosa.
  Aceitável dado o ganho em agendamento e ecossistema.
- Beat como ponto único de agendamento exige cuidado em alta disponibilidade
  (mitigável depois com `RedBeat` ou lock distribuído).

### Por que não Dramatiq

Dramatiq é mais simples e ergonômico, mas o agendamento periódico — que é
central aqui — não é nativo. Trocaríamos a verbosidade do Celery por uma
dependência extra de scheduler menos madura.

## Consequências

- Workers rodam em processo separado, compartilhando o código-base.
- Tarefas devem ser **idempotentes** (reforça a exigência do motor de alertas).
- Reavaliar caso o volume/latência exija um modelo de streaming (ex.: Faust)
  no futuro.
