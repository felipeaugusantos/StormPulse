# ADR-0095 — Cobertura de teste dos caminhos de falha do guardrail RLS

- **Status:** Aceito
- **Data:** 2026-09-22

## Contexto

Auditoria geral do projeto (pedida diretamente) achou que
`verify_rls_safety()` (`app/core/rls.py`, ADR-0054) — o check que impede
a API de subir em produção se a role conectada puder driblar RLS
silenciosamente, ou se alguma tabela tenant-scoped tiver perdido a
proteção — estava a 76% de cobertura. As linhas não cobertas eram
exatamente os 5 cenários de falha que o check existe pra pegar (role
superuser, role com `BYPASSRLS`, role igual à de migração, tabela sem
`ENABLE+FORCE ROW LEVEL SECURITY`, e o `raise` em produção) — nenhum
teste chamava essa função diretamente, só o caminho feliz era exercitado
de forma indireta pelo boot normal da aplicação em todo outro teste de
integração.

## Decisão

**Cada cenário usa um estado real do Postgres, nunca mock.** Mesma
disciplina já usada no resto da suíte de RLS deste projeto — uma role
`BYPASSRLS`/uma tabela sem RLS forjadas via mock não provariam que o SQL
de `pg_roles`/`pg_class` do check está certo, só que o código sabe
interpretar um resultado fabricado. `tests/test_rls_safety.py` cria (e
sempre remove, mesmo se o teste falhar) uma role `BYPASSRLS` temporária e
uma tabela temporária sem `ENABLE ROW LEVEL SECURITY`.

**A role superuser de bootstrap (`postgres_user`/`postgres_password`,
`migration_database_url`) serve pra dois cenários de uma vez.** Ela É
superuser E tem o mesmo nome que `settings.postgres_user` por definição
— conectar como ela dispara os dois problemas simultaneamente, o que é
uma falha realista (alguém apontar `DATABASE_URL` direto pra role de
migração), não uma artificial.

**`monkeypatch` só no nível de dado de teste (`_TENANT_SCOPED_TABLES`),
nunca na função sob teste.** A lista de tabelas tenant-scoped é
substituída por uma tabela temporária de teste — o SQL/lógica de
`verify_rls_safety` roda inalterada.

## Verificação

6 testes novos, todos passando contra Postgres real:
não-configurado-erra (caminho feliz), superuser levanta em produção,
superuser só avisa fora de produção, role igual à de migração levanta,
`BYPASSRLS` levanta, tabela sem RLS levanta. Cobertura de
`app/core/rls.py` isolada: 76% → 94% (rodando só este arquivo de teste;
as duas linhas restantes, `set_tenant_context`/`bypass_rls`, são cobertas
pelo resto da suíte de integração que já as usa o tempo todo). Suíte
completa: 92,09% de cobertura total, gate de 85% ok, nenhuma role/tabela
de teste ficou órfã no banco depois (confirmado ao vivo via `psql`).

## Consequências

- Nenhuma mudança de comportamento em `app/core/rls.py` — só teste novo.
- Precedente pra qualquer guardrail de segurança futuro parecido: os
  caminhos de falha merecem teste tanto quanto (ou mais que) o caminho
  feliz, mesmo sendo mais trabalhoso de montar.
