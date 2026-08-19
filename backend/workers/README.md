# Workers 🔭

Workers assíncronos (Celery + Celery Beat — ver ADR-0002). Placeholder de
FASE 0/1 — implementado na FASE 10.

Responsabilidades planejadas:

- Ingestão agendada de dados meteorológicos (Beat, a cada N minutos).
- Execução do pipeline do Storm Engine fora do request da API.
- Materialização de resultados (células, tracks, riscos, alertas) em
  PostgreSQL/Redis para a API consumir.

Tarefas devem ser **idempotentes** (requisito do motor de alertas antispam).
