# StormPulse web — builds the dashboard SPA and serves it (plus a reverse
# proxy to the API) from a single nginx image (infra ADR-0038).

FROM node:22-alpine AS builder
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
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
