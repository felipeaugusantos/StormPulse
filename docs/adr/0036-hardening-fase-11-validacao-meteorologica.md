# ADR-0036 — Hardening (Fase 11): validação meteorológica e posicionamento do produto

- **Status:** Aceito
- **Data:** 2026-08-22
- **Esta ADR é o "portão de decisão" pedido explicitamente no ciclo de
  hardening**: descreve o processo de validação e conclui, com base nas
  evidências reais disponíveis hoje, se o sistema pode ser classificado
  como apropriado para alertas de segurança.

## Contexto

StormPulse emite alertas (`Alert`) e avaliações de risco (`StormRisk`) a
partir de regras determinísticas sobre dados aproximados (taxa de chuva
via Marshall–Palmer, não radar real — ver
[ADR-0006](docs/adr/0006-integracao-real-inmet.md)) e sinais precoces
(convecção via satélite — ver
[ADR-0009](docs/adr/0009-satelite-goes19-tathu.md)). Nenhuma dessas
classificações jamais foi comparada sistematicamente contra o que
realmente aconteceu depois. Sem essa comparação, não existe base para
afirmar qualquer taxa de acerto, precisão ou recall — e sem isso, não há
base para recomendar o sistema para decisões de segurança real.

## O que esta fase construiu

### Infraestrutura de avaliação (`engine/validation.py`)

Funções puras, sem estado, para calcular métricas a partir de pares
previsão/observação:

- `precision_recall()` / `precision_recall_by_event_type()` — verdadeiro/falso
  positivo/negativo, agregado e por tipo de evento (granizo, raio, etc. não
  compartilham a mesma taxa de acerto, misturar tudo esconde isso).
- `mean_absolute_eta_error_minutes()` — erro médio absoluto do ETA previsto
  vs. chegada real.
- `mean_data_latency_seconds_by_provider()` / `provider_availability()` —
  latência e disponibilidade histórica por fonte, complementando as
  métricas *ao vivo* já emitidas pela Fase 10
  ([ADR-0035](docs/adr/0035-hardening-fase-10-frontend-observabilidade.md)).

12 testes com dados sintéticos (não há dado real ainda) provam que o
cálculo está correto — inclusive casos de borda importantes: precisão/recall
retornam `None` (não `0.0`) quando não há previsões/observações positivas
suficientes para o cálculo fazer sentido, e o erro de ETA usa valor
absoluto (não cancela um erro "cedo" com um "atrasado").

### `AlertVerification` — registro de ground truth (infraestrutura nova, ainda vazia)

Nova tabela (`app/alerts/verification_models.py`,
`e5f7a3c9b1d2_add_alert_verifications.py`): associa um `Alert` já emitido a
um resultado real — `confirmed` (bool, `None` = ainda não resolvido),
`actual_arrival_at` (pra calcular erro de ETA), `verified_by`/`verified_at`,
`notes`, `confidence`.

**Decisão deliberada: nenhum endpoint público para escrever nesta
tabela.** Registrar verdade de campo hoje significa alguém (desenvolvedor,
operador) escrever a linha diretamente — não existe fonte de observação
externa verificada (radar real) nem um fluxo de report comunitário
funcionando (`UserReport` já existe como modelo desde a FASE 2, mas nunca
ganhou router/UI — arquitetura preparada, nunca implementada). Adicionar um
endpoint público "confirme este alerta" é superfície de produto real —
teria que decidir autenticação, abuso, moderação de conteúdo enviado por
usuários — fora do escopo de um ciclo de hardening, e explicitamente
vetado pela instrução original de não implementar funcionalidades novas de
meteorologia. Fica para uma fase de produto futura, considerada
separadamente.

### Propagação de proveniência — auditoria, sem lacunas novas

Verificado (não modificado, já estava correto): `is_mock`/`experimental` já
aparecem consistentemente nos schemas de `StormCell`/`StormRisk` e nos
componentes de UI (`Dashboard.tsx`, `VisitorView.tsx`,
`LocationWeatherCard.tsx`) — tag "MOCK" visível quando aplicável. Fonte
(`Provenance.source_name`/`source_kind`) e timestamp (`observed_at`) já
existem em todo payload meteorológico. Idade do dado agora também vira
métrica ao vivo (`stormpulse.weather.data_age`, Fase 10).

