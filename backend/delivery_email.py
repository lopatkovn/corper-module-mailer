"""SMTP-доставка для mailer worker.

Конфиг приходит из mailer.channel.config (кладётся через PUT /channels/email):
    host, port, use_tls, username, password, sender_name, sender_email

Также есть fallback для legacy core.mail_queue — там SMTP-настройки сидят в
core.mail_settings (читаем напрямую из pg-core через отдельный engine).
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr


log = logging.getLogger("mailer-worker.smtp")


class SMTPError(Exception):
    """Любая ошибка отправки SMTP — поднимается worker'ом и пишется в message.last_error."""
    pass


def _humanize_smtp_error(host: str, port: int, exc: Exception) -> str:
    """Перевести низкоуровневую SMTP-ошибку в текст, понятный пользователю.

    Чаще всего админ видит «TimeoutError: _ssl.c:999» и не понимает что
    делать. Раскладываем по типам:
      - TimeoutError при TLS handshake → провайдер блокирует SMTP-порты
      - ConnectionRefusedError       → сервер не принимает соединение
      - SMTPAuthenticationError      → неверные креды
      - SMTPRecipientsRefused        → сервер отказался от получателя
    """
    name = type(exc).__name__
    detail = str(exc) or name
    if isinstance(exc, TimeoutError) or "timed out" in detail.lower():
        return (f"Не удалось подключиться к {host}:{port} (timeout). "
                f"Возможные причины: провайдер блокирует исходящие порты SMTP "
                f"(25/465/587), сервер недоступен или firewall режет соединение. "
                f"Технические детали: {name}: {detail}")
    if isinstance(exc, ConnectionRefusedError):
        return (f"Сервер {host}:{port} отказал в соединении. "
                f"Проверьте host/port. ({name})")
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (f"Неверные логин/пароль на {host}. ({detail})")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return f"Сервер не принял получателя: {detail}"
    return f"{name}: {detail}"


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

    # Auto-fix по порту:
    # - 465: SMTPS-only (implicit TLS). Без TLS hand-shake клиент шлёт
    #   plain SMTP, сервер ждёт TLS hello → deadlock → timeout. Включаем
    #   use_tls.
    # - 587 (submission): по RFC 6409 это STARTTLS-порт. Подавляющее
    #   большинство SMTP-серверов отказывают AUTH в plaintext на 587 и
    #   ждут STARTTLS. Включаем use_tls по умолчанию — иначе пользователь
    #   получает SMTPAuthenticationError 530 «Must issue a STARTTLS first».
    # Это безопасно: STARTTLS использует тот же TCP-сеанс, не меняет порт.
    if port == 465 and not use_tls:
        log.info("auto-enabling TLS for port 465 (implicit SMTPS)")
        use_tls = True
    elif port == 587 and not use_tls:
        log.info("auto-enabling STARTTLS for port 587 (submission)")
        use_tls = True

    log.info("smtp connect host=%s port=%s tls=%s user=%s",
             host, port, use_tls, username)

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
        log.warning("smtp send failed host=%s port=%s err=%s: %s",
                    host, port, type(e).__name__, e)
        raise SMTPError(_humanize_smtp_error(host, port, e)) from e
