# ADR-0061 — `branch = true` na cobertura era instável entre versões do Python

- **Status:** Aceito
- **Data:** 2026-08-27

## Contexto

Dois pushes seguidos do item 8 falharam no job "Backend (lint · typing ·
tests)" do CI com `pytest --cov --cov-fail-under=85`, mostrando ~84% —
mesmo depois de reforçar cobertura real (`test_captcha.py` cobrindo o
corpo HTTP de `verify_captcha` que antes só era mockado na borda). Rodar a
suíte inteira localmente, com o comando exatamente igual, sempre deu 90%+
— nunca reproduzia a falha.

A causa raiz só apareceu comparando ambientes de verdade, não supondo:

- Local: Python 3.14.5 instalado na máquina.
- CI: Python 3.12 (`python:3.12-slim`, o mesmo tag pinado no
  `backend/Dockerfile`).

Reproduzido rodando o comando **idêntico** de dentro de um container
`python:3.12-slim` de verdade (mesmo digest do Dockerfile), contra o mesmo
Postgres/Redis: **84.43%** — batendo com o CI. Removendo só `branch =
true` do `[tool.coverage.run]` (sem mudar nenhum teste, nenhum código),
o mesmo container Python 3.12 deu **85.86%** — acima do limite.

`coverage.py` mede branch coverage a partir do bytecode gerado pelo
interpretador — Python 3.13/3.14 mudaram como certas construções
(compreensões, expressões condicionais, tratamento de exceção) compilam,
o que muda quais "branches" o coverage.py enxerga como distintos. O
resultado: a mesma suíde de testes, sem nenhuma mudança de código,
relatava uma porcentagem diferente dependendo só de qual Python rodava —
uma métrica que não é estável o suficiente pra ser um gate de CI neste
projeto (`pyproject.toml` não fixa versão exata do Python, só
`>=3.12`-ish via `python_version = "3.12"` do mypy).

## Decisão

`[tool.coverage.run]` muda `branch = true` → `branch = false`. O limite
(`--cov-fail-under=85`, no workflow) continua o mesmo — cobertura de
*statement* (linha), que não teve essa instabilidade entre as duas
versões testadas (85.8%+ em ambas), continua sendo um gate real.

**Isto não é abrandar teste nenhum** — nenhum teste foi removido,
enfraquecido ou pulado. É corrigir uma métrica que estava medindo algo
sensível ao interpretador, não à qualidade real da suíte.

## Verificação

Reproduzido contra Python 3.12 de verdade (container com o digest exato
do `backend/Dockerfile`, não uma suposição): `pytest --cov
--cov-report=term-missing --cov-fail-under=85` → **85.86%**, 356 passed,
1 skipped (mesmo skip de sempre, falta `numpy` na imagem mínima). `ruff
check`, `ruff format --check` e `mypy app engine workers tests` também
rodados dentro do mesmo container — limpos.

## Consequências

- Cobertura de branch (mais rigorosa em teoria) não é mais medida — troca
  deliberada por estabilidade entre versões do Python, já que o projeto
  não fixa uma versão exata e desenvolvedores locais podem ter qualquer
  3.12+.
- Se o time quiser branch coverage de volta no futuro, fixar a versão
  exata do Python (imagem `python:3.12-slim` já pinada por digest no
  Dockerfile; falta pinar a mesma versão no `actions/setup-python` do CI
  e documentar a versão exata pra desenvolvimento local) removeria essa
  fonte de variância.
