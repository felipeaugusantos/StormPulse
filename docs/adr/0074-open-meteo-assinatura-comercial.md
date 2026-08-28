# ADR-0074 — Assinatura comercial do Open-Meteo (plano Standard)

- **Status:** Aceito
- **Data:** 2026-08-28

## Contexto

Incidente real em produção: usuários relatando "condições atuais
indisponíveis" de forma persistente (não um blip pontual — se repetiu por
várias horas mesmo após um cache curto de 5 minutos ter sido aplicado).

Investigação ao vivo contra produção (via conta de teste + chamadas
diretas à API) isolou a causa: `/current` e `/agro/rain-forecast` (ambos
batem no mesmo endpoint do Open-Meteo, `api.open-meteo.com/v1/forecast`)
falhavam de forma rápida (~1,2s) e consistente, enquanto `/agro/rainfall`
(endpoint de arquivo histórico, `archive-api.open-meteo.com`, chamado bem
menos) continuava respondendo normal. O mesmo endpoint de previsão,
testado a partir de uma máquina diferente (fora da AWS), respondia 200 sem
problema — apontando pra um bloqueio/throttle específico do IP de
produção, não uma instabilidade geral do Open-Meteo.

Pesquisa nos próprios termos do Open-Meteo confirmou a causa provável: o
nível gratuito é documentado como **só pra uso não-comercial**
("Commercial use" ❌ na tabela de planos) e compartilha limite de taxa por
IP entre todo mundo anônimo (10.000/dia, 5.000/hora, 600/minuto,
documentado). Mesma categoria de problema já identificada com o Google
Earth Engine (ADR-0073) — um provedor gratuito cujo termo de uso exclui
explicitamente produto comercial, mesmo pré-receita.

## Decisão

### Assinar o plano Standard (US$29/mês)

Diferente do Earth Engine (onde a alternativa foi trocar de fonte de
dado), aqui não tinha alternativa gratuita equivalente pronta — INMET e
CPTEC não dão previsão numérica de chuva, e o Open-Meteo é a única fonte
dessa informação na cadeia. Como já é uma funcionalidade essencial em
produção (não uma feature nova), e o custo é baixo, a decisão foi assinar
em vez de trocar de fonte ou remover a funcionalidade.

O plano Standard dá, além da licença comercial: 1M chamadas/mês, **sem
limite de taxa** (diferente do gratuito, que tem teto por minuto/hora/dia
mesmo dentro da cota), servidores dedicados com SLA de 99,9% de uptime, e
redundância geográfica (Europa + América do Norte) — ganhos reais de
confiabilidade além de só resolver o bloqueio.

### Só o endpoint de previsão migra pro host dedicado

O e-mail de confirmação da assinatura foi explícito: **o plano Standard
não inclui a API histórica** (`archive-api.open-meteo.com`) — só o plano
Professional inclui. `OpenMeteoWeatherProvider` (`app/weather/open_meteo.py`)
troca automaticamente pro host `customer-api.open-meteo.com` e anexa
`apikey=` **só** nas chamadas de previsão/condição atual
(`get_current_data`/`get_forecast`, que compartilham a mesma requisição
HTTP) quando `OPEN_METEO_API_KEY` está configurada. O endpoint de arquivo
(`get_recent_rainfall`) nunca recebe a chave nem troca de host — continua
batendo no host público exatamente como antes, já que autenticar lá
provavelmente devolveria 403 em vez de funcionar (não estamos licenciados
pra ele).

Essa parte especificamente (chuva histórica via arquivo público, sem
assinatura) continua tecnicamente sob o termo "só uso não-comercial" do
Open-Meteo — uma lacuna de conformidade que só desaparece se algum dia
for necessário o plano Professional (que também libera dados extras:
histórico, clima, ensemble e radiação via satélite — ver conversa sobre
ADR-0073).

### Chave nunca fica hardcoded

`OPEN_METEO_API_KEY` é uma variável de ambiente nova (`SecretStr`,
`None` por padrão) — sem ela, o provider continua se comportando
exatamente como antes (host público, sem parâmetro `apikey`), então
ambientes de desenvolvimento/teste não precisam de credencial nenhuma.

## Verificação

`tests/test_weather_open_meteo.py` (+3 testes, `httpx.MockTransport`):
com chave configurada, a chamada de previsão vai pro host dedicado com
`apikey` anexada; sem chave, continua no host público sem o parâmetro;
com ou sem chave, o endpoint de arquivo nunca recebe a chave nem muda de
host. Suíte completa rodada, sem regressão.

## Consequências

- Custo recorrente novo: US$29/mês — primeiro custo de infraestrutura
  externa recorrente do projeto (tudo antes era gratuito).
- Aplicar em produção exige editar o `.env` do servidor manualmente via
  SSH (o deploy não regenera esse arquivo a partir de segredos do CI) —
  fora do alcance de automação deste agente, feito pelo operador humano.
- A lacuna de conformidade do endpoint de histórico permanece (ver
  Decisão) — aceitável por agora dado o volume de uso muito menor desse
  endpoint especificamente.
