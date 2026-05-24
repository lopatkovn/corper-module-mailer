"""system-scope + group-seed-registration

Revision ID: c8d92f4b7a05
Revises: b5f12c4a8e91
Create Date: 2026-05-24 13:00:00.000000

Изменения:
  1. ALTER topic_registration.group_id NULLABLE — переиспользуем таблицу
     для регистрации СОБСТВЕННО ГРУППЫ через seed-фразу (group_id IS NULL
     означает «pending регистрация группы», не топика).
  2. ALTER mailer.channel.company_id NULLABLE — `company_id IS NULL`
     становится системным каналом (платформенный бот, системный SMTP)
     для super_admin'а в /admin/notifications.
  3. ALTER mailer.message.company_id NULLABLE — same scope для журнала.
  4. ALTER mailer.telegram_group.company_id NULLABLE — для системных групп.
  5. ALTER mailer.inbound_message.company_id NULLABLE.
  6. ALTER mailer.routing_rule.company_id NULLABLE.
  7. ALTER mailer.telegram_topic.company_id NULLABLE.
  8. ALTER mailer.topic_registration.company_id NULLABLE.

Channel.UNIQUE(company_id, kind) переживёт NULL — Postgres трактует NULL
как «не равно ничему» в UNIQUE → можем иметь одну `system + email` и
одну `system + telegram` записи (без коллизий с per-company).

`uq_telegram_group_company_chat` тот же fine.
"""
from alembic import op
import sqlalchemy as sa


revision = "c8d92f4b7a05"
down_revision = "b5f12c4a8e91"
branch_labels = None
depends_on = None


_NULLABLE_TABLES = [
    ("channel", "company_id"),
    ("telegram_group", "company_id"),
    ("telegram_topic", "company_id"),
    ("topic_registration", "company_id"),
    ("topic_registration", "group_id"),
    ("routing_rule", "company_id"),
    ("message", "company_id"),
    ("inbound_message", "company_id"),
]


def upgrade():
    for table, col in _NULLABLE_TABLES:
        op.alter_column(table, col, nullable=True)


def downgrade():
    # Defensive: clear NULL rows before forcing NOT NULL (иначе ALTER провалится)
    for table, col in reversed(_NULLABLE_TABLES):
        op.execute(f"DELETE FROM {table} WHERE {col} IS NULL")
        op.alter_column(table, col, nullable=False)
