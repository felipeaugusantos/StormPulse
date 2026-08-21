# ADR-0030 — Hardening (Fase 5): configuração consistente do FastAPI (por instância, não global)

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** Ciclo de hardening técnico — `get_request_settings()` já existia (ADR-0007/0008), mas vários pontos ainda usavam `Depends(get_settings)`, o singleton `lru_cache` de processo

## Contexto

`app/api/deps.py` já documentava o problema desde a ADR-0007/0008:
`get_settings()` é `@lru_cache` — a primeira chamada no processo
"congela" a config pra sempre, ignorando qual `Settings` foi realmente
passado pra `create_app()` naquela instância. `get_request_settings()`
(lê `request.app.state.settings`) existe exatamente pra isso, mas nem
todo mundo usava. Levantamento (`grep -rn "Depends(get_settings)" app/`)
encontrou 8 ocorrências reais fora de `login`/`refresh`/`login_google`
(já corrigidos na Fase 4, ADR-0029, porque a própria feature de cookie
não funcionava sem isso):

- `app/api/deps.py::get_current_user` — validação de todo usuário
  autenticado.
- `app/locations/router.py` (5 endpoints) — `forecast`, `current`,
  `spray-window`, `rain-forecast`, `rainfall`: todos usam
  `get_weather_provider(settings)`/`get_numeric_rain_forecast_provider(settings)`.
- `app/public/router.py` (1 endpoint) — `warnings` (avisos oficiais por
  ponto, modo visitante).
- `app/api/health.py` — `GET /health` e `GET /ready` chamavam
  `get_settings()` **diretamente** (nem `Depends`) em vez de ler
  `request.app.state.settings` — `ready()` já recebia `request` como
  parâmetro (usado pra achar `engine`/`redis`), só não usava pra config.

## Decisão

Todos os 8 pontos migrados de `Depends(get_settings)` para
`Depends(get_request_settings)`. Mudança mecânica, sem lógica nova —
`get_request_settings` já existia, só não era usado universalmente.
Imports de `get_settings` removidos onde ficaram órfãos
(`app/api/deps.py`, `app/locations/router.py`, `app/public/router.py`)
— `ruff` confirma zero import morto.

### Rate limiter de auth: de singleton de import-time para dependency por-request

`app/auth/router.py` construía `_auth_rate_limit = RateLimiter(...)`
**em import-time**, lendo `get_settings()` — o processo de import do
módulo acontece uma vez só, antes de qualquer `create_app()` real ser
chamado, então o limite de auth ficava congelado com a config que
existia nesse momento (tipicamente a config default), nunca a de uma
instância de app específica. Nenhum outro rate limiter do projeto tinha
esse problema — `default_rate_limit`/`public_rate_limit`
(`app/main.py`) já são construídos **dentro** de `create_app(settings)`,
corretamente por instância; só o de auth ficava fora desse padrão
porque é aplicado via decorator individual em cada rota dentro do
próprio módulo do router (que é definido em import-time), não via
`include_router(..., dependencies=[...])` como os outros dois.

Corrigido convertendo `_auth_rate_limit` de uma **instância** pré-construída
para uma **função de dependency** que constrói o `RateLimiter` sob
demanda a cada request, lendo `get_request_settings(request)`:

```python
async def _auth_rate_limit(request: Request) -> None:
    settings = get_request_settings(request)
    limiter = RateLimiter(
        max_requests=settings.auth_rate_limit_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
        scope="auth",
    )
    await limiter(request)
```

Reconstruir o objeto a cada chamada é barato — `RateLimiter` não guarda
nenhum estado próprio, é um wrapper fino sobre uma chave do Redis.

### Teste novo: duas instâncias de app, sem vazamento de config

`tests/test_integration_multi_app_settings.py` — três testes,
exatamente o cenário que os bugs acima erravam:

1. Um token emitido por uma instância (`JWT_SECRET_KEY` A) é **rejeitado**
   por outra instância (`JWT_SECRET_KEY` B) no mesmo processo.
2. Cada instância valida corretamente os próprios tokens.
3. Um `AUTH_RATE_LIMIT_MAX` baixo numa instância não vaza para uma
   instância-irmã com limite alto — usa um Redis fake **por instância**
   (não o real compartilhado) especificamente para isolar "qual limite
   é aplicado" de uma questão diferente e legítima (chave do rate
   limiter hoje é só IP+scope, sem nada que distinga instâncias de app —
   correto em produção real com múltiplos workers atrás do mesmo Redis,
   mas confunde um teste que precisa isolar as duas coisas).

## Consequências

- Nenhuma mudança de comportamento observável em produção com uma única
  configuração (o caso de uso normal, hoje) — o efeito só aparece em
  cenários com mais de uma `Settings` no mesmo processo (a suíte de
  testes deste projeto inteira, que já roda assim há tempos; e
  potencialmente múltiplos workers/instâncias no futuro).
- Backend inteiro revalidado depois da migração: `ruff check`,
  `ruff format --check`, `mypy` (strict), suíte completa —
  100% verde, 89.50% cobertura.
- Fora de escopo desta ADR (não mexido): providers meteorológicos
  chamados fora de requests HTTP (workers/Celery — já usam
  `get_settings()` corretamente ali, porque não há "app instance" nesse
  contexto, é um processo separado).
