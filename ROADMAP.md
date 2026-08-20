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

## Escopo do MVP (fases 1–10)

O MVP entrega o fluxo ponta-a-ponta com **fonte simulada**:
cadastro → auth → localização + raio → provider mock → células simuladas →
tracking → distância/direção/velocidade/ETA → risco → alerta → API.

## Explicitamente fora do MVP

IA generativa, detecção automática de supercélula, deep learning, previsão
própria do tempo, processamento avançado de radar, integração com dezenas de
APIs, billing/pagamentos e Kubernetes.
