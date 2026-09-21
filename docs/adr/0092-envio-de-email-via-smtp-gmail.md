# ADR-0092 — Envio de e-mail via SMTP (Gmail) como alternativa ao SES

- **Status:** Aceito
- **Data:** 2026-09-21

## Contexto

ADR-0078 já tinha identificado que `SES_FROM_EMAIL`/`AWS_*` nunca foram
configurados de verdade no `.env` de produção — confirmação de cadastro,
redefinição de senha e aviso de alerta por e-mail eram um no-op silencioso
desde sempre, mesmo com o código pronto. Essa mesma ADR recomendava não
usar Gmail (limite de ~500 e-mails/dia, risco de suspensão por uso
automatizado, pior taxa de entrega sem domínio próprio verificado) e
apontava um domínio próprio como pré-requisito natural pro SES.

Você ainda não tem esse domínio configurado pro SES agora — perguntou se
dava pra usar `mefasistemas@gmail.com` como remetente enquanto isso, e se
havia alternativa ao SES que evitasse a burocracia de verificação de
identidade/sandbox da AWS. Decisão: implementar SMTP como provedor
alternativo, escolhido explicitamente por você mesmo sabendo do trade-off
já registrado na ADR-0078 (limite de volume do Gmail é aceitável no
estágio atual do projeto).

## Decisão

**`EMAIL_PROVIDER` (`"ses"`, padrão, ou `"smtp"`) escolhe o provedor,
mesmo padrão de seleção já usado por `weather_provider`.** `send_email()`
(`workers/email.py`) continua sendo o único ponto de entrada pros dois
chamadores existentes (`workers/tasks.py`, `workers/notification_
pipeline.py`) — nenhum deles precisou mudar, o dispatch fica inteiramente
dentro do módulo de e-mail.

**Credencial SMTP é um campo `SecretStr` de verdade, ao contrário do
SES.** O princípio "credencial só vem do ambiente/IAM role, nunca um
campo em `Settings`" (ADR-0059/0078) vale para AWS porque o `boto3`
resolve isso sozinho — não existe mecanismo equivalente para uma caixa de
e-mail arbitrária. `smtp_password` segue o mesmo padrão já usado por
`redemet_api_key`/`hcaptcha_secret_key`: `SecretStr | None`, nunca logada,
listada em `_OPTIONAL_FIELDS_EMPTY_MEANS_UNSET` (uma linha vazia no
`.env` vira `None`, não uma string vazia tratada como "configurado" —
exatamente o bug real que a ADR-0059 já tinha corrigido pros outros
segredos opcionais).

**Porta decide o modo de TLS, não uma flag separada.** 465 é TLS
implícito desde o primeiro byte (`smtplib.SMTP_SSL`); qualquer outra
porta (587, a recomendada pelo Gmail) começa em texto claro e faz
STARTTLS. Confundir os dois manda a senha sem criptografia — a porta
escolhe o modo automaticamente, elimina essa classe de erro de
configuração.

**Nenhuma biblioteca nova.** `smtplib`/`email.mime` são da standard
library — o app já roda em `workers/tasks.py` de forma síncrona (chamado
de dentro de uma task Celery, nunca de um endpoint `async`), então uma
chamada bloqueante de `smtplib` é exatamente tão aceitável quanto a
chamada síncrona de `boto3` que já existia ali do lado.

**Documentado explicitamente que a senha da conta Google não funciona
aqui** — precisa de verificação em duas etapas ativada e uma "senha de
app" gerada em `myaccount.google.com/apppasswords`. Registrado no
`.env.example` pra não virar uma dúvida recorrente.

## Verificação

`tests/test_email.py`: 6 testes novos — não-configurado é pulado
honestamente (mesmo espírito do SES); STARTTLS na porta 587 com
login/sendmail corretos; TLS implícito na porta 465 sem STARTTLS; erro de
SMTP retorna `False` sem propagar exceção. `ruff`/`mypy`/suíte completa
de `test_config.py` (18 testes) e `test_email.py` (9 testes) passando.

## Consequências

- Nenhuma migração, nenhum endpoint novo.
- `EMAIL_PROVIDER` continua `"ses"` por padrão — nada muda pra quem já
  não tinha configurado nenhum dos dois (mesmo comportamento de
  "silenciosamente pulado" de antes).
- Trade-off do Gmail (limite de ~500/dia, sem autenticação de domínio
  própria) é uma escolha explícita e temporária — migrar de volta pro SES
  (ou continuar SMTP com outro provedor) fica tão simples quanto trocar
  `EMAIL_PROVIDER` de volta pra `"ses"` no `.env`, sem tocar em código.
