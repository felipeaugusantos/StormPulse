# ADR-0093 — nginx resolve o upstream `api` dinamicamente, não só no boot

- **Status:** Aceito
- **Data:** 2026-09-22

## Contexto

Incidente real em produção: depois de reiniciar `api`/`worker`/`beat`
(pra pegar `FIELDNOTES_STORAGE_SECRET_KEY` e depois `EMAIL_PROVIDER=smtp`
novos no `.env`), o site inteiro passou a responder `502 Bad Gateway` —
login, cadastro, "esqueci minha senha", tudo. `docker compose ps` mostrava
a `api` como `healthy`; o log do nginx (`web`) mostrava
`connect() failed (111: Connection refused) ... upstream:
"http://172.28.0.4:8000/..."` — um IP que já não era mais o do container
`api` atual.

Causa raiz: `web/nginx.conf` (e as duas variantes em `infra/tls/`) usavam
`upstream stormpulse_api { server api:8000; }`. Um bloco `upstream`
resolve o hostname exatamente uma vez — no início do processo nginx ou
num `nginx -s reload` — e nunca mais. Recriar `api` sozinho (`docker
compose up -d api`, sem tocar em `web`) dá ao container um IP novo na
rede do Docker, mas o `web` continua com o IP velho até alguém reiniciar
o `web` manualmente. Resolvido na hora reiniciando o `web` — mas era
questão de tempo até acontecer de novo, silenciosamente, na próxima vez
que alguém mexesse só no `.env` do `api`.

## Decisão

**`resolver 127.0.0.11 valid=10s;` + `proxy_pass` numa variável, não
mais um bloco `upstream`.** 127.0.0.11 é o DNS interno que o próprio
Docker injeta em todo container numa rede gerenciada pelo Compose —
sempre existe, não é um endereço fixo desta instância. nginx só
consulta o `resolver` quando o destino do `proxy_pass` é uma variável
(`set $upstream_api http://api:8000; proxy_pass $upstream_api;`) — um
literal ou um nome de `upstream` continua resolvido só uma vez, mesmo
com `resolver` declarado. `valid=10s` limita o quanto uma IP trocada
pode ficar "presa" — não elimina o problema, só encurta a janela de 502
de "até alguém notar e reiniciar o web" pra "no máximo 10 segundos".

**Aplicado nos 3 arquivos nginx do projeto** (`web/nginx.conf` — o que
realmente roda em produção — e as duas variantes de
`infra/tls/nginx-{http,https}.conf`, trocadas pelo `infra/setup-tls.sh`
depois da emissão do certificado): mesmo bug, mesma causa, mesmo fix,
consistente nos três.

## Verificação

Reproduzido o incidente de verdade num ambiente isolado (rede Docker
própria, `api` fake com `python -m http.server`, imagem `web` buildada
com a config nova): recriar o `api` deixa o nginx respondendo `502` só
até o `resolver`'s `valid=10s` expirar — depois disso volta a funcionar
sozinho, sem reiniciar o `web`. Sintaxe validada com `nginx -t` real
(imagem `nginx:1.27-alpine`) nos 3 arquivos.

## Consequências

- Nenhuma mudança de comportamento em uso normal (`api` estável) — só
  muda o que acontece quando `api` é recriado sem `web` junto.
- Ainda existe uma janela de até 10s de `502` depois de uma recriação —
  aceitável (era "até alguém notar e reiniciar manualmente" antes).
  Baixar `valid=` mais não vale a pena: mais consultas DNS por segundo
  pro resolver interno do Docker por um ganho marginal.
- `web` não precisa mais ser reiniciado manualmente depois de trocar uma
  variável só do `api`/`worker`/`beat` — mas continua sendo a prática
  mais simples e imediata se alguém quiser eliminar até essa janela de
  10s na hora.
