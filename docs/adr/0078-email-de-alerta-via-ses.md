# ADR-0078 — Aviso de alerta também por e-mail (AWS SES)

- **Status:** Aceito
- **Data:** 2026-09-01

## Contexto

Pedido direto: "podemos implementar o email da gmail para aviso de
notificação e confirmação de cadastro?". Investigação mostrou que boa
parte já existia:

- **Confirmação de cadastro**: já implementada via AWS SES
  (`email_verification`, item 8/ADR-0059) — é o "✉️ Confirme seu e-mail"
  já visível no dashboard.
- **Aviso de alerta por e-mail**: lacuna real. `NotificationChannel.EMAIL`
  já existia como valor do enum na tabela `notifications`, mas nada nunca
  populava ou entregava esse canal — todo alerta só chegava por push
  (Web Push/Expo). Achado ao vivo, não uma suposição.

Sobre usar Gmail especificamente: recomendação foi não usar — conta
Gmail pessoal/Workspace tem limite baixo de envio automatizado (500/dia),
risco real de suspensão por uso automatizado, e pior taxa de entrega sem
autenticação de domínio própria. O AWS SES já implementado resolve tudo
isso e é muito mais barato em escala.

## Decisão

### E-mail é reforço do push, não um canal separado por linha

`Notification.channel` (coluna já existente, nunca usada de fato) não
ganhou um segundo fluxo de criação de linha — uma única `Notification`
continua representando uma tentativa de entrega, só que agora cobrindo
todo canal aplicável: `run_notification_delivery_cycle`
(`workers/notification_pipeline.py`) tenta push (se houver assinatura) **e**
e-mail (sempre, pro e-mail da própria conta) na mesma passada, marcando
`SENT` se qualquer um dos dois funcionar. Evita redesenhar o modelo de
dados ou tocar nos quatro pontos que criam `Notification`
(`pipeline_service.py`, `agro_pipeline.py`, `satellite_pipeline.py`,
`official_warnings_pipeline.py`) só pra isso.

### `NotificationStatus.SUPPRESSED` não é mais alcançável por esse pipeline

`Notification.user_id` é FK `NOT NULL` com `ON DELETE CASCADE` — uma
notificação nunca sobrevive à exclusão do usuário dono, então o antigo
caminho "sem assinatura push E sem usuário" nunca foi um estado real
alcançável (confirmado tentando construir esse cenário num teste: a
própria constraint do banco recusa o insert). Trocado por um
`assert user is not None` documentando a garantia, em vez de manter um
branch de status pra um cenário que não existe — sem usuário e-mail
sempre é tentado, então "sem nada a fazer" deixou de existir como estado
de negócio (o enum continua existindo, só não é mais produzido aqui).

### `render_alert_email` é uma função nova, não uma variação de `render_email`

`render_email(kind, *, link)` (`workers/email.py`) sempre existiu
baseado em link (verificação, redefinição de senha) — um alerta não tem
link, só título/mensagem/nível já mostrados no dashboard. Em vez de forçar
esse formato num parâmetro que não se aplica, `render_alert_email(*,
title, message, level)` é uma função separada que produz o mesmo
`EmailContent`, reaproveitando o `send_email()` já existente sem mudar a
assinatura dele.

## Verificação

`tests/test_notification_pipeline.py`: e-mail entregue sozinho quando não
há assinatura push nenhuma (o ponto real do item); push continua contando
como sucesso mesmo com e-mail falhando (nem um substitui o outro); sem
push e sem SES configurado vira `FAILED` honesto (não mais `SUPPRESSED`,
já que agora sempre existe uma tentativa real). Suíte completa rodada
(93,13% de cobertura, gate de 85% ok).

## Consequências

- **Ainda não está ativo em produção**: confirmado que `SES_FROM_EMAIL`/
  `AWS_*` nunca foram configurados no `.env` do servidor — nem a
  confirmação de cadastro por e-mail funcionou de verdade até hoje, era
  um no-op silencioso. Precisa: conta AWS com SES habilitado, domínio/
  e-mail remetente verificado, saída do modo sandbox do SES, e uma IAM
  role na instância EC2 com `ses:SendEmail` (sem chave de acesso solta no
  `.env`, mesmo princípio já usado pro backup em S3).
- O domínio próprio recém-adquirido (Hostinger) resolve o pré-requisito
  de "e-mail remetente verificado" com aparência profissional
  (`alertas@dominio.com` em vez de um endereço avulso) — próximo passo
  natural depois desta ADR.
