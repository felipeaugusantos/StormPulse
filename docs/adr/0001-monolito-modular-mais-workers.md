# ADR-0001 — Monólito modular + workers (não microserviços)

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 0

## Contexto

Precisamos de um estilo arquitetural para a primeira versão da plataforma.
O processamento meteorológico é pesado e assíncrono; a API precisa ser rápida.

## Opções consideradas

1. **Microserviços desde o início** (auth, locations, storms, alerts… separados).
2. **Monólito único** com tudo no processo da API.
3. **Monólito modular + workers especializados.**

## Decisão

Adotar **monólito modular + workers** (opção 3).

Um único código-base Python, organizado em módulos de domínio coesos
(`app/auth`, `app/locations`, `app/storms`…), com o processamento pesado
(ingestão, detecção, tracking, risco) executado por **workers** assíncronos,
fora do ciclo de request da API.

## Justificativa

- **Vantagens:** menor complexidade operacional (um deploy, um schema),
  transações locais, refatoração fácil entre módulos, iteração rápida no MVP.
  A separação por workers já isola o custo do processamento pesado — o principal
  motivo real para escalar em separado — sem o overhead de rede/observabilidade
  de microserviços.
- **Desvantagens:** limites de módulo dependem de disciplina (não são forçados
  por rede); escala de time grande é mais difícil.
- Microserviços seriam **YAGNI** agora: não há necessidade de escalar módulos
  independentemente nem times separados. A fronteira que importa
  (API leve × engine pesado) é resolvida por workers.

## Consequências

- A API **não** executa processamento pesado no request; lê resultados
  materializados por workers no Postgres/Redis.
- Módulos devem evitar dependências circulares e manter interfaces claras, para
  permitir extração futura em serviços caso necessário.
