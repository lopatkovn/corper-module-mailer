"""Mailer worker — один контейнер, три daemon-потока.

Запускается deploy-agent'ом как component=worker:
  module.json → "worker": { "context": "backend", "command": "python worker.py" }

Потоки:
  A — outbox: каждые 5с шлёт mailer.message(status=pending) + bridge для
              core.mail_queue (заменяет старый notify-service).
  B — long polling: per включённый telegram-канал, getUpdates с timeout=25,
                    обрабатывает my_chat_member (auto-discovery групп) и
                    inbound сообщения (replies + команды).
  C — health-check: раз в 10 мин getChatMember(bot) → is_member/can_send.

Env:
  DATABASE_URL          — pg-mailer (как у backend'а)
  SECRET_KEY            — для совместимости с моделями (не используется тут)
  CORE_REGISTRY_URL     — http://core-registry:5001
  CORE_DATABASE_URL     — постижение pg-core для legacy bridge (опционально;
                          если не задан, bridge не работает, лог-варнинг)
"""
import logging
import os
import signal
import threading
import time
from datetime import datetime

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Singleton SQLAlchemy — тот же объект, что в app.py (модели импортятся ниже).
import sys
sys.path.insert(0, os.path.dirname(__file__))

import app as backend_app  # noqa: E402  — ре-юзаем Flask app + db из backend
from models import Channel, TelegramGroup, Message, PollState  # noqa: E402

from corper_shared.service_client import CoreClient  # noqa: E402

from delivery_email import send_email, SMTPError  # noqa: E402
from delivery_telegram import (  # noqa: E402
    send_message as tg_send,
    get_me as tg_get_me,
    get_chat_member as tg_get_member,
    get_updates as tg_get_updates,
    TelegramError,
)
from rate_limit import BotRateLimiter  # noqa: E402

