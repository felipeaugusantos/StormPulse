# ADR-0010 — Login com Google exige `email_verified=true`

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** Revisão de segurança pós-FASE 15/16

## Contexto

Revisão de segurança (metodologia de 3 fases: identificar → filtrar
falso-positivo com confiança ≥8/10 → reportar) encontrou uma vulnerabilidade
real em `POST /auth/google` (`backend/app/auth/router.py`,
`backend/app/auth/service.py`, introduzidos na FASE 15): o endpoint
vinculava (ou criava) uma conta usando só os claims `email`/`sub` do token
do Google, sem checar `email_verified`.

## Decisão

`login_google` agora rejeita (401) qualquer token cujo `email_verified` não
seja exatamente `true` — tanto quando vem `false` quanto quando o claim
está ausente (fail closed).

## Justificativa

O Google pode emitir um token assinado e válido com `email_verified: false`
(ex.: contas Google Workspace onde um administrador provisionou um
endereço nunca confirmado pelo dono real). Sem essa checagem, um atacante
conseguindo tal token afirmando o e-mail de uma vítima faria o StormPulse
vincular a identidade Google dele à conta de senha já existente da vítima
(ou criar uma conta nova naquele e-mail) — account takeover. Esse é um
padrão de vulnerabilidade documentado em integrações "Sign in with
Google"; a própria documentação do Google recomenda essa checagem.

## Consequências

- Contas Google com e-mail não verificado simplesmente não conseguem
  entrar — comportamento correto, não uma regressão de UX real (a grande
  maioria das contas Google tem e-mail verificado).
- Testes de regressão em
  `backend/tests/test_integration_auth_google.py`:
  `test_google_login_rejects_unverified_email`,
  `test_google_login_rejects_missing_email_verified_claim`,
  `test_google_login_does_not_link_account_with_unverified_email`
  (confirma que a conta da vítima permanece intacta e logável por senha).
- Revisão mais ampla do sistema (JWT, autorização por tenant em todos os
  routers, injeção SQL/PostGIS, pipeline de satélite, frontend) não
  encontrou outras vulnerabilidades de alta confiança nesta rodada.
