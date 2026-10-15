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
  D — трек писем: раз в минуту ищет застрявшие в core.mail_queue и разбирает
              возвраты из почтового ящика отправителя; тревожит super_admin
              в Telegram (см. mail_watch.py).

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

import requests

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Singleton SQLAlchemy — тот же объект, что в app.py (модели импортятся ниже).
import sys
sys.path.insert(0, os.path.dirname(__file__))

import app as backend_app  # noqa: E402  — ре-юзаем Flask app + db из backend
from models import (  # noqa: E402
    Channel, TelegramGroup, TelegramTopic, TopicRegistration,
    Message, PollState,
)

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
import mail_watch  # noqa: E402  — сторож застрявших писем и разбор возвратов

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
TEST_EVENT_MAX_ATTEMPTS = 1     # для test-каналов (_test.*) — одна попытка
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
    ch = Channel.query.get(m.channel_id) if m.channel_id else None
    if ch is None:
        raise RuntimeError("channel пуст — нечем отправлять")
    cfg = ch.config or {}

    if ch.kind == "email":
        send_email(
            to_addr=m.to_address,
            subject=m.subject or "(без темы)",
            body_text=m.body_text or "",
            body_html=m.body_html,
            smtp_cfg=cfg,
        )

    elif ch.kind == "telegram":
        bot_token = cfg.get("bot_token")
        if not bot_token:
            raise RuntimeError("bot_token не задан в channel.config")
        try:
            chat_id = int(m.to_address)
        except (TypeError, ValueError):
            chat_id = m.to_address
        if not _rl.try_send(ch.id, int(chat_id) if isinstance(chat_id, int) else 0):
            raise RuntimeError("rate_limited")  # worker оставит pending → ретрай
        # message_thread_id берётся из payload (положили в routing/deliver)
        thread_id = (m.payload or {}).get("message_thread_id")
        res = tg_send(bot_token, chat_id, m.body_text or "",
                      message_thread_id=thread_id)
        # сохраним telegram_message_id в payload для будущей reply-связки
        m.payload = {**(m.payload or {}), "telegram_message_id": res.get("message_id")}
    else:
        raise RuntimeError(f"неизвестный kind={ch.kind!r}")


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
            ch = Channel.query.get(m.channel_id) if m.channel_id else None
            if m.event_type in ("_test.email", "_test.telegram") and ch is not None:
                ch.last_test_at = datetime.utcnow()
                ch.last_test_ok = True
                ch.last_test_error = None
            db.session.commit()
            log.info("sent message id=%s to=%s kind=%s", m.id, m.to_address,
                     ch.kind if ch else "?")
        except Exception as e:
            err = str(e)
            m.attempts = (m.attempts or 0) + 1
            m.last_error = err
            # Для test-событий (_test.email / _test.telegram) — failed сразу
            # после первой попытки. Пользователь жмёт «Отправить тест» и ждёт
            # ответ в течение секунд — нет смысла ретраить 5 раз, каждый
            # упрётся в тот же TLS-timeout 30s; в сумме «отправка» висит ~3
            # минуты вместо мгновенного фидбэка.
            max_attempts = (TEST_EVENT_MAX_ATTEMPTS
                            if m.event_type and m.event_type.startswith("_test.")
                            else MAX_ATTEMPTS)
            if err == "rate_limited":
                # просто откатываем в pending — без увеличения attempts
                m.attempts = max(0, (m.attempts or 0) - 1)
                m.status = "pending"
            elif m.attempts >= max_attempts:
                m.status = "failed"
            else:
                m.status = "pending"
            ch = Channel.query.get(m.channel_id) if m.channel_id else None
            if (m.event_type in ("_test.email", "_test.telegram")
                    and ch is not None and m.status == "failed"):
                ch.last_test_at = datetime.utcnow()
                ch.last_test_ok = False
                ch.last_test_error = err
            db.session.commit()
            log.warning("send failed id=%s attempts=%s err=%s", m.id, m.attempts, err)


