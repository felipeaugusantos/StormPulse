# ADR-0038 — Dashboard web publicado na mesma EC2, mesma origem

- **Status:** Aceito
- **Data:** 2026-08-22
- **Decisão do dono do produto**: publicar o `web/` (dashboard real, não o
  app raiz de demo) na mesma instância EC2 do backend, servido pelo mesmo
  nginx que já fazia proxy da API — não rodar localmente na máquina do
  usuário.

## Contexto

O deploy da Fase de infraestrutura (ADR-0037) subiu só o backend — sem
nenhuma interface visual publicada em lugar nenhum além do Swagger
(`/docs`). Pra dar acesso real ao produto, faltava publicar o `web/`
(dashboard admin, distinto do app-demo da raiz que o GitHub Pages já
publica — ver [ADR-0034](docs/adr/0034-hardening-fase-9-documentacao-licenca-estrutura.md)).

## Decisão

**Uma imagem só, mesma origem**: `web/Dockerfile` faz build multi-stage —
`node:22-alpine` builda a SPA (`npm run build`), depois copia o `dist/`
pra dentro de uma imagem `nginx:1.27-alpine` final, junto com
`web/nginx.conf`. Esse mesmo nginx serve os arquivos estáticos **e** faz
proxy de `/api/*`, `/health`, `/ready`, `/docs`, `/redoc`,
`/openapi.json` pro serviço `api` — API e frontend na mesma origem
(mesmo IP/porta 80), então:

- Sem CORS pra configurar entre os dois.
- `VITE_API_URL` do build fica vazio (`ARG VITE_API_URL=""`) — o cliente
  HTTP do `web/` (`api.ts`) já cai em caminho relativo (`/api/v1/...`)
  quando essa variável não aponta pra outro host, sem precisar de nenhuma
  mudança de código.
- Quando o cookie de refresh HttpOnly for ativado (ADR-0029, ainda
  desligado), mesma origem significa `SameSite=Lax` sem precisar de CSRF
  token — a decisão que travava a Fase 4 do hardening fica resolvida
  automaticamente por essa topologia, assim que um domínio real existir.

`docker-compose.prod.yml`: serviço renomeado de `nginx` (genérico) pra
`web` (o que ele realmente é agora — frontend + proxy), imagem trocada de
`nginx:1.27-alpine` + volume montado pra
`ghcr.io/felipeaugusantos/stormpulse-web:latest` (publicada por um novo
job em `docker-publish.yml`, mesmo padrão do backend). O antigo
`infra/nginx/nginx.conf` foi removido — a config agora vive em
`web/nginx.conf`, versionada junto do próprio app que ela serve.

## Bug encontrado e corrigido durante o teste local

O primeiro `web/nginx.conf` escrito não incluía `mime.types` — um
`nginx.conf` do zero, ao contrário do padrão que vem com a imagem oficial
(que já tem `include /etc/nginx/mime.types; default_type
application/octet-stream;` no bloco `http`), não tem esse mapeamento por
padrão. Resultado: todo arquivo estático (incluindo o `.js` da SPA) era
servido como `text/plain`. Módulos ES (`<script type="module">`) recusam
executar com esse Content-Type — a tela ficava em branco, sem nenhum
console.error visível (o navegador recusa o script antes dele rodar,
então nada dentro dele consegue logar o próprio erro).

Corrigido adicionando `include mime.types; default_type
application/octet-stream;` ao `web/nginx.conf`. Confirmado via teste real
no navegador (não só `curl`, que não reproduzia claramente o sintoma) —
`curl -I` mostrava o Content-Type correto porque foi testado *depois* do
fix; o navegador continuou mostrando o header antigo por causa de um 304
condicional (mesmo ETag, arquivo byte-idêntico entre builds) até um
`fetch(..., {cache: 'reload'})` forçar a revalidação. Sem esse teste
específico no navegador — não só verificar headers via `curl` — esse bug
teria ido pra produção invisível a qualquer verificação superficial.

## Verificação

Build local (`docker build ./web`), stack completa local
(`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`)
com a imagem do backend já publicada (GHCR, pull real) + a imagem nova do
`web`: `/health`, `/ready` via proxy confirmados; página inicial (Login)
renderizando corretamente; fluxo completo do modo visitante testado no
navegador (clique em "Ver sem login" → dados mock de `/api/v1/public/*`
carregando de verdade através do proxy) — inclusive o aviso de segurança
da Fase 11 (ADR-0036) visível.

## Consequências

- O usuário final agora acessa o produto real (não só a API) por um único
  endereço.
- Nenhuma mudança na Fase 4 do hardening em si — a decisão same-origin
  vs. cross-site ainda depende de um domínio real existir; esta ADR só
  estabelece que, quando ele existir, a topologia same-origin já é a que
  está em uso, o que simplifica essa decisão futura.
- `docker-publish.yml` agora builda e publica 3 imagens por push (backend
  runtime-base, backend runtime-satellite, web) — tempo de CI desse
  workflow aumenta proporcionalmente, aceitável dado o ganho de ter uma
  imagem de frontend pronta pra uso, versionada e testada como as outras.
