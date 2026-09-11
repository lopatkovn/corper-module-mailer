"""SMTP-доставка для mailer worker.

Конфиг приходит из mailer.channel.config (кладётся через PUT /channels/email):
    host, port, use_tls, username, password, sender_name, sender_email

Также есть fallback для legacy core.mail_queue — там SMTP-настройки сидят в
core.mail_settings (читаем напрямую из pg-core через отдельный engine).
"""
import io
import logging
import smtplib
from email.generator import BytesGenerator
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


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
               body_html: str | None, smtp_cfg: dict,
               message_id: str | None = None) -> dict:
    """Отправить одно письмо. smtp_cfg = mailer.channel.config (или совместимый dict).

    Возвращает след письма: `{"message_id": …, "receipt": "250 … queued as …"}`.
    Оба поля нужны, когда получатель говорит «письмо не пришло»: по Message-ID
    к письму привязывается возврат от чужого сервера, а квитанцию релея
    (ответ на DATA) понимает поддержка хостера — по ней видно, что он принял
    и что сделал дальше.

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
    # Message-ID ставим сами: если его подставит релей, мы не узнаем значение —
    # и не свяжем с письмом ни возврат, ни ответ получателя.
    mid = message_id or make_msgid(domain=(sender_email.split("@")[-1] or "corper.pro"))
    msg["Message-ID"] = mid
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        if use_tls and port == 465:
            # implicit TLS (SMTPS)
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                if username:
                    s.login(username, password)
                receipt = _send_and_read_receipt(s, sender_email, to_addr, msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                if use_tls:
                    s.starttls()
                    s.ehlo()
                if username:
                    s.login(username, password)
                receipt = _send_and_read_receipt(s, sender_email, to_addr, msg)
    except (smtplib.SMTPException, OSError) as e:
        log.warning("smtp send failed host=%s port=%s err=%s: %s",
                    host, port, type(e).__name__, e)
        raise SMTPError(_humanize_smtp_error(host, port, e)) from e
    log.info("smtp accepted to=%s id=%s receipt=%s", to_addr, mid, receipt)
    return {"message_id": mid, "receipt": receipt}


def _send_and_read_receipt(s: smtplib.SMTP, sender: str, to_addr: str,
                           msg: EmailMessage) -> str:
    """Отправить письмо и вернуть ответ сервера на DATA.

    smtplib.send_message ответ релея не отдаёт — он его просто проверяет и
    выбрасывает. А там как раз лежит номер, под которым письмо легло в очередь
    хостера («250 2.0.0 Ok: queued as 4X2p…»), поэтому конверт собираем руками.
    """
    buf = io.BytesIO()
    BytesGenerator(buf, mangle_from_=False,
                   policy=msg.policy.clone(linesep="\r\n")).flatten(msg)
    s.ehlo_or_helo_if_needed()
    s.mail(sender)
    code, resp = s.rcpt(to_addr)
    if code not in (250, 251):
        raise smtplib.SMTPRecipientsRefused({to_addr: (code, resp)})
    code, resp = s.data(buf.getvalue())
    s.quit()
    text = resp.decode("utf-8", "replace") if isinstance(resp, bytes) else str(resp)
    return f"{code} {text}".strip()[:500]