def _core_smtp_cfg() -> dict | None:
    """SMTP-конфиг системных писем из core.mail_settings (pg-core).

    Source of truth перенесён в core (модуль mailer архивирован, его админ-UI
    недоступен; системный SMTP редактируется в /admin/notifications → core).
    Возвращает smtp_cfg-совместимый dict или None, если в core не настроено —
    тогда fallback на legacy system-канал из pg-mailer.
    """
    if _core_engine is None:
        return None
    from sqlalchemy import text as sql_text
    try:
        with _core_engine.connect() as conn:
            row = conn.execute(sql_text(
                "SELECT server, port, use_tls, username, password, sender_name, is_enabled "
                "FROM core.mail_settings ORDER BY id LIMIT 1")).mappings().first()
    except Exception as e:
        log.warning("core.mail_settings read failed: %s", e)
        return None
    if not row or not row["is_enabled"] or not row["server"] or not row["password"]:
        return None
    return {
        "host": row["server"], "port": row["port"] or 587,
        "use_tls": bool(row["use_tls"]),
        "username": row["username"] or "", "password": row["password"],
        "sender_name": row["sender_name"] or "",
        "sender_email": row["username"] or "",
    }


def _process_legacy_mail_queue() -> None:
    """Bridge для core.mail_queue (заменяет notify-service).

    Берёт по 20 pending. SMTP-конфиг: приоритет — core.mail_settings
    (редактируется в /admin/notifications, source of truth в core);
    fallback — legacy system-канал из pg-mailer (company_id IS NULL),
    затем любой включённый.

    Параллельно создаёт mailer.message запись для каждой попытки — чтобы
    письма были видны в /admin/notifications (раньше там были только
    письма, отправленные через mailer-API напрямую).
    """
    if _core_engine is None:
        return
    core_cfg = _core_smtp_cfg()
    # Системный канал (company_id IS NULL) — для журнала-mirror и как fallback.
    default_ch = (Channel.query
                  .filter(Channel.kind == "email", Channel.is_enabled.is_(True),
                          Channel.company_id.is_(None))
                  .order_by(Channel.id.asc()).first())
    if default_ch is None:
        default_ch = (Channel.query
                      .filter(Channel.kind == "email", Channel.is_enabled.is_(True))
                      .order_by(Channel.id.asc()).first())
    if core_cfg is None and default_ch is None:
        return  # некуда слать — старые письма ждут настройки SMTP

    smtp_cfg = core_cfg or (default_ch.config or {})
    from sqlalchemy import text as sql_text
    with _core_engine.begin() as conn:
        # Только pending, у которых last_attempt_at NULL или старше 60с —
        # чтобы не молотить SMTP при перманентной ошибке (DNS, креды).
        rows = conn.execute(sql_text(
            "SELECT id, to_addr, subject, body, body_html FROM core.mail_queue "
            "WHERE status='pending' "
            "  AND (last_attempt_at IS NULL OR last_attempt_at < NOW() - INTERVAL '60 seconds') "
            "ORDER BY created_at ASC LIMIT 20 FOR UPDATE SKIP LOCKED"
        )).mappings().all()
        for row in rows:
            # Mirror в mailer.message для /admin/notifications. status='sending'
            # до фактической попытки → 'sent' / 'failed' после.
            from models import Message  # локальный import — модель только здесь нужна
            mirror = Message(
                company_id=None,
                channel_id=default_ch.id if default_ch else None,
                source_module="core.mail_queue",
                event_type="legacy.bridge",
                payload={"core_mail_queue_id": row["id"]},
                to_address=row["to_addr"],
                subject=row["subject"] or "(без темы)",
                body_text=row["body"] or "",
                status="sending", attempts=1,
            )
            db.session.add(mirror)
            db.session.commit()
            try:
                trace = send_email(
                    to_addr=row["to_addr"],
                    subject=row["subject"] or "(без темы)",
                    body_text=row["body"] or "",
                    body_html=row.get("body_html"),
                    smtp_cfg=smtp_cfg,
                )
                # Записываем след: по Message-ID к письму привяжется возврат,
                # по квитанции релея его найдёт поддержка хостера.
                conn.execute(sql_text(
                    "UPDATE core.mail_queue SET status='sent', last_attempt_at=NOW(), "
                    "  sent_at=NOW(), message_id=:mid, relay_receipt=:rcpt "
                    "WHERE id=:i"),
                    {"i": row["id"], "mid": (trace or {}).get("message_id"),
                     "rcpt": (trace or {}).get("receipt")})
                mirror.status = "sent"
                mirror.sent_at = datetime.utcnow()
                db.session.commit()
                log.info("legacy mail_queue id=%s sent to=%s", row["id"], row["to_addr"])
            except SMTPError as e:
                conn.execute(sql_text(
                    "UPDATE core.mail_queue SET last_attempt_at=NOW(), error_text=:e WHERE id=:i"),
                    {"e": str(e)[:500], "i": row["id"]})
                mirror.status = "failed"
                mirror.last_error = str(e)[:1000]
                db.session.commit()
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


