# ADR-0008 — Login com Google, modo visitante, previsão real do INMET

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 15

## Contexto

Três pedidos combinados: login social (Google), acesso público sem conta
("modo visitante") mostrando células de tempestade e avisos oficiais, e
previsão de tempo real via INMET (`InmetWeatherProvider.get_forecast()`,
que desde a FASE 13 sempre devolvia `points=[]` — a previsão do INMET exige
geocódigo IBGE do município, nunca resolvido até agora).

## Decisões

### Login com Google

- Só o `id_token` do Google Identity Services é aceito e verificado
  server-side (`google.oauth2.id_token.verify_oauth2_token`, biblioteca
  `google-auth`) contra `GOOGLE_CLIENT_ID` — não usamos o fluxo de
  authorization-code, então **não precisamos do client secret**.
- `users.google_sub` (nova coluna, `UNIQUE`, `NULLABLE`) é a chave de
  vínculo — não o e-mail, que pode mudar. `authenticate_google` busca por
  `google_sub` primeiro, depois por e-mail (linka uma conta de senha já
  existente), só então cria tenant+conta nova.
- Contas só-Google recebem um **hash de senha aleatório inutilizável**
  (`hash_password(secrets.token_urlsafe(32))`) em vez de `hashed_password`
  virar `NULLABLE` — evita espalhar checagem de `None` pelo código de auth
  por uma coluna que continua, na prática, sempre exigida.
- Frontend carrega o script `accounts.google.com/gsi/client` **dinamicamente**
  (sem pacote npm) — consistente com as poucas dependências do dashboard
  (`maplibre-gl`, `react`, `react-dom`). Sem `VITE_GOOGLE_CLIENT_ID`
  configurado, o botão simplesmente não aparece — não é um erro.

### Modo visitante

- `/api/v1/public/storms`, `/public/storms/nearby` e `/public/warnings` —
  sem autenticação, rate limit próprio e mais restrito (`scope="public"`,
  30/60s por padrão) que o geral.
- **Sem tabela de avisos persistida.** `get_warnings(lat, lon)` já existia
  como chamada ao vivo ao provider ativo (mock ou INMET); o endpoint
  público só remove a exigência de login, não inventa uma fonte nova.
  Persistir avisos globais (sem exigir lat/lon) fica para uma fase futura,
  se justificada.
- Frontend: sem `react-router-dom` (não existia no projeto) — `App.tsx`
  passou de um booleano `authed` para um estado de três valores (`'login' |
  'visitor' | 'authed'`), suficiente para três telas.

### Previsão real do INMET (FASE 13 finalmente com dados)

- **Resolução de geocódigo IBGE sem geocoder de terceiros**: o nome da
  estação INMET mais próxima (`DC_NOME`) é comparado (maiúsculas, sem
  acento) contra a lista pública de municípios do IBGE por UF
  (`servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios`).
  Sem match ⇒ `WeatherProviderUnavailableError`, nunca um geocódigo
  inventado.
- **A API de previsão do INMET só devolve 5 dias** (hoje + 4) —
  confirmado ao vivo (`apiprevmet3.inmet.gov.br/previsao/{geocode}`),
  parâmetros extras (`?dias=7`, `/7`) são ignorados pelo servidor. Um 6º
  ponto (ontem) vem de uma leitura real da estação, não de previsão — dá
  contexto antes/depois sem fingir 7 dias que a fonte não tem.
- `precipitation_mm`/`precipitation_probability` ficam `None` nos pontos de
  previsão: o INMET só dá um resumo em texto livre ("Poucas nuvens"), não
  um número — nada é inferido do texto.
- **Novo endpoint** `GET /locations/{id}/forecast` (o primeiro consumidor
  real de `WeatherProvider.get_forecast()` desde que a interface existe).
  Falhas de rede genuínas (`httpx.HTTPError`, não só respostas 4xx/5xx)
  viram 404 honesto — descoberto durante o desenvolvimento porque a API do
  INMET ficou fora do ar (verificado ao vivo, múltiplas vezes) e sem esse
  tratamento o endpoint devolvia 500 cru em vez de uma falha esperada.

### Duas armadilhas de `Depends(get_settings)` (mesma classe do ADR-0007)

`/auth/google` e o teste que verifica "sem `GOOGLE_CLIENT_ID` configurado
→ 503" expuseram de novo o problema documentado no ADR-0007
(`get_settings()` é `@lru_cache` de processo, ignora a instância de
`Settings` passada a `create_app()`). Desta vez o bug realmente impedia
testar os dois estados (configurado/não configurado) na mesma sessão de
pytest — não dava para mitigar só com variável de ambiente. Corrigido de
verdade, mas com escopo mínimo: novo `get_request_settings(request) ->
Settings` em `app/api/deps.py`, lendo `request.app.state.settings` (o que
`create_app()` já guarda) em vez do cache global — usado **só** no
endpoint novo, sem tocar `register`/`login`/`refresh`/`get_current_user`
(que não precisam da variação por instância e não valia o risco de mexer
em código já testado).

## Fora do escopo (documentado, não escondido)

- Apple Sign-In (exige conta de desenvolvedor paga).
- Persistência de avisos oficiais (tabela + job de ingestão).
- Previsão de 7 dias via fonte complementar (INPE/CPTEC) — 5 dias reais é o
  que existe hoje sem misturar fontes.
- Refatorar todos os endpoints para usar `get_request_settings` — só o novo
  `/auth/google` foi corrigido; o resto continua com o comportamento já
  documentado no ADR-0007.
