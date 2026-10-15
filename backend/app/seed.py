"""
backend/app/seed.py -- Idempotent seed and reset utilities for local development.

Guarantees & Safety:
  - Fails closed if attempted against any remote or Neon production database.
  - Idempotent: Can be run repeatedly without duplicating users, resources, or nodes.
  - Seeds canonical demo users, physical/simulated locker resources, and prototype terminal node.
"""
from __future__ import annotations

import sys
import uuid
from typing import Any, Dict

import bcrypt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.migration_guard import MigrationTargetError, validate_migration_target
from app.models.nodes import Node, NodeTimeState
from app.models.resources import Resource, ResourceKind
from app.models.sync_state import SyncState
from app.models.users import User, UserRole

DEMO_PASSWORD = "demo-password"


def _hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_safe_seed_target(db: Session) -> None:
    """
    Ensure the target database is an authorized local environment.
    Raises MigrationTargetError if pointing to Neon or any unapproved remote target.
    """
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite in-memory or local test file is always safe

    # Inspect connection URL
    url_str = str(bind.url)
    settings = get_settings()

    # Reuse migration guard to validate local boundary
    validate_migration_target(
        url_to_check=url_str,
        allow_local_migration=True,
        approved_hosts={h.strip() for h in settings.APPROVED_MIGRATION_HOSTS.split(",") if h.strip()},
        approved_ports={int(p.strip()) for p in settings.APPROVED_MIGRATION_PORTS.split(",") if p.strip()},
        approved_db_names={d.strip() for d in settings.APPROVED_MIGRATION_DB_NAMES.split(",") if d.strip()},
    )


def seed_database(db: Session) -> Dict[str, int]:
    """
    Idempotently seeds initial data for local development:
      - Demo admin user (admin@demo.local)
      - Demo normal user (user@demo.local)
      - Resource A (physical locker)
      - Resource B (simulated locker)
      - Default terminal node (node-01)
      - SyncState singleton (id=1, current_seq=0)

    Returns a summary dictionary with counts of items ensured.
    """
    verify_safe_seed_target(db)

    counts = {"users": 0, "resources": 0, "nodes": 0, "sync_state": 0}

    # 1. Ensure sync_state singleton
    state = db.query(SyncState).filter(SyncState.id == 1).first()
    if state is None:
        state = SyncState(id=1, epoch=str(uuid.uuid4()), current_seq=0)
        db.add(state)
        db.flush()
        counts["sync_state"] += 1

    # 2. Ensure Users
    demo_users = [
        {
            "email": "admin@demo.local",
            "full_name": "Demo Admin",
            "role": UserRole.ADMIN.value,
            "password": DEMO_PASSWORD,
        },
        {
            "email": "user@demo.local",
            "full_name": "Demo User",
            "role": UserRole.USER.value,
            "password": DEMO_PASSWORD,
        },
    ]

    for u_data in demo_users:
        existing = db.query(User).filter(User.email == u_data["email"]).first()
        if existing is None:
            user = User(
                email=u_data["email"],
                full_name=u_data["full_name"],
                password_hash=_hash_password(u_data["password"]),
                role=u_data["role"],
                is_active=True,
            )
            db.add(user)
            counts["users"] += 1

    # 3. Ensure Resources
    demo_resources = [
        {"code": "A", "name": "Locker A", "kind": ResourceKind.PHYSICAL.value},
        {"code": "B", "name": "Locker B", "kind": ResourceKind.SIMULATED.value},
    ]

    for r_data in demo_resources:
        existing = db.query(Resource).filter(Resource.code == r_data["code"]).first()
        if existing is None:
            res = Resource(
                code=r_data["code"],
                name=r_data["name"],
                kind=r_data["kind"],
                is_active=True,
            )
            db.add(res)
            counts["resources"] += 1

    # 4. Ensure Terminal Node
    existing_node = db.query(Node).filter(Node.node_code == "node-01").first()
    if existing_node is None:
        node = Node(
            node_code="node-01",
            firmware_version="0.1.0",
            time_state=NodeTimeState.SERVER_ANCHORED.value,
            last_acked_seq=0,
        )
        db.add(node)
        counts["nodes"] += 1

    db.commit()
    return counts


def reset_database(db: Session) -> Dict[str, Any]:
    """
    Cleans domain tables and re-seeds fresh data on local development target.
    Strictly forbidden on remote/production databases.
    """
    verify_safe_seed_target(db)

    # Clean in reverse dependency order
    from app.models.access_events import AccessEvent
    from app.models.access_requests import AccessRequest
    from app.models.credentials import Credential

    db.query(AccessEvent).delete()
    db.query(Credential).delete()
    db.query(AccessRequest).delete()
    db.query(Node).delete()
    db.query(Resource).delete()
    db.query(User).delete()

    # Reset sync_state current_seq to 0
    state = db.query(SyncState).filter(SyncState.id == 1).first()
    if state:
        state.current_seq = 0
        state.epoch = str(uuid.uuid4())

    db.commit()
    return seed_database(db)


def main() -> None:
    """CLI runner for seed and reset operations."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        if "--reset" in sys.argv:
            print("Resetting and re-seeding local database...")
            result = reset_database(db)
            print(f"Database reset and seeded: {result}")
        else:
            print("Seeding local database...")
            result = seed_database(db)
            print(f"Database seeded: {result}")



if __name__ == "__main__":
    main()