# Как часто смотрим за судьбой писем: раз в минуту хватает — сторож считает
# застрявшими те, что висят дольше 10 минут, а возвраты приходят не чаще.
MAILWATCH_INTERVAL = 60


def _system_bot_token() -> str | None:
    """Токен системного бота: тревоги шлём им, а не ботом компании."""
    ch = (Channel.query
          .filter(Channel.kind == "telegram", Channel.is_enabled.is_(True),
                  Channel.company_id.is_(None))
          .order_by(Channel.id.asc()).first())
    return ((ch.config or {}).get("bot_token") if ch else None) or None


def _imap_overrides() -> dict:
    """Явные настройки IMAP из platform_setting, если хостер держит его отдельно."""
    if _core_engine is None:
        return {}
    from sqlalchemy import text as sql_text
    try:
        with _core_engine.connect() as conn:
            rows = conn.execute(sql_text(
                "SELECT key, value FROM core.platform_setting "
                "WHERE key IN ('mail_imap_host','mail_imap_port')")).mappings().all()
    except Exception:
        return {}
    out = {}
    for r in rows:
        if r["key"] == "mail_imap_host" and (r["value"] or "").strip():
            out["host"] = r["value"].strip()
        if r["key"] == "mail_imap_port" and str(r["value"] or "").strip().isdigit():
            out["port"] = int(r["value"])
    return out


def thread_d_mailwatch():
    """Трек писем: застрявшие в очереди и вернувшиеся от чужих серверов.

    Отдельный поток, а не довесок к outbox: разбор ящика ходит по IMAP и может
    висеть на таймауте, а отправка писем из-за этого останавливаться не должна.
    """
    log.info("thread D (mailwatch) started")
    while not _shutdown.is_set():
        with app.app_context():
            try:
                token = _system_bot_token()

                def notify(text: str) -> None:
                    mail_watch.alert_admins(_core_engine, tg_send, token, text)

                mail_watch.check_stuck(_core_engine, notify)
                smtp_cfg = _core_smtp_cfg() or {}
                if smtp_cfg:
                    mail_watch.poll_bounces(
                        _core_engine,
                        mail_watch.imap_cfg_from_smtp(smtp_cfg, _imap_overrides()),
                        notify)
            except Exception as e:
                log.exception("mailwatch loop error: %s", e)
        _shutdown.wait(MAILWATCH_INTERVAL)


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


def _dm_with_log(ch: Channel, bot_token: str, chat_id, text: str,
                 *, event_type: str, source_module: str = "auth",
                 reply_markup=None) -> bool:
    """Отправить TG-сообщение + записать в Message-журнал.

    Пишем запись ДО fact-of-send, чтобы при сбое осталась строка с
    status='failed' + last_error — иначе админ в /admin/notifications
    не увидит что бот пытался отправить и почему упало. Возвращает
    True/False по успешности (только informational — caller обычно
    игнорирует).
    """
    m = Message(
        company_id=None, channel_id=ch.id,
        source_module=source_module, event_type=event_type,
        payload={"chat_id": int(chat_id)},
        to_address=str(chat_id), subject=None, body_text=text,
        status="sending", attempts=1,
    )
    db.session.add(m)
    db.session.commit()
    try:
        tg_send(bot_token, chat_id, text=text, reply_markup=reply_markup)
        m.status = "sent"
        m.sent_at = datetime.utcnow()
        db.session.commit()
        return True
    except TelegramError as e:
        log.error("tg send (event=%s) failed chat=%s: %s", event_type, chat_id, e)
        m.status = "failed"
        m.last_error = str(e)[:1000]
        db.session.commit()
        return False


def _reply_magic_link(ch: Channel, bot_token: str, chat_id, resp: dict,
                      *, event_type: str, header: str, intro: str) -> None:
    """Унифицированный шаблон ответа бота с magic-link (header + intro +
    <code>token</code> + inline-кнопка URL). Используется в обоих flows
    (Quick login и First-time link)."""
    code = resp.get("magic_code") or ""
    magic_url = resp.get("magic_url") or ""
    text_body = (
        f"{header}\n\n"
        f"{intro}\n\n"
        f"<i>Код для ручного входа (нажмите, чтобы выделить):</i>\n"
        f"<code>{code}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Действует <b>15 минут</b>\n"
        f"🛡 Если вы не запрашивали вход — просто проигнорируйте это сообщение."
    )
    _dm_with_log(
        ch, bot_token, chat_id,
        text=text_body,
        event_type=event_type,
        reply_markup={
            "inline_keyboard": [[
                {"text": "🔗 Войти в портал", "url": magic_url}
            ]]
        },
    )


