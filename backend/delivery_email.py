"""SMTP-доставка для mailer worker.

Конфиг приходит из mailer.channel.config (кладётся через PUT /channels/email):
    host, port, use_tls, username, password, sender_name, sender_email

Также есть fallback для legacy core.mail_queue — там SMTP-настройки сидят в
core.mail_settings (читаем напрямую из pg-core через отдельный engine).
"""
import smtplib
from email.message import EmailMessage
from email.utils import formataddr


class SMTPError(Exception):
    """Любая ошибка отправки SMTP — поднимается worker'ом и пишется в message.last_error."""
    pass


def send_email(*, to_addr: str, subject: str, body_text: str,
               body_html: str | None, smtp_cfg: dict) -> None:
    """Отправить одно письмо. smtp_cfg = mailer.channel.config (или совместимый dict).

    Поднимает SMTPError при любой проблеме; worker ловит и пишет в last_error.
    """
    host = smtp_cfg.get("host")
    port = int(smtp_cfg.get("port") or 587)
    use_tls = bool(smtp_cfg.get("use_tls", True))
    username = smtp_cfg.get("username") or ""
    password = smtp_cfg.get("password") or ""
    sender_email = smtp_cfg.get("sender_email") or username
    sender_name = smtp_cfg.get("sender_name") or ""

    if not host:
        raise SMTPError("SMTP host не задан")
    if not sender_email:
        raise SMTPError("sender_email не задан")

    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
    msg["To"] = to_addr
    msg["Subject"] = subject or "(без темы)"
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        if use_tls and port == 465:
            # implicit TLS (SMTPS)
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                if username:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                if use_tls:
                    s.starttls()
                    s.ehlo()
                if username:
                    s.login(username, password)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise SMTPError(f"{type(e).__name__}: {e}") from e
