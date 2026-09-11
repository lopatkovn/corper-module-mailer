"""Трек писем: сторож застрявших и разбор возвратов (bounce).

Зачем. Отправка почты у нас заканчивается словами «релей принял» — дальше
письмо живёт вне портала, и на вопрос «а оно точно дошло?» ответить было
нечем. Здесь два недостающих куска:

  • сторож — письмо висит в очереди дольше положенного (SMTP лежит, кончился
    диск, сменился пароль): админ узнаёт об этом сам, а не от поставщика;
  • возвраты — чужой сервер вернул недоставку; по нашему Message-ID находим
    письмо и пишем причину человеческим текстом.

Тревоги уходят в Telegram — единственный канал, который работает, когда
сломана как раз почта.
"""
import email
import imaplib
import logging
import re
from datetime import datetime
from email.header import decode_header, make_header

from sqlalchemy import text as sql_text

log = logging.getLogger("mailer-worker.mailwatch")

# Сколько письмо может лежать в очереди, прежде чем это считается поломкой.
STUCK_MINUTES = 10
# За раз разбираем не больше, чтобы не залипнуть на большом ящике.
BOUNCE_BATCH = 40

_BOUNCE_SENDERS = ("mailer-daemon", "postmaster", "mail delivery", "mailer daemon")
_MID_RE = re.compile(r"message-id:\s*(<[^>]+>)", re.I)
_DIAG_RE = re.compile(r"diagnostic-code:\s*(.+)", re.I)
_STATUS_RE = re.compile(r"^status:\s*([245]\.\d+\.\d+)", re.I | re.M)
_ACTION_RE = re.compile(r"^action:\s*(\w+)", re.I | re.M)


def _hdr(msg, name: str) -> str:
    raw = msg.get(name)
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


# ── Тревога в Telegram ────────────────────────────────────────────────────

def alert_admins(core_engine, tg_send, bot_token: str, text: str) -> int:
    """Отправить тревогу дежурному чату, а если он не задан — админам лично.

    Служебный чат главнее личных сообщений: системная тревога адресована
    роли, а не человеку — в чате её видит тот, кто на смене, и она не теряется
    в личной переписке уволившегося администратора. Поэтому если задан
    `platform_setting.mail_alert_chat_id`, шлём ТОЛЬКО туда.

    Личные сообщения super_admin'ам остаются запасным вариантом: пока чат не
    назначен, тревога всё равно должна кого-то найти.

    Возвращает число доставленных сообщений; ноль — громко в лог, потому что
    молча потерянная тревога хуже отсутствующей.
    """
    if core_engine is None or not bot_token:
        log.warning("alert: нет core-подключения или токена бота — тревога не ушла")
        return 0
    with core_engine.begin() as conn:
        chat = conn.execute(sql_text(
            "SELECT value FROM core.platform_setting WHERE key='mail_alert_chat_id'"
        )).scalar()
        if chat and str(chat).strip():
            targets = [str(chat).strip()]
        else:
            rows = conn.execute(sql_text(
                "SELECT DISTINCT t.tg_user_id FROM core.employee_telegram t "
                "JOIN core.employee e ON e.id = t.employee_id "
                "WHERE e.is_super_admin AND e.is_active AND t.tg_user_id IS NOT NULL"
            )).mappings().all()
            targets = [r["tg_user_id"] for r in rows]
    if not targets:
        log.warning("alert: не задан дежурный чат и ни у одного super_admin нет "
                    "привязки в Telegram — тревога «%s» не ушла", text[:80])
        return 0
    sent = 0
    for chat_id in targets:
        try:
            tg_send(bot_token, chat_id=chat_id, text=text)
            sent += 1
        except Exception as e:      # чужой чат не должен рушить рассылку
            log.warning("alert: не доставлено в чат %s: %s", chat_id, e)
    return sent


# ── Сторож застрявших писем ───────────────────────────────────────────────

def check_stuck(core_engine, notify) -> int:
    """Письма, которые висят в очереди дольше STUCK_MINUTES.

    `notify(text)` — куда сообщить. Про каждое письмо тревожим один раз
    (`alert_sent_at`): сторож работает каждую минуту, а проблема обычно одна
    на все письма сразу — иначе админ получит сотню одинаковых сообщений.
    """
    if core_engine is None:
        return 0
    with core_engine.begin() as conn:
        rows = conn.execute(sql_text(
            "SELECT id, to_addr, subject, error_text, created_at FROM core.mail_queue "
            "WHERE status='pending' AND alert_sent_at IS NULL "
            f"  AND created_at < NOW() - INTERVAL '{STUCK_MINUTES} minutes' "
            "ORDER BY created_at LIMIT 50"
        )).mappings().all()
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        first = rows[0]
        # Причина у всех застрявших обычно общая — показываем её один раз.
        reason = (first["error_text"] or "").strip() or "письмо не ушло, ошибки сервер не вернул"
        lines = [
            f"⚠️ Почта не уходит: {len(rows)} писем висят в очереди дольше {STUCK_MINUTES} минут.",
            f"Первое: №{first['id']} → {first['to_addr']}",
            f"Тема: {first['subject'] or '(без темы)'}",
            f"Причина: {reason[:300]}",
            "Проверьте SMTP в разделе «Администрирование → Уведомления».",
        ]
        notify("\n".join(lines))
        conn.execute(sql_text(
            "UPDATE core.mail_queue SET alert_sent_at=NOW() WHERE id = ANY(:ids)"),
            {"ids": ids})
    log.warning("сторож: %s писем висят дольше %s минут", len(rows), STUCK_MINUTES)
    return len(rows)