def _greeting_for(resp: dict) -> str:
    """Из ответа core возьмём first-name для персонального обращения."""
    name_full = (resp.get("employee_name") or "").strip()
    first_name = name_full.split()[0] if name_full else ""
    return f", {first_name}" if first_name else ""


def _handle_private_dm(ch: Channel, msg: dict, chat: dict) -> None:
    """Системный бот в личке. Два потока, оба без contact-share:

      A) /start (без payload) или /start login — Quick login. Лукап по
         tg_user_id в core. Если найдена EmployeeTelegram-привязка —
         выдаём magic-link сразу.

      B) /start link_<email_token> — первичная привязка. Сразу зовём
         core /telegram/email-link с tg_user_id отправителя + token.
         Core валидирует token, создаёт EmployeeTelegram, минтит
         magic-link. Бот показывает inline-кнопку «Войти в портал».

      Никаких contact-share, request_contact или phone-сверки —
      email-токен из персонального письма сам по себе анкор владения.
      Прочие сообщения молча игнорируем.
    """
    from_user = msg.get("from") or {}
    text = (msg.get("text") or "").strip()
    bot_token = (ch.config or {}).get("bot_token")
    if not bot_token:
        return
    core_url = os.environ.get("CORE_REGISTRY_URL", "http://core-registry:5001")
    tg_user_id = from_user.get("id")

    if not (text == "/start" or text.startswith("/start ")):
        # Контакт-сообщения и прочее в этом потоке не нужны —
        # игнорируем, не сбивая юзера с толку.
        return

    payload = text[7:].strip() if text.startswith("/start ") else ""

    # ── Flow B: первичная привязка по email-токену ──────────────
    if payload.startswith("link_"):
        token = payload[5:].strip()
        if not token or not tg_user_id:
            _dm_with_log(ch, bot_token, chat["id"],
                          text="❌ Ссылка из письма некорректна. Запросите новое письмо.",
                          event_type="auth.link_no_token")
            return
        try:
            r = requests.post(
                f"{core_url}/telegram/email-link",
                json={"email_token": token,
                      "tg_user_id": tg_user_id,
                      "tg_username": from_user.get("username"),
                      "tg_chat_id": chat.get("id")},
                timeout=10,
            )
            resp = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception as e:
            log.error("email-link call failed: %s", e)
            _dm_with_log(ch, bot_token, chat["id"],
                          text="⚠ Временная ошибка. Попробуйте через минуту.",
                          event_type="auth.email_link_error")
            return

        if resp.get("ok"):
            if resp.get("was_activated"):
                header = f"🎉 <b>Добро пожаловать в CORPER{_greeting_for(resp)}!</b>"
                intro = ("Telegram привязан к вашей учётной записи.\n"
                          "Нажмите кнопку ниже, чтобы войти в портал.")
                event_type = "auth.welcome_magic_link"
            else:
                header = f"🔐 <b>Вход в портал{_greeting_for(resp)}</b>"
                intro = "Ваша одноразовая ссылка для входа готова."
                event_type = "auth.magic_link"
            _reply_magic_link(ch, bot_token, chat["id"], resp,
                              event_type=event_type, header=header, intro=intro)
            return

        err = resp.get("error") or "unknown"
        human = {
            "token_invalid": "❌ Ссылка из письма не найдена или уже использована. Запросите новое письмо.",
            "token_expired": "❌ Ссылка из письма просрочена (48 часов). Запросите новое письмо.",
            "tg_already_linked": "❌ Этот Telegram-аккаунт уже привязан к другому сотруднику. Обратитесь к админу.",
            "employee_missing": "❌ Учётная запись не найдена.",
        }.get(err, f"❌ Ошибка: {err}")
        _dm_with_log(ch, bot_token, chat["id"], text=human,
                      event_type=f"auth.email_link_error.{err}")
        return

    # ── Flow A: Quick login (без payload или /start login) ──────
    try:
        r = requests.post(
            f"{core_url}/telegram/quick-login",
            json={"tg_user_id": tg_user_id,
                  "tg_username": from_user.get("username"),
                  "tg_chat_id": chat.get("id")},
            timeout=10,
        )
        resp = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:
        log.error("quick-login call failed: %s", e)
        _dm_with_log(ch, bot_token, chat["id"],
                      text="⚠ Временная ошибка. Попробуйте позже.",
                      event_type="auth.quick_login_error")
        return

    if resp.get("ok"):
        _reply_magic_link(ch, bot_token, chat["id"], resp,
                          event_type="auth.quick_login",
                          header=f"🔐 <b>Вход в портал{_greeting_for(resp)}</b>",
                          intro="Ваша одноразовая ссылка для входа готова.")
        return

    err = resp.get("error") or "unknown"
    human = {
        "not_linked": ("👋 <b>Здравствуйте!</b>\n\n"
                        "Я ещё не знаю вашу учётную запись. Чтобы войти "
                        "в первый раз — запросите письмо со ссылкой на "
                        "странице входа портала, затем откройте ссылку из "
                        "письма."),
        "employee_inactive": "❌ Учётная запись отключена. Свяжитесь с администратором компании.",
    }.get(err, f"❌ Ошибка: {err}")
    _dm_with_log(ch, bot_token, chat["id"], text=human,
                  event_type=f"auth.quick_login_error.{err}")


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
    if chat_id is None:
        return
    # ── Private (DM с ботом) — TG-регистрация портала ─────────────────
    # Только для system-канала (ch.company_id IS NULL): /start приветствие
    # + request_contact keyboard, contact-share → POST в core-registry для
    # привязки tg_user_id ↔ Employee и magic-link для входа в портал.
    if chat.get("type") == "private":
        if ch.company_id is not None:
            return  # company-боты пока не обслуживают регистрацию
        _handle_private_dm(ch, msg, chat)
        return

    from_user = msg.get("from") or {}
    text = msg.get("text") or msg.get("caption")
    thread_id = msg.get("message_thread_id")   # есть только в форум-топиках

    # ── Seed-фраза: матчим pending TopicRegistration ─────────────────────
    # Дуальный режим — одна таблица обслуживает оба сценария:
    #   • group_id IS NULL  → пользователь хочет привязать ГРУППУ через фразу.
    #     Фраза вставляется в любое сообщение чата → создаём TelegramGroup
    #     с chat_id из сообщения, name из p.name или msg.chat.title.
    #   • group_id IS NOT NULL → пользователь хочет привязать ТОПИК внутри
    #     этой группы. Фраза должна прийти в форум-топике (thread_id != None).
    if text:
        # сначала пробуем group-registration (без привязки к существующей группе)
        if not thread_id:
            pending_g = (TopicRegistration.query
                         .filter(TopicRegistration.consumed_at.is_(None),
                                 TopicRegistration.expires_at > datetime.utcnow(),
                                 TopicRegistration.company_id == ch.company_id,
                                 TopicRegistration.group_id.is_(None))
                         .all())
            for p in pending_g:
                if p.phrase and p.phrase in text:
                    g = TelegramGroup.query.filter_by(
                        company_id=ch.company_id, chat_id=int(chat_id)).first()
                    chat_title = chat.get("title") or chat.get("username") or ""
                    if g is None:
                        g = TelegramGroup(
                            company_id=ch.company_id, channel_id=ch.id,
                            chat_id=int(chat_id),
                            title=p.name or chat_title or f"Чат {chat_id}",
                            chat_type=chat.get("type") or "group",
                            is_member=True, can_send=True,
                            last_seen_at=datetime.utcnow(),
                        )
                        db.session.add(g)
                        db.session.flush()
                    else:
                        if g.archived_at:
                            g.archived_at = None
                        if p.name:
                            g.title = p.name
                        g.last_seen_at = datetime.utcnow()
                    p.consumed_at = datetime.utcnow()
                    p.group_id = g.id  # сохраним результат для UI-поллинга
                    db.session.commit()
                    try:
                        cfg = ch.config or {}
                        if cfg.get("bot_token"):
                            tg_send(cfg["bot_token"], chat_id,
                                    f"Группа «{g.title}» закреплена за рассылками CORPER.")
                    except Exception as e:
                        log.warning("seed-confirm group send failed: %s", e)
                    log.info("group registered via seed: chat=%s name=%s",
                             chat_id, g.title)
                    break

        # затем — topic-registration в форум-топике
        if thread_id:
            group = TelegramGroup.query.filter_by(
                company_id=ch.company_id, chat_id=int(chat_id)).first()
            if group is not None:
                if not group.is_forum:
                    group.is_forum = True
                pending_list = (TopicRegistration.query
                                .filter(TopicRegistration.consumed_at.is_(None),
                                        TopicRegistration.expires_at > datetime.utcnow(),
                                        TopicRegistration.group_id == group.id)
                                .all())
                for p in pending_list:
                    if p.phrase and p.phrase in text:
                        topic = (TelegramTopic.query
                                 .filter_by(group_id=group.id,
                                            telegram_thread_id=int(thread_id))
                                 .first())
                        if topic is None:
                            topic = TelegramTopic(
                                company_id=ch.company_id, group_id=group.id,
                                telegram_thread_id=int(thread_id),
                                name=p.name or f"Топик #{thread_id}",
                            )
                            db.session.add(topic)
                            db.session.flush()
                        else:
                            if p.name:
                                topic.name = p.name
                            if topic.archived_at:
                                topic.archived_at = None
                        p.consumed_at = datetime.utcnow()
                        p.topic_id = topic.id
                        db.session.commit()
                        try:
                            cfg = ch.config or {}
                            if cfg.get("bot_token"):
                                tg_send(cfg["bot_token"], chat_id,
                                        f"Топик «{topic.name}» закреплён за рассылками CORPER.",
                                        message_thread_id=int(thread_id))
                        except Exception as e:
                            log.warning("seed-confirm send failed: %s", e)
                        log.info("topic registered: group=%s thread=%s name=%s",
                                 group.id, thread_id, topic.name)
                        break

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


