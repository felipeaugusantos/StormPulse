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
| **12** | Aplicativo mobile | Expo (React Native): locais, alertas, mapa MapLibre | ⬜ Pendente |
| **13** | Integração meteorológica real | INMET / INPE-CPTEC / CEMADEN / radares regionais | ⬜ Pendente |
| **14** | Hardening | Testes ampliados, observabilidade (OTel), rate limiting, segurança | ⬜ Pendente |

## Escopo do MVP (fases 1–10)

O MVP entrega o fluxo ponta-a-ponta com **fonte simulada**:
cadastro → auth → localização + raio → provider mock → células simuladas →
tracking → distância/direção/velocidade/ETA → risco → alerta → API.

## Explicitamente fora do MVP

IA generativa, detecção automática de supercélula, deep learning, previsão
própria do tempo, processamento avançado de radar, integração com dezenas de
APIs, billing/pagamentos e Kubernetes.
