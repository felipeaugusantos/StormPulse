# ADR-0058 — Caminho mínimo de backtesting: endpoint de verificação + métricas reais

- **Status:** Aceito
- **Data:** 2026-08-27

## Contexto

A ADR-0036 já tinha construído a metade "matemática" da validação
meteorológica (`engine/validation.py`, testado com dados sintéticos) e o
schema de ground-truth (`AlertVerification`, `alert_verifications`), mas
deliberadamente sem nenhum caminho de escrita — nenhum endpoint jamais
gravava uma linha ali, então a tabela existia e sempre esteve vazia.
Confirmado por auditoria de código antes de escrever qualquer linha:
`grep` por `AlertVerification` no repositório só encontrava o próprio
model, a migration, e comentários em `engine/validation.py`.

## Decisão

Dois novos endpoints, ambos atrás de `require_platform_admin` (mesmo guard
cross-tenant do resto do painel admin, FASE 28/ADR-0048) — continuando a
decisão original da ADR-0036 de não expor isso publicamente:

- `PUT /admin/alerts/{alert_id}/verification` — grava (ou atualiza,
  upsert por `alert_id`) se um `Alert` já emitido se confirmou de verdade,
  quando (`actual_arrival_at`), e uma nota livre de contexto/fonte. 404 se
  o alerta não existir.
- `GET /admin/validation/metrics` — agrega todas as verificações já
  *resolvidas* (`confirmed is not None`) e calcula, via
  `engine/validation.py` (reutilizado, não reimplementado): taxa de
  confirmação geral e por `event_type`, erro médio absoluto de ETA (em
  minutos, só para os alertas que tinham uma `StormRisk.eta_minutes`
  associada e cujo `actual_arrival_at` foi registrado), e um flag
  `reliable` (amostra ≥ 30 — limiar que a ADR-0036 sinalizou como
  necessário mas deixou indefinido).

### Por que não existe `recall` na resposta

Toda linha de `AlertVerification` vem de um `Alert` que **já foi emitido**
— não existe, ainda, nenhuma fonte de falso-negativo real (um evento que
de fato aconteceu e que o sistema nunca alertou). Calcular "recall" só com
alertas emitidos sempre dá 1.0, não importa quantas tempestades reais
tenham passado batido — um número que pareceria medido mas seria
fabricado. `ValidationMetricsOut` documenta isso explicitamente e só
expõe a taxa de confirmação (equivalente à `precision` de
`engine.validation.precision_recall`, que continua correta porque não
depende de contar falso-negativos).

## Verificação

`backend/tests/test_admin_validation.py`, 5 testes, contra Postgres real
(nunca mockado): 403 para não-admin; upsert real (cria, depois atualiza a
mesma linha, nunca duplica); 404 pra alerta inexistente; métricas
calculadas a partir de linhas reais commitadas (taxa de confirmação,
contagem por tipo de evento, erro de ETA, e que uma verificação não
resolvida — `confirmed=None` — não entra em nenhuma conta); confirma que
`recall` nunca aparece na resposta; confirma que o flag `reliable` muda de
`False` pra `True` exatamente ao cruzar as 30 amostras.

Como `/admin/validation/metrics` agrega globalmente (não por tenant), os
testes que fazem asserção exata limpam `alert_verifications` no início
(mesmo problema e mesma solução já usados em
`test_pipeline_health_reflects_fresh_and_stale_data`, ADR relacionada:
FASE 34) — sem isso, rodar a suíte inteira antes deixaria linhas de outros
testes contaminando a contagem.

Suíte completa: `ruff check`, `ruff format --check`, `mypy app engine
workers tests` e `pytest --cov=app --cov=workers --cov=engine
--cov-fail-under=85` rodados localmente contra Postgres/Redis reais antes
do push — 91.23% de cobertura, sem regressão nos testes existentes.

## Consequências

- `alert_verifications` agora tem um caminho de escrita real, mas
  continua exigindo um operador humano registrar cada linha manualmente
  (via bulletin oficial, checagem própria, etc.) — nenhuma fonte
  automática/crowdsourced foi conectada nesta ADR, deliberadamente (seria
  superfície de produto nova, fora de escopo aqui, mesma razão já dada na
  ADR-0036).
- `GET /admin/validation/metrics` só fica útil (`reliable=true`) depois de
  30 verificações resolvidas — antes disso, o número existe mas o próprio
  flag avisa que não é confiável.
- Recall meteorológico de verdade (quantos eventos reais o sistema
  perdeu) continua impossível de medir sem uma fonte independente de
  observação — não resolvido aqui, documentado como limite conhecido.
