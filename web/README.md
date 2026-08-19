# Web — Dashboard administrativo (FASE 11)

Dashboard admin do StormPulse: **React + TypeScript + Vite + MapLibre**
(ver [ADR-0004](../docs/adr/0004-maplibre-para-mapas.md)).

Consome a API (FASES 1–10) e mostra:

- **Mapa** (MapLibre) com células de tempestade coloridas por severidade e os
  locais monitorados;
- **Alertas** recentes (nível GREEN→RED, tipo de evento);
- **Células detectadas** (severidade, refletividade, horário) — marcadas `MOCK`
  quando simuladas;
- **Locais monitorados** (raio, tipos de alerta habilitados);
- **Status** de Postgres/Redis (via `/ready`) e usuário autenticado;
- **Atualização automática** a cada 30s.

> A aparência é deliberadamente enxuta (a arquitetura tem prioridade nesta fase).
> Dados simulados são sempre rotulados `MOCK` — nunca apresentados como reais.

## Rodando

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # build de produção em dist/
```

Aponte para a API com a variável de ambiente `VITE_API_URL`
(padrão `http://localhost:8000`):

```bash
VITE_API_URL=http://localhost:8000 npm run dev
```

Faça login com um usuário criado via `POST /api/v1/auth/register`.

## Estrutura

```
src/
├── api.ts                # cliente da API + token (localStorage)
├── types.ts              # tipos das respostas
├── App.tsx               # gate de autenticação
└── components/
    ├── Login.tsx
    ├── Dashboard.tsx     # topbar + painéis + auto-refresh
    └── StormMap.tsx      # mapa MapLibre (células + locais)
```
