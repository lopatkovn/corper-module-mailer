"""topics + rule rebuild + tg-group department link

Revision ID: b5f12c4a8e91
Revises: a36227e3411a
Create Date: 2026-05-24 12:00:00.000000

Изменения:
  1. CREATE TABLE telegram_topic (зарегистрированные форум-топики)
  2. CREATE TABLE topic_registration (pending seed-фразы)
  3. ALTER telegram_group:
       + is_forum BOOLEAN
       + department_id INTEGER (soft-FK на core.department, cross-schema)
       + archived_at TIMESTAMP (soft-archive)
  4. ALTER routing_rule (полная перестройка под TG-only):
       - DROP COLUMN recipients
       - DROP COLUMN channel_id
       + branch_id INTEGER nullable
       + telegram_group_id INTEGER NOT NULL FK
       + topic_id INTEGER nullable FK

⚠️ Старые routing_rule с email-recipients **не сохраняются**:
   таблица очищается перед ALTER (см. upgrade), пользователь пересоздаст правила
   через новый UI.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision = "b5f12c4a8e91"
down_revision = "a36227e3411a"
branch_labels = None
depends_on = None


def upgrade():
    # 1. telegram_topic
    op.create_table(
        "telegram_topic",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("telegram_thread_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("registered_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["telegram_group.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "telegram_thread_id",
                            name="uq_telegram_topic_group_thread"),
    )
    op.create_index("ix_telegram_topic_company_id", "telegram_topic", ["company_id"])
    op.create_index("ix_telegram_topic_group_id", "telegram_topic", ["group_id"])

    # 2. topic_registration
    op.create_table(
        "topic_registration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("phrase", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["telegram_group.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["telegram_topic.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("phrase", name="uq_topic_registration_phrase"),
    )
    op.create_index("ix_topic_registration_company_id", "topic_registration", ["company_id"])
    op.create_index("ix_topic_registration_group_id", "topic_registration", ["group_id"])
    # частичный индекс для поиска pending
    op.execute(
        "CREATE INDEX ix_topic_registration_pending "
        "ON topic_registration(phrase) WHERE consumed_at IS NULL"
    )

    # 3. telegram_group ALTER
    op.add_column("telegram_group",
                  sa.Column("is_forum", sa.Boolean(), nullable=False,
                            server_default=sa.false()))
    op.add_column("telegram_group",
                  sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column("telegram_group",
                  sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.create_index("ix_telegram_group_department_id", "telegram_group", ["department_id"])

    # 4. routing_rule rebuild — очищаем (старые рулы становятся невалидными)
    op.execute("DELETE FROM routing_rule")
    op.drop_index("ix_routing_rule_channel_id", table_name="routing_rule")
    op.drop_constraint("routing_rule_channel_id_fkey", "routing_rule", type_="foreignkey")
    op.drop_column("routing_rule", "channel_id")
    op.drop_column("routing_rule", "recipients")

    op.add_column("routing_rule",
                  sa.Column("branch_id", sa.Integer(), nullable=True))
    op.add_column("routing_rule",
                  sa.Column("telegram_group_id", sa.Integer(), nullable=False))
    op.add_column("routing_rule",
                  sa.Column("topic_id", sa.Integer(), nullable=True))
    op.create_foreign_key("routing_rule_telegram_group_id_fkey", "routing_rule",
                          "telegram_group", ["telegram_group_id"], ["id"],
                          ondelete="CASCADE")
    op.create_foreign_key("routing_rule_topic_id_fkey", "routing_rule",
                          "telegram_topic", ["topic_id"], ["id"],
                          ondelete="SET NULL")
    op.create_index("ix_routing_rule_branch_id", "routing_rule", ["branch_id"])
    op.create_index("ix_routing_rule_telegram_group_id", "routing_rule",
                    ["telegram_group_id"])
    op.create_index("ix_routing_rule_topic_id", "routing_rule", ["topic_id"])


def downgrade():
    # Reverse order
    # 4. routing_rule
    op.execute("DELETE FROM routing_rule")
    op.drop_index("ix_routing_rule_topic_id", table_name="routing_rule")
    op.drop_index("ix_routing_rule_telegram_group_id", table_name="routing_rule")
    op.drop_index("ix_routing_rule_branch_id", table_name="routing_rule")
    op.drop_constraint("routing_rule_topic_id_fkey", "routing_rule", type_="foreignkey")
    op.drop_constraint("routing_rule_telegram_group_id_fkey", "routing_rule",
                       type_="foreignkey")
    op.drop_column("routing_rule", "topic_id")
    op.drop_column("routing_rule", "telegram_group_id")
    op.drop_column("routing_rule", "branch_id")
    op.add_column("routing_rule",
                  sa.Column("recipients",
                            postgresql.JSONB(astext_type=sa.Text()),
                            nullable=False,
                            server_default=sa.text("'{}'::jsonb")))
    op.add_column("routing_rule",
                  sa.Column("channel_id", sa.Integer(), nullable=False))
    op.create_foreign_key("routing_rule_channel_id_fkey", "routing_rule",
                          "channel", ["channel_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_routing_rule_channel_id", "routing_rule", ["channel_id"])

    # 3. telegram_group
    op.drop_index("ix_telegram_group_department_id", table_name="telegram_group")
    op.drop_column("telegram_group", "archived_at")
    op.drop_column("telegram_group", "department_id")
    op.drop_column("telegram_group", "is_forum")

    # 2. topic_registration
    op.execute("DROP INDEX IF EXISTS ix_topic_registration_pending")
    op.drop_index("ix_topic_registration_group_id", table_name="topic_registration")
    op.drop_index("ix_topic_registration_company_id", table_name="topic_registration")
    op.drop_table("topic_registration")

    # 1. telegram_topic
    op.drop_index("ix_telegram_topic_group_id", table_name="telegram_topic")
    op.drop_index("ix_telegram_topic_company_id", table_name="telegram_topic")
    op.drop_table("telegram_topic")
