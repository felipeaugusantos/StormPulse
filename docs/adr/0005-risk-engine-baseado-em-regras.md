# ADR-0005 — Motor de risco baseado em regras documentadas (sem falsa IA)

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 0 (implementação na FASE 8)

## Contexto

O `StormRiskEngine` deve produzir severidade e riscos (chuva, vento, granizo,
raios) + distância, velocidade e ETA. Existe forte tentação de "parecer
inteligente" cedo demais.

## Decisão

Na primeira versão, o motor de risco é **determinístico e baseado em regras
claramente documentadas**, operando sobre dados possivelmente **simulados
(MOCK)**. Toda heurística é:

1. explícita e versionada em configuração central (sem números mágicos);
2. marcada como **experimental** quando não validada meteorologicamente;
3. rotulada como **MOCK** quando os dados de entrada forem simulados.

LLMs e deep learning **não** participam da classificação de severidade.

## Justificativa

- **Confiabilidade e honestidade:** é inaceitável afirmar que o sistema detecta
  tempestades severas reais antes de haver integração e validação reais.
- **Evolutibilidade:** regras claras são um baseline auditável que pode ser
  substituído por modelos especializados (ML) atrás da mesma interface.
- **Segurança do usuário:** classificar supercélula apenas por refletividade é
  cientificamente incorreto e perigoso — proibido.

## Consequências

- A interface `StormRiskEngine` é estável; a implementação começa simples.
- Saídas carregam metadados de proveniência (`source: mock|real`,
  `experimental: true/false`) para não enganar consumidores.
- Limiares de GREEN/YELLOW/ORANGE/RED ficam em configuração central e são
  ajustáveis sem alterar o código.
