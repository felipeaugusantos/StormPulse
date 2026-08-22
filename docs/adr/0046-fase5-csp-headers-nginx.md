# ADR-0046 — Fase 5: CSP e headers de segurança no Nginx

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

`backend/app/core/security_headers.py` já protege as respostas JSON da
API (CSP `default-src 'none'`, `X-Frame-Options`, etc.), deliberadamente
pulando `/docs`/`/redoc` para não quebrar o Swagger UI (ADR-0007). A SPA
servida pelo Nginx (`web/nginx.conf` em dev, `infra/tls/nginx-http.conf`/
`nginx-https.conf` em produção, ver ADR-0039/0044) nunca teve headers de
segurança próprios — o navegador do usuário final, ao carregar o
dashboard, não tinha nenhuma política de CSP, HSTS, anti-clickjacking ou
MIME-sniffing aplicada à página em si.

## Decisão

Headers adicionados nos três arquivos Nginx (que duplicam a mesma lógica
de servidor em vez de um `include` compartilhado — cada um recebeu o
mesmo bloco):

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(self), camera=(), microphone=(), payment=()`
  — `geolocation=(self)` porque `LocationSearchCard.tsx` de fato usa
  `navigator.geolocation.getCurrentPosition`; as demais features não são
  usadas em lugar nenhum do app, então ficam bloqueadas.
- `X-Frame-Options: DENY` — fallback legado para navegadores que ainda
  não olham `frame-ancestors` da CSP.
- `Content-Security-Policy`, montada a partir do inventário real do
  bundle (Vite não gera nenhum `<script>`/`<style>` inline — `'unsafe-inline'`
  nunca foi necessário):
  - `default-src 'self'`
  - `script-src 'self' https://accounts.google.com` — Google Identity
    Services (`Login.tsx`), carregado só quando `VITE_GOOGLE_CLIENT_ID`
    está configurado; inofensivo incluir sempre.
  - `style-src 'self'` — nenhuma folha de estilo externa, nenhuma
    CSS-in-JS.
  - `img-src 'self' data: https://tile.openstreetmap.org
    https://server.arcgisonline.com https://accounts.google.com` — os
    dois provedores de tile raster usados pelo MapLibre em
    `StormMap.tsx`, mais o próprio backend (`/api/v1/public/satellite/image.png`,
    já same-origin).
  - `connect-src 'self' https://accounts.google.com
    https://nominatim.openstreetmap.org https://tile.openstreetmap.org
    https://server.arcgisonline.com` — geocodificação (`geocode.ts`) e os
    mesmos hosts de tile (alguns navegadores contam fetch de tile como
    `connect-src`, não só `img-src`).
  - `worker-src 'self' blob:` e `child-src blob:` — MapLibre GL JS roda
    seu worker de parsing de tiles via `blob:` internamente; sem isso o
    mapa quebra silenciosamente.
  - `frame-src https://accounts.google.com` — o botão/prompt do Google
    Identity Services roda dentro de um iframe.
  - `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`,
    `frame-ancestors 'none'` — nenhum plugin embutido, nenhuma
    necessidade de `<base>` dinâmico, nenhum form deveria submeter pra
    outro lugar, e a SPA nunca deve ser embutida em outro site.
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` — só
  em `infra/tls/nginx-https.conf`, dentro do bloco `server { listen 443 ssl; }`,
  que exclusivamente serve HTTPS (a porta 80 nesse mesmo arquivo só
  redireciona). Nunca adicionado em `web/nginx.conf` (dev, sem TLS) nem em
  `nginx-http.conf` (Fase 1 do TLS, antes do certificado existir) — HSTS
  antes de HTTPS real estar disponível quebraria o próprio acesso.

**Escopo deliberado**: todos os headers acima (inclusive a CSP) foram
colocados só dentro de `location /` — a location que serve a SPA — e não
no nível do `server{}`. Isso evita empilhar uma segunda CSP em cima das
respostas já proxied de `/api/`, `/health`, `/ready`, `/docs`, `/redoc`,
`/openapi.json`, que o FastAPI já cabeça com seus próprios headers
(incluindo o CSP `'none'` da API e a ausência deliberada de CSP em
`/docs`/`/redoc`). Duas políticas de CSP diferentes na mesma resposta
seriam combinadas pelo navegador de forma mais restritiva que qualquer
uma das duas sozinha — e quebraria o Swagger UI.

## Verificação

- `nginx -t` validado nos três arquivos (`web/nginx.conf` dentro da
  própria imagem buildada; `nginx-http.conf` e `nginx-https.conf` num
  container `nginx:1.27-alpine` descartável, o segundo com um
  certificado de teste autoassinado no volume `letsencrypt/live` para
  validar que a diretiva `ssl_certificate` também resolve).
- Stack local reconstruída (`docker compose up -d --build` + imagem `web`
  buildada e rodada à parte, ligada à mesma rede Docker) — confirmado via
  `curl -sI`:
  - `GET /` devolve todos os headers novos, incluindo a CSP completa.
  - `GET /api/v1/public/storms` (proxied) devolve só os headers do
    FastAPI (CSP `'none'`, sem duplicação) — confirma o escopo por
    `location`.
- Verificação em navegador real (Browser pane): um listener de
  `securitypolicyviolation` ficou zerado durante toda a navegação —
  login, modo visitante, zoom no mapa, troca de camada — nenhum recurso
  bloqueado pela nova CSP.
- Comparação com produção (que ainda não tinha a CSP no momento do
  teste): o mapa não fazia nenhuma requisição de tile visível em nenhum
  dos dois ambientes (local com CSP nova, produção sem CSP nenhuma) —
  confirma que a ausência de requisições de tile observada é um
  comportamento pré-existente do componente do mapa, não uma regressão
  introduzida pela CSP. Fora de escopo desta fase (não foi pedido para
  investigar o comportamento do MapLibre em si).

### Bug real encontrado no primeiro deploy contra o servidor de verdade

O primeiro push desta fase passou no CI e no deploy automático (rollback
não disparou, `/health`/`/ready` respondiam), mas `curl -sI` contra a
produção real não trazia nenhum header novo. Causa: `infra/tls/
nginx.conf.active` — o arquivo que o `web` de produção realmente monta
(`docker-compose.prod.yml`) — é gerado **uma única vez** por
`infra/setup-tls.sh` (a partir de `nginx-https.conf`, com o domínio real
substituído) e é git-ignorado, porque contém esse domínio. `infra/
deploy.sh` nunca o regenerava — cada deploy normal só troca as imagens
`api`/`worker`/`beat`/`web`, então o conteúdo do CSP editado nesta fase
ficava só no repositório e na imagem publicada, sem nunca chegar ao
arquivo que o Nginx de produção de fato lê.

Corrigido adicionando um passo em `infra/deploy.sh`, logo antes de subir
`api worker beat web`: detecta se o `nginx.conf.active` atual está em
modo HTTPS (`grep "listen 443 ssl"`), extrai o domínio já gravado nele
(`server_name`) e regera o arquivo a partir do `nginx-https.conf`
rastreado no commit que está sendo implantado — sem precisar perguntar o
domínio de novo nem depender de rodar `setup-tls.sh` outra vez. Testado
localmente simulando o arquivo `nginx.conf.active` de produção (com o
domínio real da instância) e confirmando que a regeneração produz
exatamente os novos headers.

### Segundo bug, encontrado ao confirmar a correção acima

Depois da correção do `nginx.conf.active`, os headers apareciam em `/` —
menos `Strict-Transport-Security`, que tinha sido colocado no nível do
`server { listen 443 ssl; }`, fora de qualquer `location`. Causa: no
Nginx, `add_header` **não é mesclado** entre `server` e `location` — uma
`location` que define seus próprios `add_header`s (como a `location /`
desta fase, com CSP e companhia) substitui inteiramente o conjunto
herdado do `server`, em vez de somar a ele. `/health`/`/api/` (que não
têm `add_header` próprio) continuavam herdando o HSTS do `server`
normalmente — só a própria `location /` silenciosamente perdia o header
que mais importa ali. Corrigido listando `Strict-Transport-Security`
explicitamente dentro da `location /`, junto dos demais, e removendo a
duplicata do nível `server`.

## Consequências

- A SPA ganha defesa em profundidade contra XSS (CSP restringe onde
  scripts podem vir e para onde dados podem ir mesmo que um XSS
  consiga injetar HTML), clickjacking (`frame-ancestors 'none'` +
  `X-Frame-Options: DENY`) e MIME-sniffing.
- `/docs`/`/redoc`/`/openapi.json` continuam sem CSP alguma (nem a da
  API, que já pulava essas rotas, nem a nova do Nginx) — consistente com
  a decisão já tomada na ADR-0007, documentado aqui para não parecer uma
  omissão.
- Manutenção futura: os três arquivos Nginx duplicam o mesmo bloco de
  headers; se a política precisar mudar, precisa mudar nos três lugares
  (mesmo padrão de duplicação que já existia para `/api/`, `/health`,
  etc. antes desta fase — não introduzido por ela).
