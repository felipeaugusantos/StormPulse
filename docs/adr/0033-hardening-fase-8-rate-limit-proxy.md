# ADR-0033 — Hardening (Fase 8): rate limiting atrás de proxy

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

`app/core/ratelimit.py` tinha duas limitações:

1. **Chave sempre `scope:ip`**, usando `request.client.host` (o peer TCP
   direto) sem nenhuma noção de proxy. Sem proxy na frente (o deploy atual),
   isso é correto. Mas era o único comportamento possível — não havia como
   configurar um proxy reverso real na frente sem quebrar o limiter de duas
   formas possíveis: se o código lesse `X-Forwarded-For` sem checar quem
   está falando, qualquer cliente poderia forjar esse cabeçalho pra escapar
   do próprio limite ou incriminar outro IP; e sem lê-lo, todo tráfego atrás
   de um proxy real cairia no mesmo IP (o do proxy), compartilhando um único
   orçamento entre todos os usuários.
2. **Chave sempre por IP, nunca por identidade** — dois usuários autenticados
   diferentes atrás do mesmo IP/NAT competem pelo mesmo orçamento; e um
   token vazado usado de vários IPs nunca aciona limite algum porque cada
   IP tem seu próprio balde.

Fail-open (requisição permitida se o Redis estiver indisponível) já existia
e continua — decisão deliberada, documentada desde a implementação
original: disponibilidade da API é priorizada sobre rigor do limiter nesse
cenário de falha, e o evento fica logado.

## Decisão

### Política de proxy confiável, fail-safe-closed por padrão

Nova config `TRUSTED_PROXY_IPS` (lista de IPs/CIDRs separada por vírgula),
**vazia por padrão**. `resolve_client_ip()` (`app/core/ratelimit.py`):

- Se `TRUSTED_PROXY_IPS` está vazia, ou o peer TCP direto não está nela →
  `Forwarded`/`X-Forwarded-For` são **completamente ignorados**, sempre usa
  o peer direto. Fecha o vetor de spoofing por padrão: sem essa variável
  configurada, nenhum cliente consegue forjar seu próprio IP de rate limit.
- Se o peer direto **está** na lista confiável → lê o cabeçalho, mas só
  confia no hop mais à direita (o que o próprio proxy confiável anexou).
  Qualquer entrada à esquerda pode ter sido forjada pelo cliente original
  antes de chegar no proxy, e é ignorada.
- Suporta tanto `Forwarded` (RFC 7239, `for=...`) quanto `X-Forwarded-For`
  (de facto), IPv4 e IPv6 (com porta e colchetes).

**Limitação documentada**: só suporta exatamente **um** hop de proxy
confiável. Uma cadeia de múltiplos proxies confiáveis em série não é
suportada — o projeto ainda não tem infraestrutura de produção decidida
(nenhum proxy real na frente hoje), então esse é o caso mais simples que
cobre o cenário mais provável (um reverse proxy/load balancer único). Se
uma topologia com múltiplos hops confiáveis for adotada no futuro, isso
precisa ser revisitado.

### Estratégia de chave: IP para anônimo, tenant+usuário+IP para autenticado

`RateLimiter._client_key()` agora tenta decodificar um `Authorization:
Bearer` válido (reusando `decode_token()`, sem tocar o banco — as claims
`sub`/`tenant_id` já vêm no próprio access token, ver `_issue_tokens` em
`app/auth/router.py`). Um token ausente, malformado ou expirado não é
tratado como erro — a requisição simplesmente cai no caminho anônimo, sem
afetar se ela é permitida ou não; só afeta a granularidade da chave:

- **Anônimo**: `ratelimit:{scope}:anon:{ip}`
- **Autenticado**: `ratelimit:{scope}:user:{tenant_id}:{user_id}:{ip}`

IP continua fazendo parte da chave mesmo autenticado — um token
vazado/compartilhado usado de endereços diferentes não acumula um único
orçamento combinado; cada IP usando aquele token tem seu próprio limite.
`scope` (`auth`/`default`/`public`, já existente) continua separando os
três limites entre si — login/refresh (`auth`) e endpoints públicos
(`public`) na prática são sempre anônimos (não há usuário autenticado
nesses fluxos), então a mudança de chave só tem efeito visível no escopo
`default` (endpoints versionados autenticados).

## Verificação

`tests/test_ratelimit.py` (17 testes, sem Redis real — stub em memória):
acesso direto, proxy confiável (`X-Forwarded-For` e `Forwarded`), proxy não
confiável (cabeçalho ignorado), tentativa de spoof de um cliente direto
(sem proxy configurado), CIDR de proxy confiável, apenas o hop mais à
direita é confiável (prefixo forjado é ignorado), múltiplos clientes atrás
do mesmo proxy com orçamentos independentes, chave anônima vs.
autenticada (tenant+usuário+IP), mesmo usuário de dois IPs com orçamentos
independentes, token malformado tratado como anônimo (nunca como erro), e
os testes pré-existentes de fail-open/Redis indisponível/ausente.

Suíte completa do backend revalidada depois da mudança: `ruff check`,
`ruff format --check`, `mypy` (strict), suíte completa com Postgres+Redis
reais — 100% verde, 89.41% de cobertura.

## Consequências

- Comportamento inalterado para o deploy atual (`TRUSTED_PROXY_IPS` vazio):
  o limiter continua usando o peer TCP direto, exatamente como antes.
- Quando um reverse proxy real existir, ativar essa política exige uma
  ação explícita do operador (preencher `TRUSTED_PROXY_IPS` com o IP/CIDR
  do proxy) — nunca confiança implícita.
- Endpoints autenticados (`default` scope) agora isolam corretamente o
  orçamento de rate limit por usuário, não só por IP — relevante atrás de
  NAT/proxy corporativo, onde muitos usuários legítimos compartilham um
  único IP de saída.
- Fail-open no Redis continua sem alteração de comportamento — decisão já
  tomada e documentada antes desta ADR, só revalidada pelos testes
  existentes.
- Fora de escopo: nenhuma mudança de modelo, regra ou threshold
  meteorológico.
