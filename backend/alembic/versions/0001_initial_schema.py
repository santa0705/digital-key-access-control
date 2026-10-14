"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-13 22:00:00.000000

Initial migration creating seven domain tables, check constraints,
monotonic change sequence procedure, partial active credential unique index (Rule R1),
terminal immutability trigger, and audit indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. users
    # -------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, always=False), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'user'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # -------------------------------------------------------------------------
    # 2. resources
    # -------------------------------------------------------------------------
    op.create_table(
        "resources",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, always=False), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_resources"),
        sa.UniqueConstraint("code", name="uq_resources_code"),
        sa.CheckConstraint("code IN ('A', 'B')", name="ck_resources_code"),
        sa.CheckConstraint("kind IN ('physical', 'simulated')", name="ck_resources_kind"),
    )
    op.create_index("ix_resources_code", "resources", ["code"])

    # -------------------------------------------------------------------------
    # 3. nodes
    # -------------------------------------------------------------------------
    op.create_table(
        "nodes",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, always=False), primary_key=True),
        sa.Column("node_code", sa.Text(), nullable=False),
        sa.Column("firmware_version", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_state", sa.Text(), nullable=True),
        sa.Column("last_acked_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_nodes"),
        sa.UniqueConstraint("node_code", name="uq_nodes_node_code"),
        sa.CheckConstraint(
            "time_state IS NULL OR time_state IN ('untrusted', 'rtc_validated', 'server_anchored')",
            name="ck_nodes_time_state",
        ),
    )
    op.create_index("ix_nodes_node_code", "nodes", ["node_code"])

    # -------------------------------------------------------------------------
    # 4. sync_state
    # -------------------------------------------------------------------------
    op.create_table(
        "sync_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("epoch", sa.Text(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("current_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id", name="pk_sync_state"),
        sa.CheckConstraint("id = 1", name="ck_sync_state_single_row"),
    )

    # Insert singleton row (id = 1) if not present
    op.execute("""
        INSERT INTO sync_state (id, epoch, current_seq)
        VALUES (1, gen_random_uuid()::text, 0)
        ON CONFLICT (id) DO NOTHING;
    """)

    # Stored function for atomic, gap-free change sequence increment
    op.execute("""
        CREATE OR REPLACE FUNCTION next_change_seq() RETURNS bigint AS $$
        DECLARE
            new_seq bigint;
        BEGIN
            UPDATE sync_state
            SET current_seq = current_seq + 1
            WHERE id = 1
            RETURNING current_seq INTO new_seq;

            IF new_seq IS NULL THEN
                RAISE EXCEPTION 'sync_state singleton row missing (id=1)';
            END IF;

            RETURN new_seq;
        END;
        $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION trg_sync_state_protect_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Deleting sync_state singleton row is prohibited (id=%)', OLD.id;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER check_sync_state_protect_delete
        BEFORE DELETE ON sync_state
        FOR EACH ROW
        EXECUTE FUNCTION trg_sync_state_protect_delete();
    """)

    # -------------------------------------------------------------------------
    # 5. access_requests
    # -------------------------------------------------------------------------
    op.create_table(
        "access_requests",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, always=False), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("resource_id", sa.BigInteger(), sa.ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purpose", sa.String(length=200), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("decided_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_access_requests"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'revoked')", name="ck_access_requests_status"),
        sa.CheckConstraint("end_at > start_at", name="ck_access_requests_end_after_start"),
        sa.CheckConstraint("end_at - start_at <= INTERVAL '24 hours'", name="ck_access_requests_max_24h"),
    )
    op.create_index("ix_access_requests_user_id", "access_requests", ["user_id"])
    op.create_index("ix_access_requests_resource_id", "access_requests", ["resource_id"])
    op.create_index("ix_access_requests_status", "access_requests", ["status"])

    # -------------------------------------------------------------------------
    # 6. credentials
    # -------------------------------------------------------------------------
    op.create_table(
        "credentials",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, always=False), primary_key=True),
        sa.Column("request_id", sa.BigInteger(), sa.ForeignKey("access_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("resource_id", sa.BigInteger(), sa.ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pin_hmac", sa.String(length=64), nullable=False),
        sa.Column("pin_encrypted", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("change_seq", sa.BigInteger(), nullable=False),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_node_id", sa.BigInteger(), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_credentials"),
        sa.UniqueConstraint("request_id", name="uq_credentials_request_id"),
        sa.UniqueConstraint("change_seq", name="uq_credentials_change_seq"),
        sa.UniqueConstraint("resource_id", "pin_hmac", name="uq_credentials_resource_pin_hmac"),
        sa.CheckConstraint("status IN ('active', 'consumed', 'expired', 'revoked')", name="ck_credentials_status"),
        sa.CheckConstraint(
            "(status = 'revoked' AND revoke_reason IN ('admin', 'superseded')) OR (status != 'revoked' AND revoke_reason IS NULL)",
            name="ck_credentials_revoke_reason",
        ),
        sa.CheckConstraint("valid_until > valid_from", name="ck_credentials_valid_window"),
    )
    op.create_index("ix_credentials_status", "credentials", ["status"])

    # Rule R1: Partial unique index allowing at most one active credential per resource
    op.execute("""
        CREATE UNIQUE INDEX uq_credentials_resource_active
        ON credentials (resource_id)
        WHERE status = 'active';
    """)

    # Database trigger enforcing terminal immutability and protecting terminal credentials
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_credentials_terminal_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status IN ('consumed', 'expired', 'revoked') THEN
                    RAISE EXCEPTION 'Terminal credential cannot be deleted: id=%, status=%',
                        OLD.id, OLD.status;
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.status IN ('consumed', 'expired', 'revoked') THEN
                IF NEW.status != OLD.status THEN
                    RAISE EXCEPTION 'Terminal credential status cannot be changed: id=%, current=%, attempted=%',
                        OLD.id, OLD.status, NEW.status;
                END IF;
                IF NEW.pin_hmac != OLD.pin_hmac OR NEW.pin_encrypted != OLD.pin_encrypted OR NEW.resource_id != OLD.resource_id OR NEW.request_id != OLD.request_id THEN
                    RAISE EXCEPTION 'Terminal credential core identity fields cannot be modified: id=%, status=%',
                        OLD.id, OLD.status;
                END IF;
            END IF;

            IF OLD.status != 'active' AND (NEW.valid_from != OLD.valid_from OR NEW.valid_until != OLD.valid_until) THEN
                RAISE EXCEPTION 'Validity window cannot be modified for non-active credential: id=%, status=%',
                    OLD.id, OLD.status;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER check_credential_terminal_immutability
        BEFORE UPDATE OR DELETE ON credentials
        FOR EACH ROW
        EXECUTE FUNCTION trg_credentials_terminal_immutability();
    """)

    # -------------------------------------------------------------------------
    # 7. access_events
    # -------------------------------------------------------------------------
    op.create_table(
        "access_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, always=False), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.BigInteger(), sa.ForeignKey("access_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resource_id", sa.BigInteger(), sa.ForeignKey("resources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("credential_id", sa.BigInteger(), sa.ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("device_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_trusted", sa.Boolean(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_access_events"),
        sa.UniqueConstraint("event_id", name="uq_access_events_event_id"),
        sa.CheckConstraint("source IN ('device', 'server')", name="ck_access_events_source"),
        sa.CheckConstraint(
            "event_type IN ("
            "'pin_rejected', 'credential_accepted', 'unlock_command_issued', 'lockout_started', "
            "'request_created', 'request_approved', 'request_rejected', "
            "'credential_issued', 'credential_replaced', 'credential_revoked', "
            "'credential_expired', 'credential_consumed', 'pin_revealed')",
            name="ck_access_events_event_type",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ("
            "'wrong_pin', 'wrong_resource', 'expired', 'not_yet_valid', "
            "'consumed', 'revoked', 'time_untrusted')",
            name="ck_access_events_reason",
        ),
        sa.CheckConstraint(
            "source != 'device' OR time_trusted IS NOT NULL",
            name="ck_access_events_device_time_trusted",
        ),
    )
    op.create_index("ix_access_events_event_id", "access_events", ["event_id"])

    # Descending index for audit log queries
    op.execute("""
        CREATE INDEX ix_access_events_occurred_at_desc
        ON access_events (occurred_at DESC);
    """)


def downgrade() -> None:
    # Drop in exact reverse order of creation
    op.execute("DROP INDEX IF EXISTS ix_access_events_occurred_at_desc;")
    op.drop_table("access_events")

    op.execute("DROP TRIGGER IF EXISTS check_credential_terminal_immutability ON credentials;")
    op.execute("DROP FUNCTION IF EXISTS trg_credentials_terminal_immutability();")
    op.execute("DROP INDEX IF EXISTS uq_credentials_resource_active;")
    op.drop_table("credentials")

    op.drop_table("access_requests")

    op.execute("DROP TRIGGER IF EXISTS check_sync_state_protect_delete ON sync_state;")
    op.execute("DROP FUNCTION IF EXISTS trg_sync_state_protect_delete();")
    op.execute("DROP FUNCTION IF EXISTS next_change_seq();")
    op.drop_table("sync_state")

    op.drop_table("nodes")
    op.drop_table("resources")
    op.drop_table("users")
