# ADR-0031 — Hardening (Fase 6): baseline Alembic com DDL congelado

- **Status:** Aceito
- **Data:** 2026-08-22
- **Decisão do dono do produto:** "Nova baseline com DDL congelado (Recomendado)", escolhida entre três opções apresentadas (nova baseline squashed / manter histórico incremental documentando o comportamento atual / adiar)

## Contexto

`0001_bootstrap_schema.py` (a migração raiz, `revision = "0001_bootstrap"`,
`down_revision = None`) chamava `Base.metadata.create_all()` contra os
modelos ORM **atuais** (`from app import models`). Isso quebra a premissa
básica de uma cadeia de migrações: um banco novo, ao rodar `alembic upgrade
head`, deveria passar pelo mesmo caminho histórico que um banco de produção
real percorreu — cada migração incremental adicionando sua própria coluna,
na sua própria vez.

Na prática isso nunca acontecia. Toda coluna adicionada desde então
(`parent_location_id`, `crop`, `boundary_geojson`, `color`, suporte a Expo
push, etc.) já nascia junto com a tabela no passo `0001_bootstrap`, porque
os modelos atuais já as têm. As migrações incrementais "rodavam" — apareciam
no log, ficavam registradas em `alembic_version` — mas cada uma só conferia
`if coluna not in existing_columns` e não fazia nada, mascarado pelo próprio
guard de idempotência que cada uma tinha (adicionado justamente por causa
desse comportamento, ADR-0022/0023). A cadeia de migrações nunca era
realmente exercitada de ponta a ponta num banco novo — só em bancos que já
existiam antes de cada uma delas ser escrita.

## Decisão

`0001_bootstrap_schema.py` agora aplica um **snapshot de DDL congelado**
(`backend/alembic/versions/sql/0001_baseline_schema.sql`, ~1150 linhas)
gerado via `pg_dump --schema-only` a partir de um banco que rodou todas as
migrações até a ponta atual (`d4f8b2e6c9a3`), em vez de importar
`app.models`. O arquivo foi limpo apenas do `CREATE SCHEMA public;` (o
schema já existe sempre) e do boilerplate de sessão do `pg_dump`
(`SET statement_timeout`, etc.) — nenhuma DDL foi alterada manualmente.

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    sql = (_SQL_DIR / "0001_baseline_schema.sql").read_text(encoding="utf-8")
    op.execute(sql)
