# ADR-0064 — Boletins oficiais como fonte extra de alerta (item 3 do Radar Competitivo)

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

Terceiro item da sequência priorizada: "Consumir boletins da Defesa Civil
como fonte extra". Antes de implementar, investigado se existe uma API
pública, documentada e de verdade para boletins/alertas da Defesa Civil —
nacional ou estadual — dado que o projeto proíbe dado simulado/fabricado
em produção.

### O que existe de verdade

- **CEMADEN** tem uma API pública real e documentada (Swagger em
  `sws.cemaden.gov.br`, "Plataforma de Entrega de Dados") — mas ela expõe
  **só telemetria bruta de pluviômetros/estações** (cadastro de cidades,
  dados de PCDs, acumulados). Não existe nenhum endpoint de alerta/risco
  nessa API. Exige token de cadastro gratuito.
- **Sistemas estaduais/municipais** (Alerta Rio, SP Sempre Alerta, Defesa
  Civil MG/PR/ES) publicam boletins de verdade, mas como painéis HTML sem
  API documentada — o Alerta Rio, por exemplo, está atrás de um desafio
  anti-bot (Cloudflare), inviável de consumir de forma estável e legítima.
- **INMET `/avisos/ativos`** — feed nacional, público, sem cadastro, em
  JSON — é a fonte que a própria Defesa Civil (em qualquer estado)
  efetivamente usa e redistribui na prática. **Já integrado neste projeto**
  desde antes (`WeatherProvider.get_warnings`, usado hoje só no endpoint
  público de visitante `/public/warnings`).

## Decisão

Em vez de fabricar uma integração com uma fonte que não expõe alertas de
verdade (CEMADEN) ou depender de scraping frágil de um painel protegido
(Alerta Rio), a "fonte extra" é o feed que já está integrado e é
genuinamente o mais próximo do que a Defesa Civil usa — ampliado de
"só visível pra quem visita sem login" para **um gerador de alerta de
verdade por local monitorado**:

### Novo pipeline: `workers/official_warnings_pipeline.py`

Mesma estrutura de `workers/agro_pipeline.py` (lógica de decisão própria,
não `AlertEngine` — um `Warning` não tem os scores de risco chuva/vento/
granizo/raio que aquele engine espera). Para cada `Location` ativa:
chama `provider.get_warnings(lat, lon)` e cria um `Alert` real
(`AlertEventType.OFFICIAL_WARNING`) para cada aviso ainda não alertado —
dedup por hash de `(kind, severity, description, issued_at)`, já que o
INMET não expõe um ID estável de aviso.

Severidade do INMET (texto livre: "perigo potencial"/"perigo"/"grande
perigo") mapeada para a escala `RiskLevel` já usada em todo o resto do
sistema. Roda a cada hora (`official-warnings-every-hour`, beat) — um
aviso oficial muda na escala de horas, não minutos, mesma lógica de
"menos frequente é mais honesto e mais gentil com a API" já aplicada ao
agro.

### Zero mudança de frontend

O alerta gerado aparece automaticamente no painel "Alertas" existente do
Dashboard (`AlertsPanel`) — ele já renderiza `title`/`message`/`level` de
forma genérica, sem branch por `event_type`. Não foi necessário adicionar
nenhuma tela nova: o objetivo de "boletim mais visível pra quem já está
logado" é cumprido pela própria geração do alerta, não por uma cópia do
painel "Avisos oficiais" que o modo visitante já tinha.

Nova migração `e7f1a3c5b9d2` adiciona `OFFICIAL_WARNING` ao enum nativo
Postgres `alert_event_type` (mesmo padrão de `c9e2f6a1d4b8`, que fez o
mesmo para `FROST_WARNING`/`DRY_SPELL_WARNING`). Nova flag
`OFFICIAL_WARNINGS_ENABLED` (default `true`), mesmo padrão de
`AGRO_ENABLED`.

## Verificação

`tests/test_official_warnings_pipeline.py` (5 testes, Postgres real):
alerta criado para aviso ativo, mapeamento de severidade
perigo→laranja/grande perigo→vermelho, nenhum alerta sem aviso,
idempotência (mesmo aviso não duplica), desligado via flag retorna
imediato. Verificado manualmente também: inserido um `Alert` de teste com
`event_type=official_warning` direto no banco e confirmado no browser que
aparece corretamente no painel "Alertas" do dashboard autenticado (badge
"ALTO", título, mensagem, timestamp) — exatamente como qualquer outro
alerta, sem código de exibição novo.

## Consequências

- Puramente aditivo — nenhum endpoint/contrato existente muda;
  `/public/warnings` (modo visitante) continua exatamente como era.
- Nenhuma dependência nova, nenhum token/cadastro externo necessário — só
  reusa o `WeatherProvider.get_warnings` já em produção.
- Cobertura geográfica é a mesma do INMET hoje: nacional, mas por UF
  (estado) da estação mais próxima, não por polígono preciso — mesma
  limitação já documentada em `app/weather/inmet.py`.
- Se no futuro surgir uma API de Defesa Civil de verdade (com endpoint de
  alerta, não só telemetria), o `WeatherProvider.get_warnings` já é o
  ponto de extensão certo — um novo provider implementando a mesma
  interface, sem tocar neste pipeline.
