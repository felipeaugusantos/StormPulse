# ADR-0053 — NDVI por talhão (Copernicus Sentinel Hub)

- **Status:** Aceito
- **Data:** 2026-08-24

## Contexto

Levantamento do que a Cropwise (Syngenta) divulga publicamente apontou o
Cropwise Imagery (NDVI/SAVI por talhão) como a peça mais proporcional a
portar pro StormPulse — telemetria de máquinas, plantio a taxa variável
e detecção de nematoides por IA ficam fora de alcance pra um projeto
deste porte. NDVI (Normalized Difference Vegetation Index) é um dado
derivado de satélite (banda vermelha + infravermelho próximo), não uma
regra meteorológica nova — pedido explícito do usuário foi manter isso
restrito à aba Agro, sem tocar na aba Tempestade.

## Decisão

**Fonte de dados: Copernicus Data Space Ecosystem / Sentinel Hub
Statistical API**, não a Agromonitoring API (a alternativa mais simples
de integrar) — escolhida por ser gratuita sem limite de cobertura
geográfica nem risco de cobrança conforme a base de usuários cresce,
consistente com o resto do projeto (INMET, Open-Meteo, GOES-19 — tudo
grátis). Trade-off aceito: mais trabalho de integração (REST de baixo
nível com evalscript, não uma API pronta pra "me dê o NDVI deste
polígono").

**Só se aplica a talhões** — locations com `parent_location_id` setado
(FASE 26) **e** `boundary_geojson` desenhado (FASE 27). Uma fazenda-ponto
não tem polígono real pra calcular um índice de vegetação sobre; nunca
tentado pra ela. `boundary_geojson`, até agora documentado como "nunca
usado pra nada além de renderização", passa a ter seu primeiro
consumidor real.

**Desligado por padrão** (`NDVI_ENABLED=false`), mesmo espírito do
satélite GOES-19 (ADR-0016): exige credenciais próprias (client OAuth2
da Copernicus) e consome cota mensal compartilhada da conta. Uma
tentativa de ligar sem credenciais falha **no startup**, nunca com um
fallback silencioso pra dado simulado — ver o validador em
`app/core/config.py`.

**Pipeline separado** (`workers/ndvi_pipeline.py`, cadência diária —
Sentinel-2 revisita o mesmo lugar a cada ~5 dias, mais frequente que
isso só gastaria cota à toa) que escreve em `ndvi_readings`; o endpoint
(`GET /locations/{id}/agro/ndvi`) só lê a leitura mais recente já
computada — nunca chama o Sentinel Hub ao vivo por request, diferente
dos endpoints de clima (uma consulta ao Statistical API é mais pesada e
limitada por cota do que uma chamada de previsão numérica). Falha de um
talhão (nuvem cobrindo tudo, erro pontual da API) nunca aborta o ciclo
inteiro — cada talhão tem sua própria tentativa isolada.

**Frontend**: painel novo "🌿 NDVI (talhões)" **só dentro do bloco da
aba Agro** (`activeTab === 'agro'`) — o bloco da aba Tempestade não foi
tocado em nenhuma linha. O painel filtra `activeLocations` pra só
talhões com contorno (as fazendas nunca aparecem nele, mesmo estando
"ativas" no sentido geral usado pelos outros painéis agro).
`classifyNdvi` seguindo o mesmo estilo determinístico por faixas de
`classifyCape`/`classifyVpd` — sem ML, limiares padrão de vigor de
vegetação.

## Verificação

- Backend: 10 testes novos (pipeline: desabilitado é no-op; leitura
  criada pro talhão elegível; fazenda sem contorno nunca é checada;
  talhão sem contorno nunca é checado; talhão inativo nunca é checado;
  falha de um talhão não aborta os outros — todos com asserções
  escopadas à própria location do teste, nunca aos totais agregados,
  porque o banco de dev compartilhado carrega centenas de locations
  reais desta sessão; endpoint: 404 sem leitura ainda, 404 pra fazenda,
  devolve a leitura mais recente entre duas, 404 pro talhão de outro
  usuário). Suíte completa (89% cobertura), ruff e mypy verdes.
- **`SentinelHubNdviProvider` não foi exercitado contra uma conta real**
  (sem credenciais Copernicus disponíveis neste ambiente) — os
  endpoints/formatos de request-response foram verificados contra a
  documentação oficial em 2026-08-24, documentado explicitamente no
  próprio módulo. `NDVI_ENABLED=false` por padrão existe exatamente por
  isso: verificar contra uma conta real antes de ligar em produção.
- Web: `tsc -b`, suíte de testes (`classifyNdvi`) e `npm run build`
  verdes. Verificado em navegador real contra a stack local: cadastrada
  fazenda + talhão com contorno, leitura NDVI inserida diretamente
  (simulando o pipeline), confirmado que o painel na aba Agro mostra
  exatamente 1 item (só o talhão, a fazenda nunca aparece) com o valor e
  a classificação corretos e a tag "(simulado)"; confirmado que a aba
  Tempestade não ganhou nenhum conteúdo novo.

## Consequências

- Primeira integração do projeto com uma fonte de imagem de satélite de
  alta resolução (10m, Sentinel-2) — diferente do GOES-19 (~2km,
  meteorológico) já em uso; os dois nunca se sobrepõem em propósito.
- Ligar `NDVI_ENABLED=true` em produção exige, além das credenciais,
  uma verificação manual contra uma conta Copernicus real antes —
  registrado como próximo passo explícito, não incluído aqui.
- `boundary_geojson` deixa de ser puramente cosmético — qualquer mudança
  futura no formato desse campo (hoje um texto opaco só validado como
  GeoJSON parseável) precisa considerar este novo consumidor.