# ── Платформенная очередь Telegram для модулей ─────────────────────────────
#
# Бот у портала один, и опрашивать его можно только отсюда: getUpdates забирает
# обновление навсегда, второй поллер начал бы красть сообщения. Поэтому всё,
# что пришло, складываем в core.tg_update — а модули читают очередь со своим
# курсором и отвечают через платформенный бот (API в ядре).
#
# Пишем прямо в pg-core тем же engine, что и legacy-мост core.mail_queue:
# заводить ради этого отдельный токен и HTTP-вызов незачем.

def _core_tg_cfg() -> dict:
    """Параметры опроса из core.platform_setting (их правит админка бота)."""
    cfg = {"enabled": True, "timeout": POLL_TIMEOUT_SEC,
           "allowed": ["message", "my_chat_member", "channel_post"]}
    if _core_engine is None:
        return cfg
    from sqlalchemy import text as sql_text
    try:
        with _core_engine.connect() as conn:
            rows = conn.execute(sql_text(
                "SELECT key, value FROM core.platform_setting "
                "WHERE key IN ('tg_poll_enabled','tg_poll_timeout','tg_poll_allowed')"
            )).all()
    except Exception as e:
        log.warning("core: параметры опроса недоступны: %s", e)
        return cfg
    got = {k: (v or "") for k, v in rows}
    if "tg_poll_enabled" in got:
        cfg["enabled"] = got["tg_poll_enabled"] != "false"
    if got.get("tg_poll_timeout", "").isdigit():
        cfg["timeout"] = max(0, min(int(got["tg_poll_timeout"]), 60))
    if got.get("tg_poll_allowed"):
        cfg["allowed"] = [x.strip() for x in got["tg_poll_allowed"].split(",") if x.strip()]
    return cfg


