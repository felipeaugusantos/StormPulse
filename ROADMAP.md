# StormPulse — Roadmap por fases

Desenvolvimento incremental. Cada fase entrega algo verificável e não avança
automaticamente para a próxima.

| Fase | Nome | Entregáveis principais | Status |
|-----:|------|------------------------|:------:|
| **0** | Análise da arquitetura | ARCHITECTURE.md, ADRs, riscos, estrutura, dependências, plano | ✅ Concluída |
| **1** | Fundação do projeto | Estrutura do repo, FastAPI, config, Docker/Compose, Postgres+PostGIS, Redis, health/ready, pytest, lint, typing, .env.example, README | ✅ Concluída |
| **2** | Banco e modelos | 13 modelos SQLAlchemy multitenant, migration bootstrap (PostGIS), GeoAlchemy2 | ✅ Concluída |
| **3** | Autenticação | JWT + refresh (pyjwt), hash Argon2, RBAC (ADMIN/USER), rate limiting Redis | ✅ Concluída |
| **4** | Localizações + PostGIS | CRUD de `Location`, raio, `AlertPreference`, `/storms/nearby` via `ST_DWithin` | ✅ Concluída |
| **5** | Mock Weather Provider | Interface `WeatherProvider` + `MockWeatherProvider` (dados MOCK explícitos) | ✅ Concluída |
| **6** | Storm Engine inicial | Detecção de células + severidade determinística (experimental), geometria WKT | ✅ Concluída |
| **7** | Tracking e trajetória | Associação por vizinho, deslocamento/direção/velocidade/tendência, ETA por velocidade de aproximação | ✅ Concluída |
| **8** | Risk Engine | `StormRiskEngine` por regras documentadas (hazards + score→nível), experimental/mock explícito | ✅ Concluída |
| **9** | Alert Engine | Eventos, níveis GREEN→RED, idempotência (dedup_key) e antispam por política central | ✅ Concluída |
| **10** | Workers | Celery + Beat, pipeline provider→engine→risco→alerta→notificação (persistido) | ✅ Concluída |
| **11** | Dashboard básico | Web admin (React+Vite+MapLibre): mapa, células, alertas, locais, status | ✅ Concluída |
| **12** | Aplicativo mobile | Expo (React Native): login, locais com risco, alertas (mapa MapLibre + FCM: próximo incremento) | ✅ Concluída |
| **13** | Integração meteorológica real | `InmetWeatherProvider` real (estações automáticas); células aproximadas por chuva→dBZ (Marshall–Palmer); avisos por UF; sem CEMADEN/radar real; previsão pendente (ver [ADR-0006](docs/adr/0006-integracao-real-inmet.md)) | ✅ Concluída |
| **14** | Hardening | Headers de segurança, rate limiting geral, OTel (console/OTLP), pip-audit+dependabot+SECURITY.md, testes de integração dos routers (91% cobertura) — ver [ADR-0007](docs/adr/0007-hardening-v1.md) | ✅ Concluída |
| **15** | Login Google + modo visitante + previsão real | `POST /auth/google` (vínculo por `google_sub`), `/api/v1/public/*` (células+avisos sem conta), `GET /locations/{id}/forecast` (5 dias reais do INMET + 1 histórico) — ver [ADR-0008](docs/adr/0008-login-google-visitante-previsao-inmet.md) | ✅ Concluída |
| **16** | Observação via satélite (GOES-19 + TATHU) | `ConvectiveWatch` (detecção de convecção via infravermelho, GDAL+TATHU), integrado ao Alert Engine, `/api/v1/satellite` e `/api/v1/public/satellite/watches`, desligado por padrão (`SATELLITE_ENABLED=false`) — ver [ADR-0009](docs/adr/0009-satelite-goes19-tathu.md) | ✅ Concluída |
| **17** | Redundância INPE/CPTEC | `CptecWeatherProvider` (previsão real via XML público do INPE/CPTEC, sem geocódigo) + `FallbackWeatherProvider` — fallback automático por método quando o INMET falha, ligado por padrão (`CPTEC_FALLBACK_ENABLED=true`) — ver [ADR-0011](docs/adr/0011-inpe-cptec-fallback.md) | ✅ Concluída |
| **18** | Imagem de satélite ao vivo no mapa | `SatelliteImage` (frame IR do GOES-19 renderizado a partir do mesmo grid já reprojetado pra detecção), `/api/v1/public/satellite/image` + `.../image.png`, camada `image` no MapLibre com toggle — ver [ADR-0013](docs/adr/0013-imagem-satelite-ao-vivo.md) | ✅ Concluída |
| **19** | Sinais agronômicos | Alerta de geada e sequência-sem-chuva (`FROST_WARNING`/`DRY_SPELL_WARNING`, ciclo a cada 6h), janela de pulverização (vento) e chuva acumulada via `GET /locations/{id}/agro/{spray-window,rainfall}` — ver [ADR-0014](docs/adr/0014-sinais-agronomicos.md) | ✅ Concluída |
| **20** | Terceira redundância (Open-Meteo) | `OpenMeteoWeatherProvider` — agregador internacional sem chave, único com previsão numérica real de chuva; cadeia INMET → CPTEC → Open-Meteo; janela de pulverização passa a considerar chuva quando disponível — ver [ADR-0015](docs/adr/0015-open-meteo-terceiro-fallback.md) | ✅ Concluída |

