# ADR-0067 — Deploy travado por disco cheio no EC2 (incidente real)

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

Durante a implementação da sequência de 5 itens do Radar Competitivo
(itens 1-5, mesma data), os deploys automáticos dos itens 3, 4 e 5
falharam em produção com:

```
Error response from daemon: failed to create prepare snapshot dir:
failed to create temp dir: ... no space left on device
```

Confirmado via checagem direta (`curl https://.../ready`,
`/openapi.json`) que produção **continuou no ar e saudável** durante
todo o incidente — só ficou presa na versão do item 2 (o último deploy
que tinha sucesso), sem sofrer indisponibilidade. Os itens 3-5 chegaram
ao branch, passaram em todos os testes de CI, mas nunca chegaram a rodar
em produção até este fix.

## Causa raiz

`infra/deploy.sh` publica uma tag Docker **imutável e nova a cada
commit** (`sha-<commit>`, ver `.github/workflows/ci.yml`'s
`deploy.image.outputs.tag`). A única limpeza existente era
`docker image prune -f` no fim do script — que só remove imagens
*dangling* (sem tag), nunca uma tag antiga que ainda existe mas não é
mais referenciada por nenhum container. Com 5 deploys num único dia
(volume incomum), o disco da instância EC2 encheu de imagens de deploys
anteriores nunca removidas.

Pior: quando o disco enche, não é só o `pull` de imagens novas que falha
— o **rollback automático também falha**, porque recriar até os
containers com a imagem *antiga* (já em cache local) ainda precisa de
espaço pra uma nova camada de container. É por isso que o log mostrava
"ROLLBACK FAILED" — não porque a imagem anterior estava corrompida ou
ausente, mas porque não havia espaço nem pra isso.

## Decisão

`infra/deploy.sh` ganha uma poda proativa das tags do StormPulse (nunca
`docker system prune -a`, que arriscaria remover imagens de outro
serviço num host compartilhado) — rodada **antes** de `docker compose
pull`, não só depois de um deploy bem-sucedido. Mantém apenas as 4
imagens atualmente em uso (api/web/worker/beat, capturadas logo antes,
as mesmas que o rollback usaria). Roda em todo deploy, não só quando um
anterior teve sucesso — um servidor já travado por um deploy anterior
falho ainda se autorrecupera na tentativa seguinte, porque a poda roda
de novo antes de qualquer `pull`.

Falha da própria poda nunca aborta o deploy (`|| echo "WARNING..."`,
nunca dispara o `trap rollback`) — pior caso é continuar sem espaço
extra liberado, não quebrar um deploy que teria funcionado de qualquer
jeito.

## Verificação

`infra/tests/test_deploy_rollback.sh` (11 testes, todos ainda passando
sem alteração — o stub de `docker` já tinha um fallback `exit 0`
genérico que cobre as novas chamadas `docker images`/`docker rmi` sem
precisar de stub dedicado). `infra/tests/test_backup_postgres.sh` (4
testes, inalterado). `docker compose config` validado. `bash -n` limpo.

**Limite**: não foi possível testar contra um host real com disco
efetivamente cheio (exigiria acesso SSH à instância de produção, que
este ambiente não tem) — a correção foi verificada por leitura cuidadosa
do fluxo e pelos testes stubados existentes, não por reprodução ao vivo
do incidente. Liberar o espaço já ocupado na instância atual continua
sendo uma ação manual do responsável pela infraestrutura (comandos em
`infra/README.md § Disco cheio`).

## Consequências

- Deploys futuros não devem mais acumular imagens indefinidamente —
  cada um começa liberando o que a versão anterior não precisa mais.
- Não resolve, por si só, o disco já cheio na instância atual — precisa
  de uma limpeza manual uma vez (ou de um deploy manual que rode a nova
  lógica de poda antes de tentar puxar imagens, o que já ajudaria
  bastante mesmo sem intervenção humana adicional).
- Itens 3, 4 e 5 do Radar Competitivo continuam com código pronto e
  testado, aguardando o próximo deploy bem-sucedido pra chegar em
  produção.
