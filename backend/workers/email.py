"""Transactional email delivery via AWS SES or SMTP (FASE 8, account cycle;
SMTP added as a Fase 8 follow-up for a sender who doesn't have a verified
SES domain/identity yet).

SES: same "credentials only ever come from the environment/IAM role, never
a settings field" principle already used for the S3 backup upload
(``infra/backup-postgres.sh``) — ``boto3`` picks up
``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY`` or the instance's IAM role
on its own; this module never touches a credential directly.

SMTP: no such env-only mechanism exists for an arbitrary mailbox, so the
app-password lives in ``Settings.smtp_password`` (a ``SecretStr``, same
pattern as ``redemet_api_key``/``hcaptcha_secret_key``) — sent over an
implicit-TLS or STARTTLS connection, never in the clear.

Neither provider being configured means email itself isn't set up yet
(dev/test default) — sending is skipped and logged, never raised,
mirroring how a missing VAPID key degrades push delivery
(``notification_pipeline.py``) instead of crashing the cycle that
triggered it.
"""

from __future__ import annotations

import hashlib
import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings

logger = logging.getLogger(__name__)


def _correlation_hash(email: str) -> str:
    """Truncated SHA-256 of a recipient address for log correlation without
    writing the address itself to logs (LGPD — same non-reversible-fingerprint
    pattern already used for password reset tokens, ``core/security.py``)."""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]


EmailKind = Literal["email_verification", "password_reset", "organization_invitation"]


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text_body: str
    html_body: str


def render_email(kind: EmailKind, *, link: str) -> EmailContent:
    if kind == "email_verification":
        return EmailContent(
            subject="Confirme seu e-mail — StormPulse",
            text_body=(
                "Confirme seu e-mail para ativar todos os recursos da sua conta "
                f"StormPulse:\n\n{link}\n\n"
                "Se você não criou esta conta, ignore esta mensagem."
            ),
            html_body=(
                "<p>Confirme seu e-mail para ativar todos os recursos da sua conta "
                "StormPulse:</p>"
                f'<p><a href="{link}">{link}</a></p>'
                "<p>Se você não criou esta conta, ignore esta mensagem.</p>"
            ),
        )
    if kind == "organization_invitation":
        return EmailContent(
            subject="Convite para uma organização — StormPulse",
            text_body=(
                "Você recebeu acesso a uma organização no StormPulse.\n\n"
                f"Aceite o convite: {link}\n\n"
                "O convite é pessoal, expira automaticamente e só pode ser utilizado uma vez."
            ),
            html_body=(
                "<p>Você recebeu acesso a uma organização no StormPulse.</p>"
                f'<p><a href="{link}">Aceitar convite</a></p>'
                "<p>O convite é pessoal, expira automaticamente e só pode ser "
                "utilizado uma vez.</p>"
            ),
        )
    return EmailContent(
        subject="Redefinir senha — StormPulse",
        text_body=(
            "Recebemos um pedido para redefinir a senha da sua conta StormPulse.\n\n"
            f"Para escolher uma nova senha, acesse:\n{link}\n\n"
            "Este link expira em 1 hora. Se você não pediu isso, ignore esta mensagem "
            "— sua senha continua a mesma."
        ),
        html_body=(
            "<p>Recebemos um pedido para redefinir a senha da sua conta StormPulse.</p>"
            f'<p><a href="{link}">Escolher uma nova senha</a></p>'
            "<p>Este link expira em 1 hora. Se você não pediu isso, ignore esta "
            "mensagem — sua senha continua a mesma.</p>"
        ),
    )


def render_alert_email(*, title: str, message: str, level: str) -> EmailContent:
    """Item e-mail de alerta — a real gap found live (2026-09-01): the
    `NotificationChannel.EMAIL` enum value already existed on the
    `Notification` model, but nothing ever rendered or sent one — every
    alert only ever reached a user through Web Push/Expo. Separate from
    ``render_email`` above (that one is always link-based — email
    verification, password reset; an alert has no link, just the same
    title/message/level already shown on the dashboard)."""
    level_label = {"green": "baixo", "yellow": "moderado", "orange": "alto", "red": "severo"}.get(
        level, level
    )
    disclaimer = (
        "Este é um aviso automático do StormPulse e não substitui alertas "
        "oficiais (INMET, Defesa Civil, CEMADEN). Em qualquer situação de "
        "risco real, siga os canais oficiais."
    )
    return EmailContent(
        subject=f"⚠️ {title} — StormPulse",
        text_body=f"{message}\n\nNível: {level_label}\n\n{disclaimer}",
        html_body=(
            f"<p><strong>{title}</strong></p>"
            f"<p>{message}</p>"
            f"<p>Nível: {level_label}</p>"
            f"<p style='color:#6b7280;font-size:0.85em'>{disclaimer}</p>"
        ),
    )


def send_email(to_email: str, content: EmailContent, settings: Settings) -> bool:
    """Sends via whichever provider `settings.email_provider` selects
    ("ses", the default, or "smtp"). Returns whether it was actually sent —
    `False` for "not configured" (logged, not raised) or a real send
    failure (logged with the actual error, also not raised: a bounced/
    misconfigured email provider must never break the request/cycle that
    triggered it)."""
    if settings.email_provider == "smtp":
        return _send_via_smtp(to_email, content, settings)
    return _send_via_ses(to_email, content, settings)


def _send_via_ses(to_email: str, content: EmailContent, settings: Settings) -> bool:
    if not settings.ses_from_email:
        logger.warning(
            "SES_FROM_EMAIL not configured — skipping email send",
            extra={"to_hash": _correlation_hash(to_email), "subject": content.subject},
        )
        return False

    client = boto3.client("ses", region_name=settings.aws_region)
    try:
        client.send_email(
            Source=settings.ses_from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": content.subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": content.text_body, "Charset": "UTF-8"},
                    "Html": {"Data": content.html_body, "Charset": "UTF-8"},
                },
            },
        )
    except (BotoCoreError, ClientError):
        logger.exception(
            "Failed to send transactional email via SES",
            extra={"to_hash": _correlation_hash(to_email)},
        )
        return False
    return True


def _send_via_smtp(to_email: str, content: EmailContent, settings: Settings) -> bool:
    if not (settings.smtp_host and settings.smtp_username and settings.smtp_password):
        logger.warning(
            "EMAIL_PROVIDER=smtp but SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD "
            "not fully configured — skipping email send",
            extra={"to_hash": _correlation_hash(to_email), "subject": content.subject},
        )
        return False

    from_email = settings.smtp_from_email or settings.smtp_username
    message = MIMEMultipart("alternative")
    message["Subject"] = content.subject
    message["From"] = from_email
    message["To"] = to_email
    message.attach(MIMEText(content.text_body, "plain", "utf-8"))
    message.attach(MIMEText(content.html_body, "html", "utf-8"))

    try:
        # Port 465 is implicit TLS from the first byte (SMTPS); anything
        # else (587, the Gmail-recommended port) starts in the clear and
        # upgrades via STARTTLS — mixing the two up silently sends
        # credentials unencrypted, so the port picks the mode, not a
        # separate setting.
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
                server.sendmail(from_email, [to_email], message.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
                server.sendmail(from_email, [to_email], message.as_string())
    except (smtplib.SMTPException, OSError):
        logger.exception(
            "Failed to send transactional email via SMTP",
            extra={"to_hash": _correlation_hash(to_email)},
        )
        return False
    return True
