"""Transactional email delivery via AWS SES (FASE 8, account cycle).

Same "credentials only ever come from the environment/IAM role, never a
settings field" principle already used for the S3 backup upload
(``infra/backup-postgres.sh``) — ``boto3`` picks up
``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY`` or the instance's IAM role
on its own; this module never touches a credential directly.

No ``ses_from_email`` configured means SES itself isn't set up yet (dev/test
default) — sending is skipped and logged, never raised, mirroring how a
missing VAPID key degrades push delivery (``notification_pipeline.py``)
instead of crashing the cycle that triggered it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings

logger = logging.getLogger(__name__)

EmailKind = Literal["email_verification", "password_reset"]


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
    """Sends via SES. Returns whether it was actually sent — `False` for
    "not configured" (logged, not raised) or a real SES failure (logged
    with the actual error, also not raised: a bounced/misconfigured email
    provider must never break the request/cycle that triggered it)."""
    if not settings.ses_from_email:
        logger.warning(
            "SES_FROM_EMAIL not configured — skipping email send",
            extra={"to": to_email, "subject": content.subject},
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
        logger.exception("Failed to send transactional email via SES", extra={"to": to_email})
        return False
    return True