## Funcionalidades adicionais (fases 21–27)

Depois da FASE 20, o desenvolvimento continuou em fases menores e mais
rápidas (evolução guiada por feedback direto de uso, não um plano
sequencial fixo como as fases 1–20). Cada uma tem sua própria ADR:

- **Sinais adicionais do Open-Meteo** — CAPE, ETA de chuva, balanço
  hídrico, GDD (graus-dia de crescimento), risco de doença fúngica e VPD
  (déficit de pressão de vapor) — ver [ADR-0021](docs/adr/0021-instabilidade-cape-eta-balanco-hidrico-gdd-doenca-vpd.md).
- **Notificação push real (Web Push/VAPID), CSP e exclusão de conta
  (LGPD)** — RLS (Row-Level Security no Postgres) avaliado e **adiado**
  (isolamento por tenant continua só em nível de aplicação) — ver
  [ADR-0016](docs/adr/0016-push-real-csp-exclusao-conta.md).
- **Comparação com o Agritempo** (Embrapa/INMET) — validação dos sinais
  agronômicos contra uma fonte de referência — ver
  [ADR-0018](docs/adr/0018-comparacao-agritempo.md).
- **Raios/descargas atmosféricas** via API-REDEMET (DECEA/Aeronáutica),
  desligado por padrão (precisa de cadastro) — ver
  [ADR-0019](docs/adr/0019-raios-api-redemet.md).
- **Chuva numérica direto do Open-Meteo** (correção de um bug real no
  card de Trafegabilidade) — ver
  [ADR-0020](docs/adr/0020-chuva-numerica-open-meteo-direto.md).
- **Talhão / sub-local dentro da fazenda** — locais podem ter um
  `parent_location_id` e uma `crop` (cultura) própria — ver
  [ADR-0022](docs/adr/0022-talhao-sub-local-dentro-da-fazenda.md).
- **Paridade do app mobile** — Agro, cadastro de local/talhão, push
  nativa (Expo) — ver
  [ADR-0023](docs/adr/0023-mobile-parity-agro-talhao-push-expo.md).
- **Talhão com contorno real (polígono) no mapa**, colorido por cultura,
  usando a imagem de satélite como referência visual — ver
  [ADR-0024](docs/adr/0024-talhao-contorno-poligono-satelite.md).
- **Ajustes de mapa** — zoom não reseta mais a cada ciclo, legenda pode
  ser escondida, marcar ponto no mapa pra criar local, cor de cultura
  editável — ver [ADR-0025](docs/adr/0025-mapa-fixes-marcar-ponto-cor-manual.md).

## Ciclo de hardening técnico (em andamento)

