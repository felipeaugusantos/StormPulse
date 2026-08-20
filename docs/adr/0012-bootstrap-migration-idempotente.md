# ADR-0012 — Migrations incrementais precisam ser à prova de bootstrap "vivo"

- **Status:** Aceito
- **Data:** 2026-08-20
- **Contexto:** CI quebrado (banco novo) desde a FASE 15

## Contexto

Você mandou o log de falha do CI (`Backend (lint · typing · tests)` e
`Docker build & stack smoke test`, ambos com "Apply migrations" falhando).
Investigando: `alembic/versions/0001_bootstrap_schema.py` não cria um
schema congelado — ele importa `app.models` (que registra os modelos ORM
*atuais*) e chama `Base.metadata.create_all(bind=bind)`. Ou seja, "bootstrap"
não representa mais o estado da FASE 2, e sim "o que os modelos são agora".

Isso quebrou silenciosamente toda vez que um campo/tabela novo foi
adicionado ao ORM depois da FASE 2: `users.google_sub` (FASE 15),
`convective_watches` + `alerts.convective_watch_id` (FASE 16), e agora
`satellite_images` (FASE 18) — o bootstrap já cria tudo isso em um banco
novo, e a migration incremental que deveria adicionar cada um por cima
falha com `DuplicateColumn`/`DuplicateTable`.

O ambiente de desenvolvimento local nunca pegou isso porque o banco dele
foi criado há muito tempo (antes do `google_sub` existir) e só recebeu
migrations incrementais desde então — nunca rodou o bootstrap "vivo". Já o
CI (e o smoke test do Docker) sempre partem de um Postgres vazio, expondo o
problema a cada push desde a FASE 15 (confirmado: `gh run list` mostra CI
vermelho desde `FASE 16: observação via satélite`, 3 pushes seguidos sem
ninguém notar).

## Decisão

Em vez de reescrever o histórico de migrations (arriscado — exigiria
recriar manualmente o DDL exato da FASE 2 ou fazer squash e re-stampar
qualquer banco já migrado), cada migration incremental que pode colidir com
o bootstrap "vivo" agora verifica a existência da coluna/tabela antes de
criar (via `sqlalchemy.inspect(op.get_bind())`):

- `5e36b6016c06` (`users.google_sub`): checa coluna + índice.
- `f53125d00c98` (`convective_watches` + `alerts.convective_watch_id`):
  checa tabela e coluna separadamente (uma pode existir sem a outra).
- `b7d4e1f9a2c3` (`satellite_images`, FASE 18): checa tabela.
- `a1c2e3f4b5d6` (valores novos do enum `alert_event_type`) **já** usava
  `ALTER TYPE ... ADD VALUE IF NOT EXISTS` — só essa acabou sendo
  acidentalmente correta desde o início.

Verificado de ponta a ponta: subi um Postgres+PostGIS descartável, rodei
`alembic upgrade head` do zero com as migrations corrigidas — todas as 5
aplicaram sem erro, replicando exatamente o que o CI faz.

## Consequências

- Qualquer ambiente novo (CI, clone novo, primeiro deploy) volta a
  funcionar sem precisar tocar no banco de desenvolvimento local (que já
  está no estado correto, migrations idempotentes não fazem nada nele).
- Padrão a seguir daqui pra frente: **toda migration que adiciona
  coluna/tabela precisa desse guard**, porque `0001_bootstrap` vai
  continuar "vivo" (ninguém decidiu congelá-lo nesta rodada — ver
  "Limitação" abaixo).
- `downgrade()` de `f53125d00c98` não ganhou o mesmo guard: em um banco
  bootstrapado do zero, o nome da constraint de FK pode não ser
  `fk_alerts_convective_watch_id` (o `create_all()` usa a convenção de
  nome padrão do SQLAlchemy, não a explícita da migration) — downgrade
  nessas condições pode falhar. Não é exercitado no CI/produção
  (downgrade é operação manual, rara), documentado aqui como lacuna
  conhecida em vez de ignorado silenciosamente.

## Limitação / trabalho futuro não feito agora

A causa raiz de verdade é `0001_bootstrap_schema.py` não ser congelado.
Isso continuará mordendo a cada novo campo/tabela até alguém: (a) reescrever
o bootstrap como DDL explícito e congelado (como toda migration posterior já
é), ou (b) fazer squash de todo o histórico numa migration só, gerada por
autogenerate contra um banco vazio, e re-stampar o banco de dev local.
Adiada por ora — o guard de existência resolve o sintoma imediato (CI
quebrado) sem o risco de reescrever histórico de migration em produção.
