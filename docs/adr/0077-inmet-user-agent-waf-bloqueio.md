# ADR-0077 — INMET bloqueava nosso User-Agent, não estava fora do ar

- **Status:** Aceito
- **Data:** 2026-09-01

## Contexto

Usuário relatou "Células de tempestade: 0, nenhuma célula" e "Raios: 0" em
produção — investigação (painel Admin → Pipelines) mostrou que essas duas
métricas nunca tiveram um único dado desde o início ("nenhum dado ainda"),
não uma calmaria passageira. Diferente da instabilidade já conhecida e
mitigada do INMET pra previsão/temperatura (que tem CPTEC/Open-Meteo como
reserva — ADR-0011/0015), **não existe fallback nenhum pro radar** — é a
única fonte, e vinha falhando desde sempre, silenciosamente, graças à
própria correção de resiliência já existente (falha de radar não derruba
mais o ciclo inteiro, só fica "sem dado esta rodada").

## Investigação

Testado `apitempo.inmet.gov.br` direto de duas redes completamente
diferentes (a máquina local, fora da AWS): toda chamada devolvia
`Recv failure: Connection was reset` — parecia o servidor do INMET fora
do ar. Mas o padrão era estranho: o handshake TLS completava normalmente,
só a requisição HTTP em si era resetada — assinatura mais de bloqueio
ativo (WAF/anti-bot) do que de servidor genuinamente indisponível.

Testado com um `User-Agent` de navegador real: a mesma URL respondeu 200
com dados reais das estações **imediatamente**. Confirmado o oposto
também: o User-Agent padrão do httpx (`python-httpx/0.28.1`, exatamente o
que `InmetWeatherProvider` envia) reproduz o bloqueio de forma
determinística, 100% das vezes. **O INMET nunca esteve fora do ar** — um
WAF na frente da API está bloqueando o fingerprint de cliente HTTP
genérico, não IPs específicos nem a StormPulse — provavelmente afeta
qualquer integração que use uma biblioteca HTTP sem cabeçalhos de
navegador.

## Decisão

### Headers de navegador real no cliente do INMET

`InmetWeatherProvider` agora constrói seu `httpx.AsyncClient` padrão com
`User-Agent`/`Accept` de navegador real (`_BROWSER_LIKE_HEADERS`) —
aplicado só quando nenhum `client` é injetado externamente (não afeta os
testes, que sempre injetam seu próprio `MockTransport`).

### Segundo bug real encontrado no caminho: corpo vazio quebrava tudo

Ao testar a correção ao vivo, uma estação individual devolveu corpo vazio
(não JSON válido) em vez de `[]` — `response.json()` levanta
`json.JSONDecodeError` (um `ValueError`), que **não** é `httpx.HTTPError`
nem `WeatherProviderUnavailableError` — os dois únicos tipos que o
try/except por estação em `get_radar_frames` já esperava. Isso derrubava
a busca de leitura pra **todas** as estações por causa de uma só, e o
mesmo problema existia em `_fetch_stations()` (lista de estações),
capaz de derrubar o ciclo inteiro de ingestão. Ambos os pontos agora
convertem um corpo não-JSON em `WeatherProviderUnavailableError`, a mesma
degradação honesta já usada pra formato de resposta inesperado.

## Verificação

Confirmado ao vivo contra o INMET real (não só mock): lista de estações
(674 estações reais), `get_radar_frames` e `get_current_data` funcionando
de ponta a ponta depois da correção — 5 tentativas seguidas bem-sucedidas.
`tests/test_weather_inmet.py` (+3 testes): cliente padrão nunca envia o
User-Agent genérico do httpx; corpo não-JSON na lista de estações vira
`WeatherProviderUnavailableError` em vez de crash; uma estação com corpo
não-JSON nunca derruba a leitura das outras (mesmo espírito de
`test_radar_frames_skip_cells_below_rain_threshold`). Suíte completa
rodada (93,11% de cobertura, gate de 85% ok).

## Consequências

- Sem custo, sem infraestrutura nova — só cabeçalhos HTTP diferentes.
- A instabilidade "conhecida" do INMET citada em ADRs anteriores pode ter
  sido, pelo menos em parte, esse mesmo bloqueio o tempo todo — vale
  observar se a taxa real de falha do INMET cai depois desse deploy.
- O mesmo risco (WAF bloqueando cliente HTTP genérico) pode existir em
  outros provedores gov.br que ainda não tiveram esse sintoma observado —
  não replicado preventivamente em todos agora, só corrigido onde foi
  confirmado ao vivo.