def _tg_flat(u: dict) -> dict:
    """Плоские поля обновления: по ним модули фильтруют, не разбирая raw."""
    msg = u.get("message") or u.get("channel_post") or {}
    chat = msg.get("chat") or ((u.get("my_chat_member") or {}).get("chat")) or {}
    frm = msg.get("from") or ((u.get("my_chat_member") or {}).get("from")) or {}
    text = (msg.get("text") or msg.get("caption") or "").strip()
    cmd = ""
    if text.startswith("/"):
        # В группе Telegram дописывает имя бота: «/connect@corper_pro_bot 12».
        cmd = text.split()[0].split("@")[0][:40]
    kind = ("my_chat_member" if "my_chat_member" in u
            else "channel_post" if "channel_post" in u else "message")
    name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) \
        or frm.get("username") or ""
    return {
        "update_id": int(u.get("update_id") or 0), "kind": kind,
        "chat_id": chat.get("id"), "chat_type": (chat.get("type") or "")[:16],
        "chat_title": (chat.get("title") or chat.get("username") or "")[:200],
        "topic_id": msg.get("message_thread_id"),
        "from_id": frm.get("id"), "from_name": name[:200],
        "text": text, "command": cmd,
    }


def _publish_to_core(updates: list) -> None:
    """Сложить пачку в очередь ядра. Дубли отсекает update_id."""
    if _core_engine is None or not updates:
        return
    import json as _json
    from sqlalchemy import text as sql_text
    try:
        with _core_engine.begin() as conn:
            for u in updates:
                row = _tg_flat(u)
                if not row["update_id"]:
                    continue
                conn.execute(sql_text(
                    "INSERT INTO core.tg_update (update_id, kind, chat_id, chat_type,"
                    " chat_title, topic_id, from_id, from_name, text, command, raw)"
                    " VALUES (:update_id, :kind, :chat_id, :chat_type, :chat_title,"
                    " :topic_id, :from_id, :from_name, :text, :command, CAST(:raw AS JSONB))"
                    " ON CONFLICT (update_id) DO NOTHING"),
                    {**row, "raw": _json.dumps(u, ensure_ascii=False)})
    except Exception as e:
        log.warning("core.tg_update: пачка не записана: %s", e)


