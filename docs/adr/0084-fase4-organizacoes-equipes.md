# ADR-0084 — Fase 4: organizações e equipes

## Contexto

Consultores, cooperativas e grupos agrícolas precisam operar no mesmo tenant sem
compartilhar credenciais e sem expor fazendas de outras organizações. O modelo
anterior associava cada local ao usuário que o criou e tinha apenas papéis
legados, insuficientes para delegação por fazenda ou talhão.

## Decisão

- `Tenant` é a organização e continua sendo a fronteira primária de isolamento.
- Os papéis funcionais são proprietário, administrador, agrônomo, operador e
  visualizador. Papéis legados continuam aceitos para contas existentes.
- Proprietário e administrador gerenciam membros. Agrônomo e operador podem
  alterar dados agronômicos; visualizador é somente leitura.
- `organization_wide_access` concede acesso à organização inteira. Caso seja
  falso, `LocationAccessGrant` concede uma fazenda ou um talhão; uma concessão
  da fazenda inclui seus talhões.
- Convites armazenam somente o hash do token, têm validade limitada, são
  bloqueados para reutilização por `accepted_at` e podem ser revogados.
- `access_expires_at` e a revogação do usuário são verificados em toda
  autenticação Bearer ou API key, tornando a revogação imediata.
- Toda criação, aceitação, alteração e revogação de acesso produz um
  `AccessAuditLog` no mesmo tenant.
- As três novas tabelas têm `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL
  SECURITY` e a mesma política de `tenant_id` das demais tabelas protegidas.

## Consequências

O acesso continua falhando fechado em duas camadas: RLS impede leitura física
entre tenants e a autorização da aplicação reduz o conjunto ao escopo do
membro. Administradores restritos não podem conceder locais que não enxergam
nem promover alguém para acesso organizacional. As telas web e mobile usam os
mesmos endpoints, e convites são aceitos por um fluxo público baseado no token
de uso único.