### Aviso de segurança — agora na UI de verdade, não só no README

O README já tinha uma seção de limitações (Fase 9, ADR-0034) — mas
**nenhuma tela do produto de fato mostrava esse aviso**. Corrigido:

- `web/src/components/SafetyDisclaimer.tsx` — novo componente compartilhado,
  usado no `Dashboard.tsx` (usuário autenticado) e `VisitorView.tsx` (modo
  visitante): "⚠️ StormPulse não substitui alertas oficiais (INMET, Defesa
  Civil, CEMADEN). Em qualquer situação de risco real, siga os canais
  oficiais."
- `mobile/src/screens/HomeScreen.tsx` — mesmo texto, no rodapé da tela
  inicial.

Verificado visualmente no navegador (Vite dev server, modo visitante) que
o aviso renderiza corretamente mesmo sem backend disponível — é texto
estático, não depende de nenhuma chamada de API.

## O processo de validação (como isto *deveria* funcionar, uma vez que haja dado real)

1. Cada `Alert` emitido já é uma "previsão" registrada (tabela `alerts`,
   existente desde a FASE 9).
2. Alguém com acesso ao banco grava uma linha em `alert_verifications`
   quando souber o que realmente aconteceu (confirmação por canal oficial,
   observação direta, ausência confirmada do evento).
3. `engine/validation.precision_recall_by_event_type()` sobre o conjunto
   de pares `(Alert.event_type, alert foi emitido, verification.confirmed)`
   dá precisão/recall reais, por tipo de evento.
4. Para alertas de aproximação de tempestade (com ETA), `EtaSample`
   (`Alert` + `AlertVerification.actual_arrival_at`) alimenta
   `mean_absolute_eta_error_minutes()`.
5. Repetir isso por volume suficiente de amostras (não definido nesta ADR —
   depende de quanto tráfego real o sistema tiver) antes de qualquer
   número ser estatisticamente significativo.

## Conclusão — classificação do sistema

**StormPulse não está, e não pode estar, classificado como apropriado
para alertas de segurança crítica hoje.** Não por falta de intenção, mas
por ausência de evidência: zero pares previsão/observação foram
registrados até agora (a infraestrutura para registrá-los é nova, desta
mesma ADR). Sem volume de dados real, nenhuma taxa de precisão/recall
declarada teria significado estatístico — apresentar um número agora seria
pior do que não apresentar nenhum.

Isso não é uma mudança de rumo: é a formalização explícita do que o
princípio inviolável do projeto já dizia desde o início ("classificação
determinística, nunca por LLM" — [ADR-0005](docs/adr/0005-risk-engine-baseado-em-regras.md))
e do que o README já anunciava informalmente. O que muda com esta ADR é
que agora existe (a) uma forma concreta de medir, quando houver dado, e
(b) o aviso correspondente **na tela do usuário**, não só num documento
que a maioria nunca lê.

**Posicionamento correto do produto, até que essa validação exista com
volume real**: uma camada de conveniência que agrega e simplifica sinais
meteorológicos já públicos, não um sistema de alerta oficial e não um
substituto para os canais que têm mandato legal e infraestrutura de
verificação para isso (INMET, Defesa Civil, CEMADEN).

## Consequências

- Nenhuma mudança de modelo, regra ou threshold meteorológico.
- Nenhuma funcionalidade nova de produto voltada ao usuário final além do
  aviso de segurança (que é uma correção de lacuna de compliance, não uma
  feature).
- `AlertVerification` fica como infraestrutura pronta, mas vazia —
  próximo passo real (fora de escopo aqui) seria decidir *como* popular
  essa tabela em escala (relatório manual do operador? canal oficial via
  API? crowdsourcing com moderação, finalmente ligando `UserReport`?) —
  decisão de produto, não de hardening.
- Backend revalidado: `ruff check`, `ruff format --check`, `mypy`
  (strict), migração testada (upgrade/downgrade, `alembic check` sem
  divergência além do ruído conhecido do PostGIS tiger geocoder), suíte
  completa com Postgres+Redis reais — 100% verde, 89.19% de cobertura,
  `engine/validation.py` 100% coberto. Frontend: `web/` typecheck +
  vitest verdes, verificado visualmente no navegador; `mobile/` typecheck
  + jest verdes.