log = logging.getLogger("mailer-worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = backend_app.app
db = backend_app.db
core = CoreClient(os.environ.get("CORE_REGISTRY_URL", "http://core-registry:5001"))

_shutdown = threading.Event()
_rl = BotRateLimiter()

OUTBOX_INTERVAL = 5             # сек между циклами потока A
HEALTH_INTERVAL = 600           # 10 мин
POLL_TIMEOUT_SEC = 25           # long polling getUpdates timeout
MAX_ATTEMPTS = 5                # после стольких неудач → status=failed

# ── pg-core engine для legacy bridge ──────────────────────────────────────
_core_db_url = os.environ.get("CORE_DATABASE_URL")
_core_engine = None
if _core_db_url:
    from sqlalchemy import create_engine
    _core_engine = create_engine(_core_db_url, pool_pre_ping=True, pool_size=2)
else:
    log.warning("CORE_DATABASE_URL не задан — legacy bridge core.mail_queue выключен")


# ── Поток A: outbox ───────────────────────────────────────────────────────

def _send_one_message(m: Message) -> None:
    """Отправить одно сообщение из mailer.message. Бросает исключение при ошибке."""
    if m.channel is None:
        raise RuntimeError("channel пуст — нечем отправлять")
    cfg = m.channel.config or {}

    if m.channel.kind == "email":
        send_email(
            to_addr=m.to_address,
            subject=m.subject or "(без темы)",
            body_text=m.body_text or "",
            body_html=m.body_html,
            smtp_cfg=cfg,
        )

    elif m.channel.kind == "telegram":
        bot_token = cfg.get("bot_token")
        if not bot_token:
            raise RuntimeError("bot_token не задан в channel.config")
        try:
            chat_id = int(m.to_address)
        except (TypeError, ValueError):
            chat_id = m.to_address
        if not _rl.try_send(m.channel.id, int(chat_id) if isinstance(chat_id, int) else 0):
            raise RuntimeError("rate_limited")  # worker оставит pending → ретрай
        res = tg_send(bot_token, chat_id, m.body_text or "")
        # сохраним telegram_message_id в payload для будущей reply-связки
        m.payload = {**(m.payload or {}), "telegram_message_id": res.get("message_id")}
    else:
        raise RuntimeError(f"неизвестный kind={m.channel.kind!r}")


def _process_pending_mailer_messages() -> None:
    pending = (Message.query
               .filter(Message.status == "pending")
               .order_by(Message.created_at.asc())
               .limit(50).all())
    for m in pending:
        m.status = "sending"
        db.session.commit()
        try:
            _send_one_message(m)
            m.status = "sent"
            m.sent_at = datetime.utcnow()
            m.last_error = None
            # для test-каналов — обновим last_test_at/ok
            if m.event_type in ("_test.email", "_test.telegram") and m.channel is not None:
                m.channel.last_test_at = datetime.utcnow()
                m.channel.last_test_ok = True
                m.channel.last_test_error = None
            db.session.commit()
            log.info("sent message id=%s to=%s kind=%s", m.id, m.to_address, m.channel.kind)
        except Exception as e:
            err = str(e)
            m.attempts = (m.attempts or 0) + 1
            m.last_error = err
            if err == "rate_limited":
                # просто откатываем в pending — без увеличения attempts
                m.attempts = max(0, (m.attempts or 0) - 1)
                m.status = "pending"
            elif m.attempts >= MAX_ATTEMPTS:
                m.status = "failed"
            else:
                m.status = "pending"
            if m.event_type in ("_test.email", "_test.telegram") and m.channel is not None and m.status == "failed":
                m.channel.last_test_at = datetime.utcnow()
                m.channel.last_test_ok = False
                m.channel.last_test_error = err
            db.session.commit()
            log.warning("send failed id=%s attempts=%s err=%s", m.id, m.attempts, err)


def _process_legacy_mail_queue() -> None:
    """Bridge для core.mail_queue (заменяет notify-service).

    Берёт по 20 pending, отправляет через дефолтный SMTP-канал ПЕРВОЙ компании,
    у которой email-канал включён. Это упрощение — старые письма из mail_queue
    не привязаны к company_id, поэтому используем любой готовый канал.
    """
    if _core_engine is None:
        return
    # Найти любой включённый email-канал (для отправки legacy писем)
    default_ch = (Channel.query
                  .filter(Channel.kind == "email", Channel.is_enabled.is_(True))
                  .order_by(Channel.id.asc()).first())
    if default_ch is None:
        return  # некуда слать — старые письма ждут настройки канала

    smtp_cfg = default_ch.config or {}
    from sqlalchemy import text as sql_text
    with _core_engine.begin() as conn:
        # Только pending, у которых last_attempt_at NULL или старше 60с —
        # чтобы не молотить SMTP при перманентной ошибке (DNS, креды).
        rows = conn.execute(sql_text(
            "SELECT id, to_addr, subject, body FROM core.mail_queue "
            "WHERE status='pending' "
            "  AND (last_attempt_at IS NULL OR last_attempt_at < NOW() - INTERVAL '60 seconds') "
            "ORDER BY created_at ASC LIMIT 20 FOR UPDATE SKIP LOCKED"
        )).mappings().all()
        for row in rows:
            try:
                send_email(
                    to_addr=row["to_addr"],
                    subject=row["subject"] or "(без темы)",
                    body_text=row["body"] or "",
                    body_html=None,
                    smtp_cfg=smtp_cfg,
                )
                conn.execute(sql_text(
                    "UPDATE core.mail_queue SET status='sent', last_attempt_at=NOW() "
                    "WHERE id=:i"), {"i": row["id"]})
                log.info("legacy mail_queue id=%s sent to=%s", row["id"], row["to_addr"])
            except SMTPError as e:
                # Оставляем pending — будет ретрай через 60с. Только last_attempt_at
                # и error_text. (notify-service вёл себя так же: бесконечный ретрай.)
                conn.execute(sql_text(
                    "UPDATE core.mail_queue SET last_attempt_at=NOW(), error_text=:e WHERE id=:i"),
                    {"e": str(e)[:500], "i": row["id"]})
                log.warning("legacy mail_queue id=%s pending-retry err=%s", row["id"], e)


def thread_a_outbox():
    log.info("thread A (outbox) started")
    while not _shutdown.is_set():
        with app.app_context():
            try:
                _process_pending_mailer_messages()
                _process_legacy_mail_queue()
            except Exception as e:
                log.exception("outbox cycle error: %s", e)
        _shutdown.wait(OUTBOX_INTERVAL)


# ── Поток C: health-check ─────────────────────────────────────────────────

def _check_telegram_group(g: TelegramGroup, ch_cfg: dict, bot_id: int) -> None:
    try:
        bot_token = ch_cfg.get("bot_token")
        info = tg_get_member(bot_token, g.chat_id, bot_id)
        status = (info or {}).get("status") or ""
        g.is_member = status in ("creator", "administrator", "member")
        g.can_send = status in ("creator", "administrator") or (
            status == "member" and (info.get("can_send_messages") is not False)
        )
        g.last_seen_at = datetime.utcnow()
    except TelegramError as e:
        g.is_member = False
        g.can_send = False
        g.last_seen_at = datetime.utcnow()
        log.warning("group health-check chat_id=%s failed: %s", g.chat_id, e)


def thread_c_health():
    log.info("thread C (health-check) started")
    # первый запуск — сразу, потом раз в HEALTH_INTERVAL
    while not _shutdown.is_set():
        with app.app_context():
            try:
                channels = Channel.query.filter(
                    Channel.kind == "telegram",
                    Channel.is_enabled.is_(True),
                ).all()
                for ch in channels:
                    cfg = ch.config or {}
                    bot_id = cfg.get("bot_id")
                    if not bot_id or not cfg.get("bot_token"):
                        continue
                    groups = TelegramGroup.query.filter_by(
                        company_id=ch.company_id, channel_id=ch.id).all()
                    for g in groups:
                        _check_telegram_group(g, cfg, int(bot_id))
                    db.session.commit()
            except Exception as e:
                log.exception("health-check error: %s", e)
        _shutdown.wait(HEALTH_INTERVAL)


# ── Поток B: long polling ─────────────────────────────────────────────────

def _ensure_poll_state(channel_id: int) -> PollState:
    st = PollState.query.filter_by(channel_id=channel_id).first()
    if st is None:
        st = PollState(channel_id=channel_id, last_update_id=0)
        db.session.add(st)
        db.session.commit()
    return st


def _handle_update(ch: Channel, update: dict, bot_id: int) -> None:
    from models import InboundMessage  # локальный import — модель здесь нужна

    # my_chat_member — бот добавлен / удалён из группы
    if "my_chat_member" in update:
        ev = update["my_chat_member"]
        chat = ev.get("chat") or {}
        chat_id = chat.get("id")
        chat_type = chat.get("type") or "group"
        title = chat.get("title") or chat.get("username") or ""
        new_status = ((ev.get("new_chat_member") or {}).get("status")) or ""
        is_member = new_status in ("creator", "administrator", "member")
        if chat_id is None or chat_type == "private":
            return
        g = TelegramGroup.query.filter_by(
            company_id=ch.company_id, chat_id=int(chat_id)).first()
        if g is None and is_member:
            g = TelegramGroup(
                company_id=ch.company_id, channel_id=ch.id,
                chat_id=int(chat_id), title=title, chat_type=chat_type,
                is_member=True, can_send=True,
                last_seen_at=datetime.utcnow(),
            )
            db.session.add(g)
            log.info("auto-registered telegram group chat_id=%s title=%s", chat_id, title)
        elif g is not None:
            g.is_member = is_member
            g.can_send = is_member
            g.title = title or g.title
            g.last_seen_at = datetime.utcnow()
        db.session.commit()
        return

    # обычное сообщение
    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None or chat.get("type") == "private":
        # личные сообщения — пишем как inbound, но без company-привязки если нет группы;
        # пока что игнорируем (фаза 6 — команды и DM-сценарии)
        return

    from_user = msg.get("from") or {}
    text = msg.get("text") or msg.get("caption")

    # reply-match
    reply_to_internal = None
    reply_to_tg_msg_id = None
    if "reply_to_message" in msg:
        reply_to_tg_msg_id = (msg["reply_to_message"] or {}).get("message_id")
        if reply_to_tg_msg_id is not None:
            orig = (Message.query
                    .filter(Message.channel_id == ch.id,
                            Message.to_address == str(chat_id))
                    .order_by(Message.created_at.desc()).limit(50).all())
            for m in orig:
                if (m.payload or {}).get("telegram_message_id") == reply_to_tg_msg_id:
                    reply_to_internal = m.id
                    break

    inbound = InboundMessage(
        company_id=ch.company_id, channel_id=ch.id,
        chat_id=int(chat_id),
        from_user_id=from_user.get("id"),
        from_username=from_user.get("username"),
        text=text,
        telegram_message_id=msg.get("message_id"),
        telegram_update_id=update.get("update_id"),
        reply_to_telegram_message_id=reply_to_tg_msg_id,
        reply_to_message_id=reply_to_internal,
        raw=update,
    )
    db.session.add(inbound)

    # простые команды /start /status — отвечаем приветствием/статусом
    if text and text.strip().startswith("/"):
        cmd = text.strip().split()[0].lower().split("@")[0]
        cfg = ch.config or {}
        bot_token = cfg.get("bot_token")
        try:
            if cmd == "/start":
                tg_send(bot_token, chat_id,
                        "Бот рассылок CORPER подключён. Группа будет автоматически "
                        "зарегистрирована, привяжите её к филиалу в /org/notifications.")
            elif cmd == "/status":
                g = TelegramGroup.query.filter_by(
                    company_id=ch.company_id, chat_id=int(chat_id)).first()
                bid = g.branch_id if g else None
                tg_send(bot_token, chat_id,
                        f"Статус: chat_id=<code>{chat_id}</code>, "
                        f"филиал={'не назначен' if not bid else bid}")
        except TelegramError as e:
            log.warning("команда %s failed: %s", cmd, e)

    db.session.commit()


def _poll_channel(ch: Channel) -> None:
    """Один цикл getUpdates для одного канала."""
    cfg = ch.config or {}
    bot_token = cfg.get("bot_token")
    bot_id = cfg.get("bot_id")
    if not bot_token:
        time.sleep(5)
        return
    st = _ensure_poll_state(ch.id)
    try:
        updates = tg_get_updates(
            bot_token,
            offset=st.last_update_id + 1,
            timeout=POLL_TIMEOUT_SEC,
            allowed_updates=["message", "my_chat_member", "channel_post"],
        )
    except TelegramError as e:
        log.warning("getUpdates channel=%s failed: %s", ch.id, e)
        time.sleep(10)
        return

    max_uid = st.last_update_id
    for u in updates:
        try:
            _handle_update(ch, u, int(bot_id) if bot_id else 0)
        except Exception as e:
            log.exception("handle_update failed: %s", e)
        max_uid = max(max_uid, int(u.get("update_id") or 0))
    if max_uid > st.last_update_id:
        st.last_update_id = max_uid
        st.last_polled_at = datetime.utcnow()
        db.session.commit()


def thread_b_polling():
    """Один поток крутит ВСЕ включённые telegram-каналы по очереди.

    Если каналов больше одного — round-robin с timeout=25с делает суммарную
    задержку приемлемой (≤25с per канал). Для масштаба >5 ботов завести
    отдельный поток на канал.
    """
    log.info("thread B (polling) started")
    while not _shutdown.is_set():
        with app.app_context():
            try:
                channels = Channel.query.filter(
                    Channel.kind == "telegram",
                    Channel.is_enabled.is_(True),
                ).all()
                if not channels:
                    _shutdown.wait(30)
                    continue
                for ch in channels:
                    if _shutdown.is_set():
                        break
                    cfg = ch.config or {}
                    if not cfg.get("bot_token"):
                        continue
                    _poll_channel(ch)
            except Exception as e:
                log.exception("polling cycle error: %s", e)
                _shutdown.wait(5)


# ── main ──────────────────────────────────────────────────────────────────

def _handle_sigterm(signum, frame):
    log.info("got signal %s, shutting down…", signum)
    _shutdown.set()


def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    threads = [
        threading.Thread(target=thread_a_outbox, name="outbox", daemon=True),
        threading.Thread(target=thread_b_polling, name="polling", daemon=True),
        threading.Thread(target=thread_c_health, name="health", daemon=True),
    ]
    for t in threads:
        t.start()

    while not _shutdown.is_set():
        time.sleep(1)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
