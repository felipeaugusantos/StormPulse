# StormPulse web — builds the dashboard SPA and serves it (plus a reverse
# proxy to the API) from a single nginx image (infra ADR-0038).

FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Empty by default — same-origin deploy (this image's own nginx proxies
# /api/* to the `api` service, see nginx.conf), so the SPA calls the API
# via a relative path. Override only for a build meant to talk to a
# different-origin API.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
# The VAPID *public* key (Web Push opt-in, FASE 22) — not sensitive (it's
# sent to every visitor's browser as-is, same as any public key), but
# still has to match this deployment's own VAPID_PRIVATE_KEY on the
# backend, so it's a build arg rather than a hardcoded default. Empty by
# default means the push opt-in button fails with an honest
# "not configured" error (web/src/push.ts) instead of pretending to work.
ARG VITE_VAPID_PUBLIC_KEY=""
ENV VITE_VAPID_PUBLIC_KEY=$VITE_VAPID_PUBLIC_KEY
# hCaptcha site key (FASE 8) — public by design (same reasoning as the
# VAPID public key above). Empty by default: the captcha widget just
# doesn't render, matching the backend not requiring captcha_token either
# when HCAPTCHA_SECRET_KEY is unset.
ARG VITE_HCAPTCHA_SITE_KEY=""
ENV VITE_HCAPTCHA_SITE_KEY=$VITE_HCAPTCHA_SITE_KEY
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
# The pinned base image ships an Alpine openssl build with a known,
# already-fixed-upstream CRITICAL CVE (heap overflow parsing X.509 certs) —
# `apk upgrade` pulls the patched package from the same Alpine release's
# repo without changing the base image/nginx version itself. Confirmed via
# a real Trivy scan before/after this line (item 7, hardening de
# reprodutibilidade/vulnerabilidades).
RUN apk update && apk upgrade --no-cache && rm -rf /var/cache/apk/*
COPY --from=builder /app/dist /usr/share/nginx/html
# Institutional/portfolio site for the company itself (enzova.com.br) —
# static, no build step, served from the same container as a second
# nginx server{} block (infra/tls/nginx-https.conf) since it needs no
# API proxy of its own. See docs/adr/0079.
COPY enzova-site/ /usr/share/nginx/enzova-site
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
