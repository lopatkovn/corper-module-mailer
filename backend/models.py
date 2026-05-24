"""Database models for the 'mailer' module.

Lives in dedicated schema 'mailer' (configured via module.json, DATABASE_URL search_path).

Phase 1 schema — 7 таблиц по INSTRUCTIONS.md §4.1.
Все таблицы scoped по company_id (мультикомпанийность).
"""
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB

from app import db


# ── channel ────────────────────────────────────────────────────────────────
class Channel(db.Model):
    """Канал доставки компании (email-SMTP или telegram-bot).

    Phase 1: credentials лежат в `config` JSONB (plaintext). Будущая фаза —
    вынести секреты в `core.module_secret` через `secret_ref`.
    """
    __tablename__ = "channel"

    id          = db.Column(db.Integer, primary_key=True)
    company_id  = db.Column(db.Integer, nullable=True, index=True)
    kind        = db.Column(db.String(20), nullable=False)   # 'email' | 'telegram'
    is_enabled  = db.Column(db.Boolean, nullable=False, default=False)
    label       = db.Column(db.String(120), nullable=False, default="")
    config      = db.Column(JSONB, nullable=False, default=dict)
    secret_ref  = db.Column(db.String(120), nullable=True)   # → core.module_secret.key (TODO)
    last_test_at    = db.Column(db.DateTime, nullable=True)
    last_test_ok    = db.Column(db.Boolean, nullable=True)
    last_test_error = db.Column(db.Text, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow,
                            onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("company_id", "kind", name="uq_channel_company_kind"),
    )


# ── telegram_group ─────────────────────────────────────────────────────────
class TelegramGroup(db.Model):
    """Реестр Telegram-групп компании со статусом бота."""
    __tablename__ = "telegram_group"

    id          = db.Column(db.Integer, primary_key=True)
    company_id  = db.Column(db.Integer, nullable=True, index=True)
    channel_id  = db.Column(db.Integer, db.ForeignKey("channel.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    chat_id     = db.Column(db.BigInteger, nullable=False)
    title       = db.Column(db.String(255), nullable=False, default="")
    chat_type   = db.Column(db.String(20), nullable=False, default="group")  # group|supergroup|channel|forum
    is_forum    = db.Column(db.Boolean, nullable=False, default=False)  # форум-чат поддерживает топики
    branch_id   = db.Column(db.Integer, nullable=True, index=True)
    department_id = db.Column(db.Integer, nullable=True, index=True)  # soft-FK на core.department.id (cross-schema)
    is_member   = db.Column(db.Boolean, nullable=False, default=False)
    can_send    = db.Column(db.Boolean, nullable=False, default=False)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    added_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)  # soft-archive (toggle OFF в Структуре)

    __table_args__ = (
        db.UniqueConstraint("company_id", "chat_id", name="uq_telegram_group_company_chat"),
    )


# ── telegram_topic ─────────────────────────────────────────────────────────
class TelegramTopic(db.Model):
    """Зарегистрированный форум-топик в Telegram-группе."""
    __tablename__ = "telegram_topic"

    id                 = db.Column(db.Integer, primary_key=True)
    company_id  = db.Column(db.Integer, nullable=True, index=True)
    group_id           = db.Column(db.Integer, db.ForeignKey("telegram_group.id", ondelete="CASCADE"),
                                   nullable=False, index=True)
    telegram_thread_id = db.Column(db.BigInteger, nullable=False)
    name               = db.Column(db.String(255), nullable=False, default="")
    registered_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    archived_at        = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("group_id", "telegram_thread_id", name="uq_telegram_topic_group_thread"),
    )


