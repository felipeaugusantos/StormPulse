# ADR-0068 — Alerta de disco cheio para o operador da plataforma

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

O incidente documentado na [ADR-0067](0067-fix-disco-cheio-deploy.md)
(disco do EC2 cheio de imagens Docker acumuladas, travando 3 deploys
seguidos) só foi percebido porque alguém checou os logs de CI
manualmente — nada no sistema avisou proativamente. A causa específica
daquele incidente já foi corrigida (poda proativa de imagens em
`deploy.sh`), mas nada impede o disco de encher de novo por outro motivo
(logs, backups do Postgres, um volume mal dimensionado) sem que ninguém
perceba até o próximo deploy falhar — ou pior, até a aplicação em si
parar de funcionar.

## Decisão

Novo `infra/check-disk-space.sh`, mesmo padrão de `backup-postgres.sh`
(script standalone, roda via cron, nunca depende da stack Docker estar
de pé — um disco cheio pode até derrubar os containers, então o alerta
não pode depender deles pra funcionar). Verifica `df` do path configurado
contra um limite (`DISK_ALERT_THRESHOLD_PERCENT`, default 80%) e manda
e-mail via SES (`aws ses send-email`, mesma credencial/IAM role já usada
pelo upload opcional de backup pro S3) pro e-mail do operador da
plataforma — reusa `PLATFORM_ADMIN_EMAIL` por padrão (a mesma pessoa já
configurada como operador), sem precisar de um cadastro novo.

### Não é um script Python/da aplicação

Cogitado reusar `workers/email.py` (já manda e-mails transacionais via
SES com template), mas descartado: esse caminho depende do container
`worker` estar de pé e do broker Redis acessível — exatamente o que pode
não ser verdade quando o disco está cheio. Um script shell standalone,
rodando via cron direto no host, é o único jeito de garantir que o
alerta ainda funciona mesmo se a stack Docker inteira estiver
comprometida.

### Estado — não manda e-mail toda vez

Um arquivo de estado (`DISK_ALERT_STATE_FILE`) marca um alerta como "em
aberto": enquanto o disco continuar acima do limite, execuções
seguintes do cron (a cada 15 min, sugerido) não reenviam — só a primeira
vez que cruza o limite. Quando volta a ficar abaixo, manda um e-mail de
"normalizado" e limpa o estado. Sem isso, um disco preso em 95% por uma
semana mandaria um e-mail a cada 15 minutos.

### Nunca falha por falta de configuração

Sem `DISK_ALERT_EMAIL`/`SES_FROM_EMAIL` configurados, o script loga e
sai `0` — mesma filosofia do `BACKUP_S3_BUCKET` opcional em
`backup-postgres.sh`. Nunca quebra um cron job só porque o e-mail ainda
não foi configurado.

## Verificação

`infra/tests/test_check_disk_space.sh` (5 cenários, `df`/`aws` stubados,
nunca toca disco real ou SES real): abaixo do limite não alerta; acima
do limite pela primeira vez alerta e abre o estado; acima do limite com
alerta já aberto não duplica; recuperado abaixo do limite manda
"normalizado" e limpa o estado; sem e-mail/remetente configurados nunca
quebra e nunca tenta chamar `aws`. Adicionado ao mesmo job de CI que já
roda `test_backup_postgres.sh`/`test_deploy_rollback.sh`
(`infra/tests/`), e ao escopo do ShellCheck (`scandir: ./infra`, já
cobre qualquer script novo na pasta automaticamente).

**Limite**: não foi possível testar contra uma instância EC2 real com
SES de verdade configurado (exigiria credenciais AWS de produção, fora
do escopo deste ambiente) — a verificação se apoia nos testes stubados
e na reutilização deliberada do mesmo padrão de credenciais/IAM role já
em uso e testado em produção por `backup-postgres.sh`.

## Consequências

- Nenhuma mudança de contrato de aplicação — é infraestrutura pura,
  fora do container da API.
- Precisa de uma linha de crontab configurada manualmente no servidor
  (documentado em `infra/README.md`) — não é ativado por si só ao fazer
  merge deste código, igual a `backup-postgres.sh`.
- Cobre disco cheio; não cobre outras formas de degradação do host
  (memória, CPU, certificado TLS expirando) — fora de escopo desta
  fase.