Revisão técnica focada em segurança/operação, sem mudar regras ou modelos
meteorológicos (ver princípio inviolável no topo do README). Cada fase tem
sua própria ADR; fases não listadas aqui ainda não começaram.

| Fase | Nome | Entregável principal | Status |
|-----:|------|------------------------|:------:|
| **1** | Branches, CI, deploy | Actions atualizadas, job `root` novo no CI, auditoria npm em 2 camadas — [ADR-0026](docs/adr/0026-hardening-fase-1-branches-ci.md) | ✅ Concluída |
| **2** | Dependências do app mobile | Upgrade coordenado Expo SDK 51→57 via `expo install` — [ADR-0027](docs/adr/0027-hardening-fase-2-expo-sdk-57.md) | ✅ Concluída |
| **3** | Renovação de sessão (mobile) | Tokens em `expo-secure-store`, refresh com lock compartilhado — [ADR-0028](docs/adr/0028-hardening-fase-3-renovacao-sessao-mobile.md) | ✅ Concluída |
| **4** | Segurança de sessão (web) | Cookie HttpOnly opcional pro refresh token — **implementação parcial**, bloqueada por decisão de domínio de produção ainda não tomada — [ADR-0029](docs/adr/0029-hardening-fase-4-cookie-refresh-token-opt-in.md) | 🟡 Parcial |
| **5** | Configuração consistente do FastAPI | `Depends(get_settings)` → `Depends(get_request_settings)` em todos os pontos, rate limiter de auth corrigido — [ADR-0030](docs/adr/0030-hardening-fase-5-configuracao-por-instancia.md) | ✅ Concluída |
| **6** | Migrations Alembic reproduzíveis | Baseline com DDL congelado substitui `Base.metadata.create_all()` — [ADR-0031](docs/adr/0031-hardening-fase-6-baseline-alembic-ddl-congelado.md) | ✅ Concluída |
| **7** | Docker reproduzível | TATHU pinado por SHA, imagem base por digest, variantes `runtime-base`/`runtime-satellite` — [ADR-0032](docs/adr/0032-hardening-fase-7-docker-reproducivel.md) | ✅ Concluída |
| **8** | Rate limiting atrás de proxy | Política de proxy confiável, chave por tenant+usuário+IP — [ADR-0033](docs/adr/0033-hardening-fase-8-rate-limit-proxy.md) | ✅ Concluída |
| **9** | Documentação, licença, estrutura frontend | README/ARCHITECTURE/ROADMAP sincronizados, distinção entre os dois frontends, SECURITY.md com canal de reporte privado — [ADR-0034](docs/adr/0034-hardening-fase-9-documentacao-licenca-estrutura.md) | ✅ Concluída |
| **10** | Frontend e observabilidade | Code-splitting já existia (confirmado); 34 testes novos no `web/` (Vitest); métricas operacionais (duração/falha de ciclo, fonte meteorológica, idade do dado, alertas, latência externa) — [ADR-0035](docs/adr/0035-hardening-fase-10-frontend-observabilidade.md) | ✅ Concluída |
| **11** | Validação meteorológica | Infra de avaliação forecast vs. observação real, ADR sobre adequação a alertas de segurança | ⏳ Planejada |

Preparação de infraestrutura de produção (proxy reverso/TLS, backup do
Postgres, política do Redis, rotação de segredos, retenção de logs,
Celery Beat único) ainda **não começou** — depende de decisões de
infraestrutura que o dono do produto ainda não tomou (ver ADR-0029/0031).

## Escopo do MVP (fases 1–10)

O MVP entrega o fluxo ponta-a-ponta com **fonte simulada**:
cadastro → auth → localização + raio → provider mock → células simuladas →
tracking → distância/direção/velocidade/ETA → risco → alerta → API.

## Explicitamente fora do MVP

IA generativa, detecção automática de supercélula, deep learning, previsão
própria do tempo, processamento avançado de radar, integração com dezenas de
APIs, billing/pagamentos e Kubernetes.
