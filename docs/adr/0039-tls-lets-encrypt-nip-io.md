# ADR-0039 — TLS via Let's Encrypt usando nip.io (sem domínio próprio)

- **Status:** Aceito
- **Data:** 2026-08-22
- **Decisão do dono do produto**: configurar TLS agora, mesmo sem domínio
  próprio comprado, usando [nip.io](https://nip.io) — motivado por uma
  limitação real encontrada em uso: a API de geolocalização do navegador
  é bloqueada em qualquer origem que não seja HTTPS (ou `localhost`), o
  que quebrava o botão "usar minha localização" no cadastro de local.

## Contexto

O deploy (ADR-0037/0038) rodava em HTTP puro — funcional, mas com
limitações reais: geolocalização bloqueada pelo navegador, login com
Google inviável (exige HTTPS), e a Fase 4 do hardening
([ADR-0029](docs/adr/0029-hardening-fase-4-cookie-refresh-token-opt-in.md))
continuava parcial. Comprar um domínio não era uma opção imediata —
[nip.io](https://nip.io) resolve `<ip-com-hifens>.nip.io` pro próprio IP
(ex.: `100-48-193-126.nip.io` → `100.48.193.126`), o suficiente pro Let's
Encrypt validar posse do "domínio" via desafio HTTP-01 e emitir um
certificado real, sem custo e sem esperar propagação de DNS.

## Decisão

**Fluxo de emissão em duas fases**, porque o certificado não existe até
ser emitido, mas o nginx precisa estar rodando (servindo o desafio ACHE
na porta 80) pra emiti-lo — problema clássico do ovo e da galinha:

1. **Fase 1** (`infra/tls/nginx-http.conf`) — nginx só em HTTP, serve
   `/.well-known/acme-challenge/` (a partir de um volume compartilhado
   com o container `certbot`) além do app normal.
2. `infra/setup-tls.sh <domínio> <email>` roda `certbot certonly
   --webroot` contra esse nginx já no ar, valida o desafio, grava o
   certificado num volume Docker (`certbot-etc`).
3. **Fase 2** (`infra/tls/nginx-https.conf`) — troca a config ativa
   (`infra/tls/nginx.conf.active`, montada por volume, **não** embutida na
   imagem `stormpulse-web` — precisa poder mudar sem rebuild): porta 80
   vira só redirect + desafio ACME (pras renovações futuras), porta 443
   serve TLS de verdade.

`DOMAIN_PLACEHOLDER` no template HTTPS é substituído pelo domínio real via
`sed` dentro do próprio script — nunca editado à mão, evita erro de
digitação/esquecimento em um arquivo committado.

**Renovação**: `infra/renew-tls.sh` — `certbot renew` (idempotente, só
renova quando faltam <30 dos 90 dias de validade) + `nginx -s reload`
(recarrega sem derrubar conexões). Agendado via cron, semanal — larga
margem antes dos 90 dias.

**`certbot` no `docker-compose.prod.yml`**: não é um serviço de longa
duração (sem `restart:`, nunca sobe com `up -d`) — só existe pra ser
invocado via `docker compose run --rm certbot ...` pelos dois scripts
acima. Dois volumes novos: `certbot-etc` (`/etc/letsencrypt`, os
certificados) e `certbot-webroot` (`/var/www/certbot`, compartilhado com
`web` só pro desafio ACME).

## Consequências diretas

- **Geolocalização do navegador volta a funcionar** — era o motivo
  original desta ADR.
- **Fase 4 do hardening pode ser fechada de fato**: com `web/` e API na
  mesma origem HTTPS (ADR-0038), `SameSite=Lax` sem CSRF token já é
  seguro — `REFRESH_COOKIE_ENABLED=true` pode ser ativado quando o dono do
  produto decidir, sem bloqueio técnico restante.
- Certificado válido por um IP específico via nip.io — se o Elastic IP
  ainda não estiver alocado (ver conversa anterior) e o IP da instância
  mudar, o certificado precisa ser reemitido pro novo `<ip>.nip.io`.
  Reforça a recomendação de alocar um Elastic IP antes de considerar essa
  configuração estável.
- `CORS_ALLOWED_ORIGINS` no `.env` do servidor deve ser atualizado pra
  `https://<domínio-nip.io>` (era `http://<ip>`) — mesmo não sendo
  estritamente necessário com same-origin, mantém a config consistente
  com a realidade.

## Fora de escopo

- Domínio próprio de verdade — nip.io é uma solução de transição,
  documentada como tal; comprar um domínio real continua sendo decisão
  do dono do produto, não assumida aqui.
- HSTS preload / HTTP/2 / OCSP stapling — hardening adicional de TLS,
  não necessário pro objetivo imediato (desbloquear geolocalização e
  fechar a Fase 4).
