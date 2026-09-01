# ADR-0080 — INMET aposentou o endpoint público de leituras por estação

- **Status:** Aceito
- **Data:** 2026-09-01

## Contexto

O painel de saúde dos pipelines mostrava "Células de tempestade (radar)"
como **"nenhum dado ainda"** — não uma pausa de calmaria, um vazio desde
sempre. Isso é diferente do bloqueio de User-Agent já corrigido na
ADR-0077 (aquele dava reset de conexão; a lista de estações
`/estacoes/T` continuava funcionando o tempo todo).

Investigação ao vivo (não suposição):

1. `GET /estacao/{início}/{fim}/{código}` — o endpoint que
   `_fetch_station_readings` usa pra ler chuva/vento/temperatura por
   estação — retorna **`204 No Content`** pra qualquer estação real e
   ativa testada, e pra qualquer intervalo de datas, incluindo **um ano
   atrás**. Não é "estação sem dado hoje": é o endpoint inteiro nunca
   devolvendo nada, em qualquer época.
2. O portal `tempo.inmet.gov.br` (o site oficial de verdade) foi aberto e
   inspecionado ao vivo: ao gerar um gráfico horário de estação, ele
   chama `POST https://apitempo.inmet.gov.br/estacao/front/` com um corpo
   JSON contendo `data_inicio`, `data_fim`, `estacao`, e **dois tokens
   anti-bot gerados por JavaScript** (`seed`, próprio do site, e `gcap`,
   um token do reCAPTCHA v3 do Google). Automatizar isso significaria
   resolver reCAPTCHA em produção — não é um caminho aceitável.
3. Testado `GET /token/estacao/{início}/{fim}/{código}/{token-falso}` —
   respondeu `200 "CHAVE INVÁLIDA!"` (texto puro, não JSON). Isso confirma
   que existe um endpoint **legítimo e programático** de substituição,
   protegido por um token real (não reCAPTCHA).
4. Verificado via busca que esse token não é autoatendimento — é pedido
   por e-mail a `cadastro.act@inmet.gov.br`.

Conclusão: o INMET aposentou silenciosamente o endpoint público de
leituras por estação, sem aviso, sem mudar o código de erro pra algo
distinguível (`204`, indistinguível de "não há dados agora"). O provider
já degradava honestamente (nunca fabricava um dado), então isso nunca
crashou nada — só deixou "Células de tempestade" permanentemente vazio
sem soar alarme.

## Decisão

`InmetWeatherProvider` ganha um `api_token` opcional (config
`INMET_API_TOKEN` — o campo já existia em `Settings`/`.env.example`,
reservado, nunca conectado; agora está). Quando configurado,
`_fetch_station_readings` usa `/token/estacao/{início}/{fim}/{código}/
{token}` em vez do endpoint aposentado; sem token, cai de volta pro
endpoint público antigo (inofensivo — se o INMET algum dia reverter a
aposentadoria, volta a funcionar sozinho, sem exigir deploy).

Um token inválido/expirado responde `200 "CHAVE INVÁLIDA!"` (texto puro),
não `401`/`403` — tratado como um caso distinto de "sem dado hoje":
levanta `WeatherProviderUnavailableError` com uma mensagem que nomeia o
problema real (token rejeitado), em vez de cair no genérico "resposta
inesperada", pra aparecer nos logs de forma acionável.

## Consequências

- **Ainda não está ativo em produção**: o token precisa ser solicitado
  por e-mail pelo dono do produto — não é algo que dá pra automatizar ou
  pedir em nome dele. Até o token chegar e ser configurado no `.env` do
  servidor, `INMET_API_TOKEN` continua vazio e o comportamento é o mesmo
  de hoje (fallback pro endpoint aposentado, retornando vazio).
- `get_current_data`, `get_radar_frames`, `get_forecast` (ponto de ontem)
  e `get_recent_rainfall` compartilham `_fetch_station_readings` — todos
  se beneficiam do token assim que configurado, sem mudança adicional.
- Vale reavaliar `REDEMET_API_KEY` (raios, também "nenhum dado ainda" no
  painel) com a mesma disciplina de investigação ao vivo antes de assumir
  que é só falta de configuração.
