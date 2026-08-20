# ADR-0011 — INPE/CPTEC como fallback automático do INMET

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 17 — redundância de fonte meteorológica

## Contexto

Durante esta sessão o INMET (fonte real principal desde a FASE 13) ficou
fora do ar por um período — confirmado de três formas independentes
(chamada real via Docker retornando `RemoteProtocolError`, navegação direta
ao endpoint do INMET mostrando erro do próprio servidor deles, e nosso
`/ready` seguindo saudável). Isso não é um bug do StormPulse: é
instabilidade real de infraestrutura externa. Você perguntou se existe
outra fonte de monitoramento além do INMET.

Pesquisei ao vivo e confirmei: o INPE também opera o **CPTEC**, com um
serviço XML público (`servicos.cptec.inpe.br/XML`), sem chave. Testei o
endpoint `GET /cidade/7dias/{lat}/{lon}/previsaoLatLon.xml` diretamente
para Ribeirão Preto e recebi uma previsão real, funcionando, **enquanto o
INMET seguia fora do ar** — confirmando que os dois serviços têm modos de
falha independentes (times/infra diferentes dentro do INPE).

## Decisão

1. Novo `CptecWeatherProvider` (`backend/app/weather/cptec.py`),
   implementando a mesma interface `WeatherProvider` das fontes reais
   existentes. Só implementa `get_forecast` de verdade — `get_current_data`,
   `get_radar_frames` e `get_warnings` levantam
   `WeatherProviderUnavailableError` honestamente, porque o serviço XML do
   CPTEC genuinamente não tem esses dados para coordenadas arbitrárias
   (condições atuais só existem para capitais; não há refletividade de
   radar nem feed de avisos oficiais aqui).
2. Novo `FallbackWeatherProvider` (`backend/app/weather/fallback.py`):
   decorator genérico que tenta o provider primário em cada método da
   interface e, se ele levantar `WeatherProviderUnavailableError` ou
   `httpx.HTTPError`, tenta o secundário. O fallback é **por método**, não
   uma troca de provider inteiro — importante porque o CPTEC não pode
   ajudar em `get_radar_frames`/`get_current_data` (vai falhar igual, sem
   piorar nada), mas ajuda de verdade em `get_forecast`.
3. `backend/app/weather/factory.py`: quando `WEATHER_PROVIDER=inmet` (o
   padrão de produção) e `CPTEC_FALLBACK_ENABLED=true` (novo, **padrão
   ligado** — ao contrário do satélite da FASE 16, aqui o custo extra só
   existe quando o primário já falhou, então não há razão para desligar por
   padrão), o INMET é envolvido pelo fallback automaticamente. `cptec`
   também pode ser selecionado como fonte isolada
   (`WEATHER_PROVIDER=cptec`), útil para teste manual.
4. `WeatherProviderUnavailableError` foi movida para uma classe-base em
   `app/weather/provider.py` (o módulo de interface compartilhado); as
   classes de mesmo nome em `inmet.py` e `cptec.py` agora herdam dela —
   compatível com o código existente que importava de `app.weather.inmet`,
   mas permite que `backend/app/locations/router.py` e o
   `FallbackWeatherProvider` capturem qualquer fonte real com um único
   `except`.

## Honestidade sobre o "7 dias"

O endpoint chama-se `7dias` mas devolveu **6** entradas `<previsao>` no
teste ao vivo (2026-08-20 a 2026-08-25) — documentado no docstring de
`cptec.py`, não arredondado para "7" só porque é o nome do endpoint.

## Consequências

- Quando o INMET está no ar, nada muda — o CPTEC nunca é chamado.
- Quando o INMET falha, `/locations/{id}/forecast` continua respondendo com
  dados reais (agora do CPTEC) em vez de 404, sem qualquer dado fabricado —
  a `Provenance` do resultado deixa claro que veio do CPTEC
  (`source_name="INPE/CPTEC"`, `source_kind=FORECAST_MODEL`).
- `get_radar_frames` (usado pelo ciclo de ingestão de 5 min) continua
  falhando quando o INMET está fora — comportamento inalterado, porque o
  CPTEC não tem dado equivalente. O pipeline de detecção de células segue
  parado até o INMET voltar, como já era documentado.
- Testes: `backend/tests/test_weather_cptec.py` (parsing do XML real,
  erros honestos por método) e `backend/tests/test_weather_fallback.py`
  (lógica do decorator, com providers falsos — independente de qualquer
  formato de rede real).
