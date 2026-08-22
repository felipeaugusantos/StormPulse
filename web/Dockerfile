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
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
