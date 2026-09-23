# ADR-0096 — Rastreamento de erros (Sentry) nos 3 lugares

- **Status:** Aceito
- **Data:** 2026-09-22

## Contexto

Auditoria geral do projeto (pedida diretamente) achou a maior lacuna
real: nenhum dos incidentes descobertos no mesmo dia (nginx servindo um
IP morto depois de um restart, healthcheck de `worker`/`beat` sempre
falso, MinIO removido do Docker Hub) foi descoberto por alerta
automático — só investigando manualmente, log por log. O único APM
existente é o OpenTelemetry tracing local (ADR-0007), sem exportador pra
nenhum backend externo — segue a *rota* de uma requisição, mas não avisa
ninguém quando algo quebra.

Perguntado qual ferramenta usar: Sentry, pela cobertura de SDK oficial
pros 3 lugares do projeto (FastAPI, React, React Native/Expo) com uma
conta só.

## Decisão

**Módulo próprio (`error_tracking.py`/`errorTracking.ts`, um por
plataforma), não configuração direta espalhada.** Mesmo padrão já usado
pra tracing (`configure_tracing`) — uma função, um ponto de entrada,
fácil de encontrar e de desligar.

**Desligado por padrão, sem DSN configurado — mesmo espírito de
`ses_from_email`/`smtp_host`/`otel_exporter_otlp_endpoint`.** Nenhuma
chamada de rede, nenhum comportamento diferente, até alguém colar um DSN
de verdade. Isso significa que a criação da conta/projetos Sentry (3,
um por plataforma, ou 1 com ambientes separados) fica com você — não é
algo que dá pra automatizar sem uma conta e credenciais que só você tem.

**DSN não é tratado como "segredo de controle de acesso" nos clientes
(web/mobile), só nomeado como um por convenção.** Um DSN do Sentry só
permite *enviar* eventos pra aquele projeto — os próprios SDKs de
cliente da Sentry o expõem publicamente no bundle, por design (mesma
categoria do VAPID public key, ADR-0016, ou da site key do hCaptcha). No
backend, ainda assim guardado como `SecretStr`, por consistência com o
resto de `Settings`, não porque vazar cause dano real.

**`traces_sample_rate=0` nos 3 lugares — captura de erro, não uma
segunda pipeline de tracing.** OpenTelemetry já é a ferramenta de
tracing/performance deste projeto (ADR-0007); rodar o tracing próprio do
Sentry em paralelo seria custo duplicado sem sinal novo. Escopo
deliberadamente mínimo: só "uma exceção não tratada aconteceu, avise
alguém agora".

**Backend: o mesmo módulo inicializa tanto a `api` quanto
`worker`/`beat`.** `configure_error_tracking(settings)` chamado em
`app.main.create_app()` (captura exceções de requisição, via a
integração `fastapi` do SDK) e em `workers/celery_app.py` no nível do
módulo (captura falha de tarefa, via a integração `celery` — auto-
habilitada porque `celery` está importável nesse processo). Mesmo
processo de dois lugares diferentes, sem duplicar lógica.

## Verificação

Backend: 2 testes novos (`test_error_tracking.py`) — no-op sem DSN,
inicializa com os parâmetros certos quando configurado (`sentry_sdk.init`
mockado, nenhuma chamada de rede real). `ruff`/`mypy`/suíte completa
(92%+ de cobertura, gate ok). Web: 2 testes novos
(`errorTracking.test.ts`), `tsc --noEmit` limpo, `npm run build` limpo,
`npm audit --omit=dev` = 0. Mobile: 2 testes novos
(`errorTracking.test.ts`), `tsc --noEmit` limpo, `npm audit --omit=dev
--audit-level=high` limpo (mesma cadeia pré-existente de
`@expo/config-plugins`, sem novidade).

## Consequências

- Nenhuma migração, nenhum endpoint novo.
- Dependência nova: `sentry-sdk[fastapi,celery]` (backend), `@sentry/react`
  (web), `@sentry/react-native` (mobile — instalado via `expo install`,
  que também adicionou o config plugin nativo em `app.json`
  automaticamente).
- **Passo manual pendente, só seu**: criar o(s) projeto(s) no
  [sentry.io](https://sentry.io) (plano free cobre isso tranquilamente
  no volume atual do projeto) e configurar `SENTRY_DSN` no `.env` do
  servidor (backend), `VITE_SENTRY_DSN` como variável de repositório do
  GitHub Actions (`vars.VITE_SENTRY_DSN`, web) e `EXPO_PUBLIC_SENTRY_DSN`
  em `mobile/eas.json`/ambiente local (mobile) — sem isso, nada muda,
  exatamente como hoje.
- Não cobre "a API caiu" (indisponibilidade total) — isso é o que o
  UptimeRobot já observado nos logs (`Mozilla/5.0+(compatible;
  UptimeRobot/2.0;...)`) parece fazer de fora; vale confirmar se os
  contatos de alerta dele estão configurados de verdade, separado desta
  ADR.
