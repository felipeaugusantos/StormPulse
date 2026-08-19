# Web — Dashboard administrativo (FASE 11)

Dashboard admin do StormPulse: **React + TypeScript + Vite + MapLibre**
(ver [ADR-0004](../docs/adr/0004-maplibre-para-mapas.md)).

Consome a API (FASES 1–10) e mostra:

- **Mapa** (MapLibre) com células de tempestade coloridas por severidade e os
  locais monitorados;
- **Alertas** recentes (nível GREEN→RED, tipo de evento);
- **Células detectadas** (severidade, refletividade, horário) — marcadas `MOCK`
  quando simuladas;
- **Locais monitorados** (raio, tipos de alerta habilitados) — clique num
  local para ver a previsão (FASE 15);
- **Status** de Postgres/Redis (via `/ready`) e usuário autenticado;
- **Atualização automática** a cada 30s;
- **Login com Google** (opcional, via `VITE_GOOGLE_CLIENT_ID`) e **modo
  visitante** ("Ver sem login" — células + avisos sem conta, FASE 15).

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

Faça login com um usuário criado via `POST /api/v1/auth/register`, com
Google (se `VITE_GOOGLE_CLIENT_ID` estiver setado) ou clique em
"Ver sem login" para o modo visitante.

## Estrutura

```
src/
├── api.ts                # cliente da API + token (localStorage)
├── types.ts              # tipos das respostas
├── App.tsx               # login | visitante | autenticado
└── components/
    ├── Login.tsx         # e-mail/senha + Google + link de visitante
    ├── Dashboard.tsx     # topbar + painéis + auto-refresh
    ├── VisitorView.tsx   # modo visitante (sem login) — FASE 15
    └── StormMap.tsx      # mapa MapLibre (células + locais)
```