# ── topic_registration ─────────────────────────────────────────────────────
class TopicRegistration(db.Model):
    """Pending seed-фраза, ждущая распознавания ботом в форум-топике.

    Lifecycle:
      created (UI запрос) → expires_at = now()+15min
      consumed_at != null → бот распознал, topic_id указывает на созданный TelegramTopic
      expires_at < now() and consumed_at is null → истекло
    """
    __tablename__ = "topic_registration"

    id           = db.Column(db.Integer, primary_key=True)
    company_id  = db.Column(db.Integer, nullable=True, index=True)
    # group_id IS NULL → pending регистрация группы (фраза вставляется в
    # любой чат, где бот, → создаём TelegramGroup с chat_id=сообщения).
    # group_id IS NOT NULL → pending регистрация топика в этой группе.
    group_id     = db.Column(db.Integer, db.ForeignKey("telegram_group.id", ondelete="CASCADE"),
                             nullable=True, index=True)
    phrase       = db.Column(db.String(64), nullable=False, unique=True)
    name         = db.Column(db.String(255), nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at   = db.Column(db.DateTime, nullable=False)
    consumed_at  = db.Column(db.DateTime, nullable=True)
    topic_id     = db.Column(db.Integer, db.ForeignKey("telegram_topic.id", ondelete="SET NULL"),
                             nullable=True)


# ── event_type ─────────────────────────────────────────────────────────────
class EventType(db.Model):
    """Каталог типов событий (сид ядра + sync из module.json.emits)."""
    __tablename__ = "event_type"

    id            = db.Column(db.Integer, primary_key=True)
    key           = db.Column(db.String(120), nullable=False, unique=True)  # 'tasks.task.overdue'
    label         = db.Column(db.String(255), nullable=False, default="")
    source_module = db.Column(db.String(60), nullable=False, default="core")
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# ── routing_rule ───────────────────────────────────────────────────────────
class RoutingRule(db.Model):
    """Правило маршрутизации TG-доставки:
       event_type [× branch_filter] → telegram_group [× topic].

    Email-доставка НЕ ходит через rules — source-модули шлют /events
    с явными recipients в режиме `channel_kind='email'`.
    """
    __tablename__ = "routing_rule"

    id                = db.Column(db.Integer, primary_key=True)
    company_id  = db.Column(db.Integer, nullable=True, index=True)
    event_type_id     = db.Column(db.Integer, db.ForeignKey("event_type.id", ondelete="CASCADE"),
                                  nullable=False, index=True)
    branch_id         = db.Column(db.Integer, nullable=True, index=True)  # NULL = любой филиал
    telegram_group_id = db.Column(db.Integer, db.ForeignKey("telegram_group.id", ondelete="CASCADE"),
                                  nullable=False, index=True)
    topic_id          = db.Column(db.Integer, db.ForeignKey("telegram_topic.id", ondelete="SET NULL"),
                                  nullable=True, index=True)  # NULL = общий чат группы
    is_enabled        = db.Column(db.Boolean, nullable=False, default=True)
    priority          = db.Column(db.Integer, nullable=False, default=100)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow,
                                  onupdate=datetime.utcnow, nullable=False)


# ── message ────────────────────────────────────────────────────────────────
class Message(db.Model):
    """Очередь/журнал исходящих сообщений (email + telegram)."""
    __tablename__ = "message"

    id            = db.Column(db.Integer, primary_key=True)
    company_id  = db.Column(db.Integer, nullable=True, index=True)
    channel_id    = db.Column(db.Integer, db.ForeignKey("channel.id", ondelete="SET NULL"),
                              nullable=True, index=True)
    source_module = db.Column(db.String(60), nullable=False, default="core")
    event_type    = db.Column(db.String(120), nullable=False, default="")
    payload       = db.Column(JSONB, nullable=False, default=dict)
    to_address    = db.Column(db.String(255), nullable=False, default="")  # email или chat_id строкой
    subject       = db.Column(db.String(500), nullable=True)
    body_text     = db.Column(db.Text, nullable=True)
    body_html     = db.Column(db.Text, nullable=True)
    status        = db.Column(db.String(20), nullable=False, default="pending")  # pending|sending|sent|failed
    attempts      = db.Column(db.Integer, nullable=False, default=0)
    last_error    = db.Column(db.Text, nullable=True)
    sent_at       = db.Column(db.DateTime, nullable=True)
    dedup_key     = db.Column(db.String(120), nullable=True, index=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow,
                              onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        # hot-path для worker'а: следующее pending по возрасту
        db.Index("ix_message_status_created", "status", "created_at"),
    )


# ── inbound_message ────────────────────────────────────────────────────────
class InboundMessage(db.Model):
    """Входящие сообщения из Telegram (long polling)."""
    __tablename__ = "inbound_message"

    id            = db.Column(db.Integer, primary_key=True)
    company_id  = db.Column(db.Integer, nullable=True, index=True)
    channel_id    = db.Column(db.Integer, db.ForeignKey("channel.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    chat_id       = db.Column(db.BigInteger, nullable=False, index=True)
    from_user_id  = db.Column(db.BigInteger, nullable=True)
    from_username = db.Column(db.String(120), nullable=True)
    text          = db.Column(db.Text, nullable=True)
    telegram_message_id        = db.Column(db.BigInteger, nullable=False)
    telegram_update_id         = db.Column(db.BigInteger, nullable=False)
    reply_to_telegram_message_id = db.Column(db.BigInteger, nullable=True)
    reply_to_message_id        = db.Column(db.Integer,
                                           db.ForeignKey("message.id", ondelete="SET NULL"),
                                           nullable=True, index=True)
    raw           = db.Column(JSONB, nullable=False, default=dict)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("channel_id", "telegram_update_id",
                            name="uq_inbound_channel_update"),
    )


# ── poll_state ─────────────────────────────────────────────────────────────
class PollState(db.Model):
    """Курсор getUpdates на каждого бота-канала."""
    __tablename__ = "poll_state"

    id              = db.Column(db.Integer, primary_key=True)
    channel_id      = db.Column(db.Integer, db.ForeignKey("channel.id", ondelete="CASCADE"),
                                nullable=False, unique=True)
    last_update_id  = db.Column(db.BigInteger, nullable=False, default=0)
    last_polled_at  = db.Column(db.DateTime, nullable=True)