# ── Разбор возвратов ──────────────────────────────────────────────────────

def _looks_like_bounce(msg) -> bool:
    ctype = (msg.get_content_type() or "").lower()
    if ctype == "multipart/report":
        return True
    sender = _hdr(msg, "From").lower()
    subject = _hdr(msg, "Subject").lower()
    if any(w in sender for w in _BOUNCE_SENDERS):
        return True
    return ("undeliver" in subject or "returned mail" in subject
            or "не доставлено" in subject or "delivery status" in subject)


def _extract_bounce(raw: bytes) -> tuple[str | None, str]:
    """Из тела возврата достаём Message-ID исходного письма и причину.

    Формат возврата не стандартизирован до конца, поэтому идём по убыванию
    надёжности: отчёт delivery-status → заголовки вложенного оригинала →
    просто первый Message-ID в тексте.
    """
    text = raw.decode("utf-8", "replace")
    # Свой Message-ID у самого возврата идёт первым — он нам не нужен,
    # поэтому ищем все и берём последний, он из вложенного оригинала.
    mids = _MID_RE.findall(text)
    mid = mids[-1] if mids else None

    diag = _DIAG_RE.search(text)
    status = _STATUS_RE.search(text)
    action = _ACTION_RE.search(text)
    parts = []
    if action:
        parts.append({"failed": "отказано", "delayed": "задержано",
                      "delivered": "доставлено"}.get(action.group(1).lower(),
                                                     action.group(1)))
    if status:
        parts.append("код " + status.group(1))
    if diag:
        parts.append(diag.group(1).strip())
    reason = " · ".join(parts) if parts else "сервер получателя вернул письмо без пояснения"
    return mid, reason[:800]


def poll_bounces(core_engine, imap_cfg: dict, notify) -> int:
    """Забрать из почтового ящика отправителя новые возвраты.

    Флаги писем не трогаем — ящиком пользуются люди, и «прочитано» после нас
    сбивало бы их. Вместо этого помним последний разобранный UID в
    core.platform_setting.
    """
    host = (imap_cfg or {}).get("host")
    user = (imap_cfg or {}).get("username")
    password = (imap_cfg or {}).get("password")
    port = int((imap_cfg or {}).get("port") or 993)
    if not (host and user and password):
        return 0
    if core_engine is None:
        return 0

    with core_engine.begin() as conn:
        last_uid = conn.execute(sql_text(
            "SELECT value FROM core.platform_setting WHERE key='mail_bounce_last_uid'"
        )).scalar()
    try:
        last_uid = int(str(last_uid or 0))
    except (TypeError, ValueError):
        last_uid = 0

    found = 0
    try:
        im = imaplib.IMAP4_SSL(host, port, timeout=30)
        try:
            im.login(user, password)
            im.select("INBOX", readonly=True)
            # UID-диапазон, а не поиск по UNSEEN: «непрочитанное» — состояние
            # человека, а не наше.
            typ, data = im.uid("search", None, f"UID {last_uid + 1}:*")
            uids = [int(x) for x in (data[0] or b"").split()] if typ == "OK" else []
            uids = [u for u in uids if u > last_uid][:BOUNCE_BATCH]
            max_uid = last_uid
            for uid in uids:
                max_uid = max(max_uid, uid)
                typ, msgdata = im.uid("fetch", str(uid), "(BODY.PEEK[])")
                if typ != "OK" or not msgdata or not msgdata[0]:
                    continue
                raw = msgdata[0][1]
                msg = email.message_from_bytes(raw)
                if not _looks_like_bounce(msg):
                    continue
                mid, reason = _extract_bounce(raw)
                if not mid:
                    continue
                with core_engine.begin() as conn:
                    row = conn.execute(sql_text(
                        "UPDATE core.mail_queue SET bounced_at=NOW(), bounce_reason=:r "
                        "WHERE message_id=:m AND bounced_at IS NULL "
                        "RETURNING id, to_addr, subject"), {"r": reason, "m": mid}).mappings().first()
                if not row:
                    continue
                found += 1
                log.warning("возврат: письмо №%s → %s: %s", row["id"], row["to_addr"], reason[:120])
                notify("\n".join([
                    f"📭 Письмо не доставлено: №{row['id']} → {row['to_addr']}",
                    f"Тема: {row['subject'] or '(без темы)'}",
                    f"Причина: {reason[:300]}",
                ]))
            if max_uid > last_uid:
                with core_engine.begin() as conn:
                    conn.execute(sql_text(
                        "INSERT INTO core.platform_setting (key, value) VALUES "
                        "('mail_bounce_last_uid', :v) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
                        {"v": str(max_uid)})
        finally:
            try: im.logout()
            except Exception: pass
    except Exception as e:
        # Ящик недоступен — это не повод ронять воркер: письма всё равно уходят.
        log.warning("возвраты: ящик недоступен (%s): %s", host, e)
        return 0
    return found


def imap_cfg_from_smtp(smtp_cfg: dict, overrides: dict | None = None) -> dict:
    """IMAP-настройки по SMTP: у почтовых хостингов это один и тот же сервер.

    Явные значения (platform_setting mail_imap_host / mail_imap_port) главнее —
    у кого-то IMAP живёт на отдельном хосте.
    """
    o = overrides or {}
    return {
        "host": (o.get("host") or (smtp_cfg or {}).get("host") or "").strip(),
        "port": o.get("port") or 993,
        "username": (smtp_cfg or {}).get("username"),
        "password": (smtp_cfg or {}).get("password"),
    }