```

O ID da revisão (`0001_bootstrap`) **não mudou**. Isso é a peça central da
estratégia: o Alembic rastreia revisões aplicadas em `alembic_version` e
nunca reexecuta uma que já está lá. Qualquer banco que já tenha essa linha
gravada — ou seja, todo ambiente que já existia antes desta ADR — nunca
executa o corpo novo. Só um banco genuinamente novo (`alembic_version`
vazia) passa pelo caminho novo. Isso evita ter que mexer com múltiplos
heads do Alembic ou `alembic stamp` para reconciliar bancos existentes.

`downgrade()` não pode mais chamar `Base.metadata.drop_all()` (voltaria a
importar modelos). Passou a usar duas tuplas fixas, escritas à mão neste
mesmo arquivo (`_TABLES`, `_ENUM_TYPES` — nunca vindas de input externo),
para gerar `DROP TABLE IF EXISTS ... CASCADE` / `DROP TYPE IF EXISTS ...`.

## Matriz de verificação

Testada com containers Postgres descartáveis (não o banco de
desenvolvimento real), todos removidos ao final.

| Cenário | Resultado |
|---|---|
| **Banco novo, `upgrade head`** | Schema resultante idêntico (`pg_dump --schema-only`, diff byte-a-byte no schema `public`, excluindo a tabela `alembic_version`) ao schema de referência gerado pelo código antigo. Única diferença encontrada foi um `COMMENT ON SCHEMA public` cosmético, dependente da versão/imagem do Postgres, não do conteúdo desta migração. |
| **Banco existente já no `head`** | Não aplicável reexecutar — `alembic_version` já tem `0001_bootstrap` gravado; Alembic não toca nele. Nenhuma ação necessária, nenhum dado em risco. |
| **Banco existente em revisão intermediária** | Simulado: banco novo migrado com o código *antigo* até uma revisão intermediária (`d3e8f1a9c7b2`, "add push_subscriptions"), depois trocado o código da migração `0001_bootstrap` para a versão nova (congelada) e rodado `alembic upgrade head` a partir dali. Cadeia completou sem erro até `d4f8b2e6c9a3`; `0001_bootstrap` não foi reexecutado (já estava em `alembic_version`). Limitação conhecida do teste: não é possível simular retroativamente como os *modelos ORM* eram na época de cada revisão intermediária — o teste prova que a troca do conteúdo de `0001_bootstrap` é segura para qualquer banco que já a tenha aplicada, que é exatamente a garantia que a estratégia de ID fixo oferece. |
| **Downgrade** | `alembic downgrade base` a partir do `head`, banco a banco, com sucesso. Corrigiu 3 bugs pré-existentes de nomes de constraint (ver seção abaixo) — não introduzidos por esta ADR, só nunca exercitados fim-a-fim antes dela (nenhum teste ou operação já feita neste projeto chamava `downgrade` até a raiz). Ciclo `downgrade base → upgrade head` repetido depois dos fixes, sem erro. |
| **Re-stamping** | Não necessário e não recomendado como operação de rotina: nenhum banco existente precisa de `alembic stamp`, porque o ID de revisão não mudou e o Alembic já os reconhece como estando no `0001_bootstrap` correto. `alembic stamp` só seria necessário no cenário hipotético (não aplicável aqui) de renomear ou dividir revisões — explicitamente evitado por esta ADR. |

### Bugs de downgrade encontrados e corrigidos

As migrações `a3e8d1c6f4b2` (Expo push), `f2a7c4e9b1d6` (`locations.parent_location_id`)
e `f53125d00c98` (`convective_watches`) criam, no caminho antigo de
`upgrade()`, constraints com nome escolhido à mão
(`uq_push_subscriptions_expo_push_token`, `fk_locations_parent_location_id_locations`,
`fk_alerts_convective_watch_id`) — mas esse ramo só roda quando a coluna
**ainda não existe**. Num banco nascido da baseline congelada, a coluna já
existe desde o `0001_bootstrap`, então esse ramo nunca roda; a constraint
equivalente (`unique=True`/`ForeignKey(...)` sem nome explícito no modelo
ORM) recebe o nome automático do Postgres/SQLAlchemy
(`push_subscriptions_expo_push_token_key`, `locations_parent_location_id_fkey`,
`alerts_convective_watch_id_fkey`). O `downgrade()` de cada uma, ao tentar
`DROP CONSTRAINT` pelo nome fixo antigo, falhava com
`UndefinedObject`.

Corrigido nas três migrações: `downgrade()` agora localiza a constraint via
`sqlalchemy.inspect(...).get_unique_constraints(...)` /
`.get_foreign_keys(...)`, filtrando pela(s) coluna(s) envolvida(s), em vez
de assumir um nome fixo. Funciona tanto para bancos que passaram pelo
caminho antigo (nome à mão) quanto pelo novo (nome automático).

## Consequências

- **Nenhum impacto em bancos existentes.** A garantia vem inteiramente do
  rastreamento de `alembic_version` do Alembic, não de qualquer lógica nova
  — todo ambiente que já tem `0001_bootstrap` marcado como aplicado
  continua exatamente como estava.
- Bancos novos agora percorrem a cadeia de migrações real, coluna por
  coluna, migração por migração — a suíte de testes (que sempre recria o
  banco do zero) passa a validar de fato o histórico, não só o estado
  final.
- `downgrade()` até a raiz agora é uma operação testada e funcional, não só
  teórica — útil para desenvolvimento local e para o cenário de rollback
  descrito na Fase de infraestrutura de produção (ainda não implementada).
- Fora de escopo: não foi feita nenhuma alteração de modelo, regra ou
  threshold meteorológico. O `pg_dump` foi tirado de um banco criado
  exclusivamente para este teste, nunca do banco de desenvolvimento real.
- Backend revalidado por completo depois da mudança: `ruff check`,
  `ruff format --check`, `mypy` (strict), suíte completa — 100% verde,
  89.50% de cobertura.
