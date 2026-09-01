# ADR-0075 — Modelo explícito (ECMWF IFS) em vez do "best_match" da Open-Meteo

- **Status:** Aceito
- **Data:** 2026-08-29

## Contexto

Conversa sobre outras fontes de modelo numérico (GFS, ICON, ECMWF, meteoblue)
levou a uma descoberta: a Open-Meteo — que já usamos e já pagamos (ADR-0074)
— não é uma fonte única, é um **agregador** que mistura vários modelos
nacionais (GFS/NOAA, ICON/DWD, ECMWF IFS, entre outros) por trás de uma
lógica de seleção automática chamada `best_match`. Pra fora da América do
Norte/Europa (onde a lógica documentada prioriza HRRR/NAM e ICON-D2/EU
respectivamente), a documentação só diz "cai pra ECMWF IFS, GFS, ou ICON
Global" — sem garantir qual desses três responde de fato pra uma
coordenada no Brasil em um dado momento.

Também descobrimos que o ECMWF (considerado um dos melhores modelos
globais do mundo) tornou seu catálogo real-time **CC-BY-4.0 — de uso
livre, inclusive comercial — desde 2025**, e a Open-Meteo já expõe esse
modelo específico via `models=ecmwf_ifs025`.

## Decisão

### Pedir o ECMWF IFS explicitamente, não confiar no `best_match`

Testado ao vivo (2026-08-29) contra uma coordenada real do sistema: todo
campo que `OpenMeteoWeatherProvider` usa (condição atual, CAPE, ET0,
umidade, rajada máxima) está disponível em `ecmwf_ifs025`, com valores na
mesma faixa do `best_match` atual. `OPEN_METEO_MODEL=ecmwf_ifs025` vira o
novo padrão — substitui uma mistura opaca (que pode variar qual modelo
responde sem aviso) por uma fonte única, conhecida e citável.

### Nunca aplicado ao endpoint de histórico/arquivo

`get_recent_rainfall` usa `archive-api.open-meteo.com`, que é um produto
de reanálise (ERA5), não uma previsão de modelo ao vivo — o parâmetro
`models=` não se aplica lá e nunca é enviado nessa chamada, mesmo com
`OPEN_METEO_MODEL` configurado.

### Configurável, não hardcoded

`open_meteo_model: str | None = "ecmwf_ifs025"` — deixar em branco
(`OPEN_METEO_MODEL=`) volta pro comportamento anterior (`best_match`) sem
precisar reverter código, caso o ECMWF apresente algum problema específico
não previsto nesse teste inicial.

### Outras fontes cogitadas e descartadas por ora

- **meteoblue ("mBlue AI")**: provedor pago à parte (não passa pela Open-
  Meteo). ~€200/mês (Premium) ou a partir de €100/mês (Enterprise) — mais
  caro que a assinatura Standard da Open-Meteo que já temos, sem uma
  vantagem clara de qualidade especificamente pro Brasil que justifique o
  custo adicional.
- **GFS/ICON isolados**: já acessíveis pelo mesmo mecanismo (`models=
  gfs_seamless`/`icon_global`) — não avaliados como alternativa ao ECMWF
  porque este último tem reputação mundial superior como modelo global
  único; multiplicar modelos sem uma necessidade concreta (ex: ensemble)
  não foi perseguido aqui.

## Verificação

`tests/test_weather_open_meteo.py` (+3 testes, `httpx.MockTransport`):
com `model` configurado, a chamada de previsão envia `models=` com o
valor certo; sem `model`, nenhum parâmetro `models` é enviado (preserva o
`best_match` de antes); com ou sem `model`, o endpoint de arquivo nunca
recebe o parâmetro. Suíte completa rodada, sem regressão.

## Consequências

- Nenhum custo adicional — já está incluído na assinatura Standard
  existente (ADR-0074).
- Se o ECMWF IFS um dia se mostrar pior que o `best_match` pra alguma
  região específica do Brasil, a reversão é só limpar uma variável de
  ambiente, sem mudança de código.
- Abre a porta pra, no futuro, comparar explicitamente vários modelos
  (`models=ecmwf_ifs025,gfs_seamless,icon_global` — a Open-Meteo aceita
  múltiplos, retornando um array por modelo) como uma previsão por
  ensemble simples, se algum dia fizer sentido pra engine de risco.
