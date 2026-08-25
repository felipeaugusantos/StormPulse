# ADR-0055 — Criptografia dos dados do usuário em repouso

- **Status:** Aceito
- **Data:** 2026-08-25

## Contexto

Último item de uma lista de 5 pedidos de hardening (autenticação nas rotas,
hash de senha, limite de tentativas de login, RLS — [ADR-0054](0054-row-level-security.md) —
e este). `users.hashed_password` já era protegido (hash Argon2, nunca
reversível), mas `email`, `full_name` e `google_sub` — e os snapshots
`actor_email`/`target_email` denormalizados em `admin_audit_log` — ficavam
em texto plano no Postgres. Um acesso direto ao banco (dump, backup mal
protegido, um operador de infraestrutura sem motivo de negócio) expunha
esses dados sem qualquer trava adicional.

## Decisão

AES-256-GCM (`app.core.crypto`) para os valores em si, com **duas chaves
independentes** (nunca uma só para os dois papéis — hygiene padrão de
criptografia):

- `FIELD_ENCRYPTION_KEY` — AES-256-GCM, nonce aleatório por valor. Cifra
  `users.email`, `users.full_name`, `users.google_sub`,
  `admin_audit_log.actor_email`/`target_email`.
- `FIELD_ENCRYPTION_INDEX_KEY` — HMAC-SHA256, determinístico de propósito.

### O problema que a segunda chave resolve

Nonce aleatório por linha significa que o mesmo e-mail cifrado duas vezes
produz ciphertext diferente — exatamente a propriedade que torna AES-GCM
seguro contra análise de padrão, mas que também impede usar a coluna
cifrada em `WHERE email = ...` ou numa `UNIQUE CONSTRAINT`: duas linhas
com o mesmo e-mail nunca teriam o mesmo ciphertext, então nem duplicata
seria pega. `email_index`/`google_sub_index` (HMAC-SHA256 determinístico,
`app.core.crypto.blind_index`) são as colunas que unicidade e busca por
igualdade (`login`, `_email_exists`, vínculo de conta Google, bootstrap do
platform admin) realmente usam. Um valor de índice vazado só prova que
duas linhas compartilham o mesmo dado subjacente — nunca revela qual é.

### O que ficou fora de alcance de busca exata

A busca por substring do painel admin (`admin/service.py::list_users`,
`func.lower(User.email).like(pattern)`) não tem como sobreviver: SQL LIKE
não funciona contra ciphertext nem contra um HMAC (que só faz igualdade
exata). A busca agora decifra (transparente via `EncryptedString`, ver
abaixo) e filtra em Python, paginando a lista já filtrada. Aceitável na
escala atual do painel admin — precisaria de um índice de busca dedicado
se a base de usuários crescesse muito além disso.

### Transparente pro código de aplicação

`app/db/encrypted_types.py::EncryptedString` (`TypeDecorator` do
SQLAlchemy) cifra/decifra no bind/no load — o atributo do ORM sempre lê e
escreve texto plano (`user.email` continua uma string normal em todo
lugar: construção de `User(...)`, serialização em resposta, log,
`admin_audit_log`). Só o valor que realmente vai pro Postgres é
ciphertext. O único código que precisou mudar são os `SELECT ... WHERE`
por e-mail/`google_sub` (agora contra `*_index`, via `blind_index()`) e a
escrita, que passa a setar o índice junto com o valor.

### Migração — dois estados de partida bem diferentes

Um banco novo (CI, instalação do zero) recebe o schema de
`0001_bootstrap` — que desde a ADR-0031 aplica um **snapshot congelado**
da era pré-FASE-2, não `Base.metadata.create_all()` contra os modelos
atuais — então mesmo um banco novo passa pelo schema legado (varchar,
índice único direto em `email`/`google_sub`) e a migração desta ADR
(`ab4b31a9059a`) faz o trabalho de verdade nele, exatamente como faria em
produção. Cada alteração estrutural é protegida checando o estado atual
da coluna/índice antes de agir (mesmo idioma de
`5e36b6016c06_add_users_google_sub.py`), e o backfill de dados roda sobre
`WHERE email_index IS NULL` — seguro de rodar de novo em qualquer redeploy
(que roda `alembic upgrade head` a cada deploy), sem re-cifrar linhas já
migradas.

**Verificado ao vivo, não só em CI**: banco Postgres reiniciado do zero,
linhas de usuário/tenant/audit-log inseridas manualmente em texto plano
simulando dados de produção pré-migração, `alembic upgrade head` rodado
por cima — ciphertext confirmado no banco (`SELECT email FROM users`
retorna ruído base64, não o e-mail), decriptação e busca por
`email_index`/`google_sub_index` confirmadas via sessão real da
aplicação, `alembic downgrade` confirmado restaurando texto plano e o
schema antigo, `alembic upgrade head` re-executado sobre um banco já
migrado confirmado como no-op. Suíte de testes completa (~300 testes)
verde nos dois estados (banco vazio e banco com os dados legados
inseridos manualmente).

## Consequências

- `FIELD_ENCRYPTION_KEY`/`FIELD_ENCRYPTION_INDEX_KEY` precisam de valores
  fortes e distintos em produção — o padrão de desenvolvimento é recusado
  no startup quando `ENVIRONMENT=production` (mesmo padrão de
  `JWT_SECRET_KEY`/`POSTGRES_APP_PASSWORD`).
- Trocar `FIELD_ENCRYPTION_KEY` depois que já existem dados cifrados torna
  esses dados irrecuperáveis — não há rotação automática; uma rotação real
  precisaria decifrar com a chave antiga e recifrar com a nova, migração à
  parte, fora do escopo desta ADR.
- A busca por e-mail no painel admin decifra e filtra em Python (ver
  acima) — funciona bem na escala atual, mas não escala indefinidamente.
- `email`/`full_name`/`google_sub` continuam sendo texto plano em memória
  dentro do processo da aplicação (é assim que RLS, JWT, resposta HTTP,
  etc. continuam funcionando sem mudança) — esta ADR protege dados em
  repouso no banco, não em memória/trânsito (já coberto por HTTPS em
  produção).
