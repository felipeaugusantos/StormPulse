# ADR-0073 — Umidade do solo regional via NASA POWER (item NASA)

- **Status:** Aceito
- **Data:** 2026-08-28

## Contexto

Item pendente da avaliação de "que outras APIs geram valor" — o satélite
SMAP da NASA mede umidade do solo, mas seu acesso programático real (via
Earthdata Login + granules HDF5/NetCDF, ou via Google Earth Engine) tem
custo ou complexidade real. Descobrimos que o Earth Engine, especificamente,
**não é gratuito pro nosso caso**: o nível não-comercial dele exclui
explicitamente qualquer "atividade fee-for-service" — diferente do
Sentinel Hub (grátis por volume de uso, não por tipo de empresa), o
critério do Google é o tipo de negócio, e uma empresa vendendo um produto
(mesmo pré-receita) não se qualifica. Decisão: não usar Earth Engine agora;
tentar uma via 100% gratuita da própria NASA.

## Decisão

### Fonte real: NASA POWER, não o satélite SMAP em si

A [NASA POWER API](https://power.larc.nasa.gov/docs/services/api/) é
gratuita para qualquer uso (comercial ou não, sem exigência de atribuição
— confirmado no próprio termo de uso), sem login, sem chave. Ela publica
`GWETTOP`/`GWETROOT`/`GWETPROF` (umidade de superfície/raiz/perfil, fração
de saturação 0-1) — não são a leitura direta do instrumento do SMAP, e sim
uma estimativa do modelo de reanálise GEOS da própria NASA. Mesma
categoria de informação, caminho de acesso muito mais simples (REST/JSON
puro, confirmado ao vivo contra uma coordenada real do sistema
2026-08-28) — nenhum parsing de arquivo binário de satélite necessário.

### Resolução: ainda mais regional que o SMAP, nunca por talhão

A resolução nativa do GEOS por trás do POWER é da ordem de ~50km — mais
grosseira até que os ~9-11km do próprio SMAP. Por isso este dado nunca é
tratado como leitura do talhão (ao contrário do NDVI): é contexto regional
complementar à chuva já medida, rotulado como tal em toda superfície
(tela, PDF) — mesma honestidade já aplicada ao limite geográfico do
DETER/PRODES (ADR-0072).

### Chamada ao vivo no relatório, não um ciclo de fundo

Diferente do DETER/PRODES (WFS do INPE se mostrou instável em teste) e do
NDVI (Sentinel Hub tem cota mensal a preservar), a NASA POWER respondeu
rápido e de forma estável nos testes manuais, e não tem cota conhecida
relevante pro nosso volume. Por isso é consultada ao vivo dentro de
`build_weekly_report`, mesmo padrão já usado pro resumo por IA — uma
falha aqui (rede, todos os dias da janela vindos como *fill value*
`-999.0`, o que acontece rotineiramente pros 1-2 dias mais recentes
enquanto o modelo ainda processa) nunca derruba o relatório inteiro,
só omite essa seção (`soil_moisture: null`).

### `SOIL_MOISTURE_ENABLED=false` por padrão, mesmo sendo grátis

Mesma decisão já tomada pro desmatamento (ADR-0072): ligar sob decisão
explícita do operador, não por padrão, por ser uma dependência externa
nova ainda sem histórico de uso real em produção — não por custo ou
instabilidade conhecida dessa vez, só por prudência com algo recém-escrito.

## Verificação

`tests/test_soilmoisture_nasa_power.py` (`httpx.MockTransport`): parâmetros
corretos na requisição (`GWETTOP,GWETROOT,GWETPROF`, `community=AG`),
"anda pra trás" até o dia mais recente sem *fill value* em nenhum dos três
parâmetros (um dia com só um dos três preenchido ainda é descartado —
nunca mistura valor real de um parâmetro com placeholder de outro),
levanta erro honesto quando todos os dias da janela são inválidos ou a
rede falha. `tests/test_integration_weekly_report.py` (+3 testes,
Postgres real): omitido por padrão (`SOIL_MOISTURE_ENABLED=false`),
presente com valores corretos quando ligado (provider fake, sem chamada
de rede real em CI), degrada pra `null` sem derrubar o relatório quando o
provider falha. `tests/test_weekly_report_pdf_rendering.py` (+2 testes):
renderiza com e sem a seção. Suíte completa rodada (92.66% de cobertura,
gate de 85% ok).

## Consequências

- Nenhuma tabela nova — é lido ao vivo a cada relatório, nunca persistido
  (diferente de NDVI/desmatamento).
- Se a NASA POWER algum dia se mostrar instável como o WFS do INPE, o
  padrão já está pronto pra virar um ciclo de fundo (mesmo idioma do
  DETER/PRODES) sem mudar o formato do dado exposto no relatório.
- O MapBiomas (cobertura de solo nacional) continua fora de escopo — exige
  Earth Engine, que tem custo real pro nosso tipo de uso (ver Contexto).
