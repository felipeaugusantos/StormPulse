# ADR-0059 — Ciclo de conta: verificação de e-mail, redefinição de senha, termos, anti-abuso

- **Status:** Aceito
- **Data:** 2026-08-27

## Contexto

Auditoria de código (não suposição) confirmou que, além de registro/login/
Google OAuth/refresh/logout, nada do ciclo de conta existia: sem coluna
`email_verified`, sem endpoint de verificação, sem `forgot-password`/
`reset-password`, sem aceite de termos rastreado, sem infraestrutura de
e-mail transacional (nenhum SMTP/SES/SendGrid no código), e anti-abuso
limitado a rate limit genérico (sem CAPTCHA). Decisões do responsável pelo
projeto: e-mail via **AWS SES**, anti-abuso via **hCaptcha**.

## Decisão

### E-mail transacional (AWS SES)

`workers/email.py` — `boto3` chama SES diretamente, credenciais **só**
via ambiente/IAM role (nunca um campo de settings), mesmo princípio já
usado pro upload S3 do backup (`infra/backup-postgres.sh`). Sem
`SES_FROM_EMAIL` configurado, o envio é pulado e logado, nunca falha a
requisição que disparou — mesmo espírito de `VAPID_PRIVATE_KEY` opcional
pro push.

Disparo é sempre fire-and-forget via Celery, nunca bloqueando a resposta
HTTP: `app/core/tasks.py::send_transactional_email` enfileira
`workers.tasks.send_transactional_email_task` exatamente como
`trigger_pipeline` já fazia pro botão "atualizar agora" do admin — a
imagem `api` nunca importa `boto3` diretamente, só a imagem `worker` o
faz de verdade.

### Tokens de verificação/redefinição — sem tabela nova

Reaproveitado o mesmo mecanismo JWT que já assina access/refresh tokens
(`app/core/security.py`), com dois novos `type` de token:

- `email_verification` (24h) — verificar duas vezes é inofensivo, não
  precisa de controle de uso único.
- `password_reset` (1h) — carrega um claim `pwd_fp` (fingerprint curto do
  `hashed_password` atual no momento da emissão). Redefinir a senha muda
  `hashed_password`, o que invalida naturalmente qualquer token emitido
  antes daquela troca — controle de uso único sem precisar de uma tabela
  separada de tokens só para isso.

### Endpoints novos (`app/auth/router.py`)

- `POST /auth/verify-email` — `{token}` → 204, idempotente.
- `POST /auth/resend-verification` — autenticado, reenvia se ainda não
  verificado.
- `POST /auth/forgot-password` — `{email}` → sempre 204, exista ou não a
  conta (nunca revela se um e-mail está cadastrado).
- `POST /auth/reset-password` — `{token, new_password}` → 204, ou 400
  pra token inválido/expirado/já usado.

### Verificação de e-mail nunca bloqueia login

`User.email_verified` é informativo (exposto em `UserOut`, drives um
banner no frontend) — **não** impede login. Bloquear login de contas já
existentes na primeira deploy dessa mudança seria quebrar contas que já
funcionavam, não uma correção de segurança (regra explícita deste
trabalho: preservar funcionalidade existente). Um login via Google marca
`email_verified=true` imediatamente — o próprio `login_google` já recusa
um e-mail do Google não verificado antes de chegar aqui, então isso
reflete um fato já estabelecido, não uma suposição.

### Aceite de termos (`terms_accepted_at`)

`RegisterIn.accept_terms` precisa ser `true` explicitamente (422 se
ausente/falso) — timestampado em `User.terms_accepted_at`. Contas
pré-existentes ficam com `NULL` (nunca preenchido retroativamente como se
tivessem aceitado algo que não existia no momento do cadastro delas —
seria fabricar consentimento).

### Anti-abuso (hCaptcha)

`app/core/captcha.py::verify_captcha` — opcional: sem
`HCAPTCHA_SECRET_KEY`, `/auth/register` e `/auth/login` não exigem
`captcha_token` (dev/test sem conta hCaptcha). Configurada, todo request
sem token válido é rejeitado com 400 antes de tocar o banco. Uma falha de
rede na própria API do hCaptcha é tratada como captcha inválido (nunca
abre uma brecha por indisponibilidade do terceiro).

## Migração

`b8f4c2a7e6d1_add_users_account_cycle_fields.py` — `email_verified`
(NOT NULL, default false), `email_verified_at`, `terms_accepted_at`
(ambas nullable). Backfill: contas com `google_sub` já vinculado viram
`email_verified=true` (fato real — Google já verificou, ver
`login_google`); todas as outras começam `false`, sem fabricar histórico.

## Verificação

17 testes novos (`tests/test_account_cycle.py`,
`tests/test_email.py`), contra Postgres/Redis reais — nunca contra um
banco mockado: registro exige aceite de termos; conta nova começa não
verificada; verificação com token válido/idempotente/token
inválido; reenvio de verificação reporta `sent=false` depois de já
verificado; esqueci-senha nunca revela se o e-mail existe; redefinição de
senha muda a senha de verdade (login com a antiga falha, com a nova
funciona) e o token vira inutilizável depois do primeiro uso; hCaptcha
mockado (sem chamada de rede real) confirma que fica opcional sem
configuração e obrigatório/validado quando configurado. Envio de e-mail
via SES testado à parte (`test_email.py`) com `boto3.client` mockado —
nunca uma chamada AWS real.

Suíte completa (`ruff check`, `ruff format --check`, `mypy app engine
workers tests`, `pytest --cov=app --cov=workers --cov=engine
--cov-fail-under=85`) rodada localmente contra Postgres/Redis reais antes
do push — 90.91% de cobertura, sem regressão nos testes existentes (só a
suíte inteira de `/auth/register` em outros arquivos de teste precisou
ganhar `accept_terms: true` no payload, mudança mecânica, não de
comportamento).

## Consequências

- Nenhum código-fonte de terceiro (Google/hCaptcha) é confiado sem
  verificação server-side — mesmo padrão já usado pro ID token do Google.
- `LICENSE`/CAPTCHA/conta SES continuam decisões/contas que só o
  responsável pelo projeto pode criar — ver o relatório final desta
  rodada pra lista exata de passos manuais pendentes.
- Frontend (checkbox de termos, widget hCaptcha, fluxo de
  esqueci/redefinir senha, aviso de e-mail não verificado) é tratado em
  commits separados, mesma rodada.