def _poll_channel(ch: Channel) -> None:
    """Один цикл getUpdates для одного канала."""
    cfg = ch.config or {}
    bot_token = cfg.get("bot_token")
    bot_id = cfg.get("bot_id")
    if not bot_token:
        time.sleep(5)
        return
    st = _ensure_poll_state(ch.id)
    cfg = _core_tg_cfg()
    if not cfg["enabled"]:
        # Опрос выключен в админке бота: держать соединение впустую незачем.
        time.sleep(10)
        return
    try:
        updates = tg_get_updates(
            bot_token,
            offset=st.last_update_id + 1,
            timeout=cfg["timeout"],
            allowed_updates=cfg["allowed"],
        )
    except TelegramError as e:
        log.warning("getUpdates channel=%s failed: %s", ch.id, e)
        time.sleep(10)
        return

    # Сначала в общую очередь, потом разбор: если разбор упадёт, модули всё
    # равно получат сообщение — у Telegram его уже не перезапросить.
    _publish_to_core(updates)

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


def _sync_system_bot_from_core() -> None:
    """Синк токена системного бота из core.platform_setting → системный
    TG-канал в pg-mailer (company_id IS NULL).

    Source of truth перенесён в core (админка /admin/notifications пишет
    platform_setting.system_tg_bot_token). Worker подхватывает смену токена
    за один цикл поллинга: обновляет channel.config (poll/health/DM-машинерия
    остаётся на Channel/PollState без изменений).
    """
    if _core_engine is None:
        return
    from sqlalchemy import text as sql_text
    try:
        with _core_engine.connect() as conn:
            row = conn.execute(sql_text(
                "SELECT value FROM core.platform_setting "
                "WHERE key = 'system_tg_bot_token'")).first()
    except Exception as e:
        log.warning("core platform_setting read failed: %s", e)
        return
    token = (row[0] or "").strip() if row else ""
    if not token:
        return  # в core не задан — оставляем legacy-конфиг канала как есть

    ch = (Channel.query
          .filter(Channel.kind == "telegram", Channel.company_id.is_(None))
          .order_by(Channel.id.asc()).first())
    if ch is None:
        ch = Channel(company_id=None, kind="telegram", is_enabled=True,
                     label="Системный бот", config={})
        db.session.add(ch)
    cfg = dict(ch.config or {})
    if cfg.get("bot_token") == token and ch.is_enabled:
        return  # уже синхронизирован
    cfg["bot_token"] = token
    try:
        me = tg_get_me(token)
        cfg["bot_id"] = (me or {}).get("id")
        cfg["bot_username"] = (me or {}).get("username")
    except TelegramError as e:
        log.warning("system bot getMe failed on sync: %s", e)
    ch.config = cfg
    ch.is_enabled = True
    db.session.commit()
    log.info("system bot token synced from core (bot=%s)", cfg.get("bot_username"))


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
                _sync_system_bot_from_core()
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
        threading.Thread(target=thread_d_mailwatch, name="mailwatch", daemon=True),
    ]
    for t in threads:
        t.start()

    while not _shutdown.is_set():
        time.sleep(1)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
