# Changelog

## 2026-09-05 — Fase 5: satélite e inteligência do talhão

- NDVI, NDRE, EVI, NDMI e NDWI com série histórica Sentinel-2.
- Cobertura de nuvens, qualidade, confiabilidade e zonas de vigor.
- Anomalias com histórico mínimo e alerta de queda persistente.
- Comparação lado a lado, mapas PNG históricos e exportação CSV.
- Web e mobile atualizados; decisão sobre geometria PostGIS em ADR-0083.

Todas as mudanças notáveis deste projeto serão documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o projeto adota [Versionamento Semântico](https://semver.org/lang/pt-BR/)
(`MAJOR.MINOR.PATCH`) a partir desta versão. Histórico anterior a este
arquivo (todas as "Fases" 1–34 do projeto) não foi reconstruído
retroativamente aqui — está integralmente disponível via `git log`; este
arquivo passa a ser mantido daqui em diante, a cada release.

## [Não lançado]

### Corrigido
- CSP do nginx bloqueava a fonte Inter carregada via Google Fonts
  (`style-src`/`font-src` não incluíam `fonts.googleapis.com`/
  `fonts.gstatic.com`).
- Drill de restore de backup no CI falhava contra um bug real (uma
  instrução `CREATE EXTENSION` sobrevivia ao `--exclude-schema` do
  `pg_dump`) e contra uma race de inicialização do próprio image
  `postgis/postgis` (não relacionada a este repositório).
- ShellCheck no CI falhava por um achado nível "note" (SC2016) não
  suprimido em `infra/deploy.sh`.
- Rollback de deploy deixava `worker`/`beat` presos na imagem nova após
  uma falha (só `api`/`web` eram revertidos).
- Backup pré-deploy não bloqueava o deploy quando falhava, e não conferia
  se o arquivo gerado era de fato utilizável.
- Três validadores de produção que faltavam: cookie de refresh HttpOnly
  desabilitado, provider de clima "mock", nome do role de Postgres
  configurável (deveria ser fixo).
- Notificação push nunca funcionava em produção — `VITE_VAPID_PUBLIC_KEY`
  nunca chegava no build da imagem web.

### Adicionado
- Verificação de segurança de RLS (Row-Level Security) no startup do
  backend.
- Aba "Pipelines" no painel admin, com botão de atualização manual.
- Testes automatizados (stub) de rollback/backup + drill de restore real
  contra Postgres descartável no CI.

## [0.1.0] — histórico pré-CHANGELOG

Toda a linha do tempo do projeto até aqui (fases 1–34: autenticação,
multi-tenant, mapa em tempo real, pipelines de satélite/raios/agro, RLS,
criptografia de dados sensíveis, notificações push, etc.) está registrada
commit a commit em `git log` e nas ADRs em `docs/adr/`. Não reconstruída
retroativamente aqui para não fabricar um histórico que não foi mantido
em tempo real.
