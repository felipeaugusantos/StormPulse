# ADR-0052 — `Cache-Control: no-cache` no `index.html` da SPA

- **Status:** Aceito
- **Data:** 2026-08-23

## Contexto

Incidente real: depois de promover a primeira conta a operador da
plataforma (ADR-0048/0050) e confirmar via `curl` que o backend estava
correto, o usuário reportou que o botão "🛠️ Admin" continuava ausente
mesmo depois de sair e entrar de novo dentro do próprio app.

Causa: `web/nginx.conf`/`infra/tls/nginx-*.conf` nunca definiam
`Cache-Control` pra `index.html` — sem esse header explícito, um
navegador pode aplicar cache heurístico (RFC 7234, baseado em
`Last-Modified`) e não bater no servidor de novo por um bom tempo. Pior:
como o StormPulse é uma SPA sem client-side router de verdade, "sair" e
"entrar" dentro do app são só troca de estado do React — **nenhuma
navegação de página acontece**, então nada força o navegador a
reconsultar `index.html`/o bundle JS. A aba do usuário estava rodando o
JavaScript de horas atrás, de antes do deploy que adicionou o botão.

## Decisão

Split explícito de política de cache entre os dois tipos de arquivo que
`web/dist/` produz:

- **`index.html`** (servido por `location /`, inclusive no fallback do
  `try_files` pra qualquer rota da SPA): `Cache-Control: no-cache` —
  sempre revalidado, nunca servido do cache sem checar o servidor
  primeiro. É o único arquivo que nomeia qual bundle JS/CSS está
  vigente; nunca pode ficar desatualizado.
- **`/assets/*`** (nomes com hash de conteúdo do Vite —
  `index-<hash>.js`, etc.): novo `location /assets/` com
  `Cache-Control: public, max-age=31536000, immutable` — o oposto,
  cache máximo, porque o hash no nome já garante que o conteúdo nunca
  muda sob a mesma URL. `location /assets/` (mais específico) tem
  prioridade sobre `location /` pra essas URLs, então não herda o
  `no-cache` do bloco de baixo.

Aplicado nos três arquivos Nginx (`web/nginx.conf`,
`infra/tls/nginx-http.conf`, `infra/tls/nginx-https.conf`) — mesma
duplicação já existente desde a Fase 5 (ADR-0046).

## Verificação

- `nginx -t` nos três arquivos (mesmo processo do ADR-0046: container
  `nginx:1.27-alpine` descartável, certificado de teste pro variante
  HTTPS).
- Build real da imagem `web` + `curl -I` contra os dois tipos de URL:
  `GET /` devolve `Cache-Control: no-cache`; `GET /assets/index-*.js`
  devolve `Cache-Control: public, max-age=31536000, immutable` — os
  dois na mesma resposta que já confirma que `location /assets/`
  realmente intercepta essas URLs antes de `location /`.

## Consequências

- Depois de qualquer deploy futuro, um usuário com o app já aberto numa
  aba **ainda** vai precisar de um reload de verdade (a SPA não se
  auto-atualiza sozinha) — isso é inerente ao modelo de SPA sem
  service-worker de atualização automática, fora de escopo aqui. O que
  muda é que, a partir de agora, um reload de verdade (ou uma aba nova)
  **sempre** pega o código atual — antes disso não era garantido nem
  mesmo com F5 normal, dependendo de quanto tempo tinha passado.
- `/assets/*` ganhando cache agressivo de verdade (antes ficava com o
  comportamento padrão do Nginx, que não é tão longo) deve reduzir
  tráfego repetido do mesmo bundle pra visitantes recorrentes.
