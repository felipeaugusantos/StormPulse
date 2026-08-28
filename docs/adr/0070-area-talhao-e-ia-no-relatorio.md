# ADR-0070 — Área do talhão e resumo por IA no relatório semanal

- **Status:** Aceito
- **Data:** 2026-08-28

## Contexto

O relatório semanal (FASE 32, ADR-0063 pro PDF) foi desenhado desde o
início como "algo pra mostrar a um agronomista ou banco" — nesse uso,
duas lacunas concretas apareceram: (1) não existe área do talhão em
lugar nenhum do sistema, algo que qualquer documento agronômico
profissional traz; (2) o relatório é só números e tabela crua — sem uma
frase que já entregue a leitura, o destinatário precisa interpretar
sozinho.

## Decisão

### Área: derivada do contorno já desenhado, nunca um novo cadastro

O talhão já tem `boundary_geojson` (FASE 27, ADR-0024) — o polígono
desenhado no mapa. Em vez de pedir pro usuário digitar a área (que
diverge do que está desenhado) ou depender de uma imagem de satélite,
`Location.area_ha` é uma propriedade calculada sob demanda a partir
desse mesmo polígono, nunca armazenada (o polígono é a fonte de
verdade). O cálculo (`engine.geo.polygon_area_km2`) projeta o anel pra
um plano equirretangular centrado na latitude média do polígono e aplica
a fórmula do cadarço (shoelace) — precisão adequada pra área de talhão
(centenas de metros a poucos km), e deliberadamente mais estável
numericamente que a alternativa exata em esfera (excesso esférico), que
subtrai números quase iguais exatamente na escala em que isso quebra —
mesmo raciocínio de "sem biblioteca de reprojeção" já usado no
dimensionamento de pixel do NDVI (`app/ndvi/sentinel_hub.py`).

Exposto como `area_ha` em `LocationOut` (todo local) e em
`WeeklyReportOut` — `null` sem contorno desenhado, nunca um valor
inventado.

### Resumo por IA: mesma disciplina do resumo de risco de tempestade

Já existia um resumo gerado por IA (ADR-0060) só pra avaliação de risco
de tempestade (`StormRisk`) — o relatório semanal do talhão nunca teve
equivalente. Novo `app/locations/ai_summary.py`, mesma regra do módulo
original: o Claude só reformula números que a própria request já
calculou (chuva, dias secos, área, alertas, NDVI) — nunca uma segunda
fonte desses números, nunca inventa nada fora do prompt. Diferença
deliberada do original: usa `AsyncAnthropic` (não o cliente síncrono),
porque roda dentro do handler assíncrono do FastAPI que atende a
request, não de uma task do Celery — dá pra `await` a chamada junto do
resto da resposta em vez de bloquear o loop.

Opcional (sem `ANTHROPIC_API_KEY` configurada, ou falha da API, retorna
`None` — nunca derruba o endpoint do relatório). Aparece tanto no JSON
quanto no PDF do relatório.

## Verificação

Novo `tests/test_engine_geo.py` (área de quadrado conhecido, direção do
anel não importa, anel degenerado dá zero). Novo
`tests/test_locations_ai_summary.py` (mesmo padrão de mock do
`test_ai_summary.py` original — nunca uma chamada real à API Anthropic
nos testes). `tests/test_integration_locations.py`/
`test_integration_weekly_report.py` estendidos (Postgres real): área
correta pra um contorno real desenhado, `null` sem contorno,
`ai_summary` como `None` no ambiente de teste (sem chave configurada).

Verificado também manualmente no navegador: talhão de ~2km × 2km
desenhado retornou 461.16 ha (bate com o cálculo manual), aparece tanto
na lista de talhões quanto no card do relatório, e a ausência de
`ai_summary` (sem chave local) não gera nenhuma seção vazia nem erro.

## Consequências

- Puramente aditivo — nenhum contrato/endpoint existente muda de forma
  incompatível, só ganha campos novos opcionais.
- Cada abertura de relatório com IA configurada faz uma chamada real à
  API Anthropic (custo por request, não cacheado) — aceitável dado o
  volume esperado (relatório sob demanda, não um ciclo automático).
