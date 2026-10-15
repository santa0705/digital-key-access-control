"""
backend/app/migration_guard.py -- Fail-closed Alembic migration safety guard.

Ensures that Alembic migrations (online or offline) can NEVER run against
remote/cloud databases (such as shared Neon) or unapproved targets.
Requires explicit opt-in via ALLOW_LOCAL_MIGRATION=true and strict validation
against host, port, database, and user allowlists.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Set
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL


class MigrationTargetError(Exception):
    """Raised when a migration target fails safety verification."""
    pass


@dataclass(frozen=True)
class TargetValidationResult:
    """Safe, sanitized representation of a verified migration target."""
    drivername: str
    host: str
    port: int
    database: str
    username: Optional[str]
    masked_url: str


def mask_database_url(url: str) -> str:
    """
    Produce a safe-to-log database URL with password replaced by '***'.
    Never exposes credentials or secrets.
    """
    if not url:
        return "<empty>"
    try:
        parsed = make_url(url)
        return parsed.render_as_string(hide_password=True)
    except Exception:
        # Fallback manual string masking if make_url cannot parse
        try:
            parts = urlsplit(url)
            netloc = parts.netloc
            if "@" in netloc:
                userinfo, hostport = netloc.rsplit("@", 1)
                user = userinfo.split(":", 1)[0]
                netloc = f"{user}:***@{hostport}"
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        except Exception:
            return "<unparseable-url>"


def parse_string_allowlist(raw: Optional[str]) -> Set[str]:
    """Parse comma-separated allowlist into lowercase stripped strings."""
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def parse_port_allowlist(raw: Optional[str]) -> Set[int]:
    """
    Parse comma-separated port allowlist into a set of integer port numbers.
    Fails closed (raises MigrationTargetError) if any value is not a valid port.
    """
    if not raw:
        return set()
    ports: Set[int] = set()
    for item in raw.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        try:
            port_num = int(cleaned)
            if not (1 <= port_num <= 65535):
                raise ValueError(f"Port {port_num} out of valid range (1-65535)")
            ports.add(port_num)
        except Exception as exc:
            raise MigrationTargetError(
                f"Invalid port configuration in approved ports allowlist: {cleaned}"
            ) from exc
    return ports


def is_truthy(val: Optional[str | bool]) -> bool:
    """Check if value represents a boolean True."""
    if isinstance(val, bool):
        return val
    if not val:
        return False
    return str(val).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def validate_migration_target(
    url_to_check: Optional[str] = None,
    allow_local_migration: Optional[bool | str] = None,
    approved_hosts: Optional[str | Set[str]] = None,
    approved_ports: Optional[str | Set[int]] = None,
    approved_db_names: Optional[str | Set[str]] = None,
    approved_users: Optional[str | Set[str]] = None,
) -> TargetValidationResult:
    """
    Validate a database URL for Alembic migration execution.
    Fails closed on any ambiguity, remote host, missing target, or unapproved property.

    Args:
        url_to_check: Target database connection URL. If None, loaded from env / config.
        allow_local_migration: Explicit opt-in flag.
        approved_hosts: Set or comma-separated string of allowed hosts.
        approved_ports: Set or comma-separated string of allowed ports.
        approved_db_names: Set or comma-separated string of allowed database names.
        approved_users: Set or comma-separated string of allowed users.
    """
    # 1. Resolve configuration values (favoring explicit arguments, then app.config, then os.getenv)
    if allow_local_migration is None:
        env_opt = os.getenv("ALLOW_LOCAL_MIGRATION")
        if env_opt is not None:
            allow_local_migration = env_opt
        else:
            try:
                from app.config import get_settings
                allow_local_migration = get_settings().ALLOW_LOCAL_MIGRATION
            except Exception:
                allow_local_migration = False

    if not is_truthy(allow_local_migration):
        raise MigrationTargetError(
            "Local database migrations are disabled by default. "
            "Set ALLOW_LOCAL_MIGRATION=true to explicitly opt-in."
        )

    # 2. Check for missing URL
    if url_to_check is None:
        url_to_check = os.getenv("DATABASE_URL")
        if not url_to_check:
            try:
                from app.config import get_settings
                url_to_check = get_settings().DATABASE_URL
            except Exception:
                url_to_check = None

    if not url_to_check or not str(url_to_check).strip():
        raise MigrationTargetError("Migration target database URL is missing or empty.")

    url_str = str(url_to_check).strip()

    # Normalize unbracketed IPv6 addresses with ports: e.g. @::1:5432/db -> @[::1]:5432/db
    if "@" in url_str:
        prefix, remainder = url_str.rsplit("@", 1)
        hostport = remainder.split("/", 1)[0]
        if hostport.count(":") > 1 and not hostport.startswith("["):
            # Multiple colons indicates IPv6
            r_colon = hostport.rfind(":")
            ipv6_part = hostport[:r_colon]
            port_part = hostport[r_colon + 1:]
            if port_part.isdigit():
                remainder_tail = remainder[len(hostport):]
                url_str = f"{prefix}@[{ipv6_part}]:{port_part}{remainder_tail}"

    # 3. Parse target URL safely
    try:
        parsed_url: URL = make_url(url_str)
    except Exception as exc:
        raise MigrationTargetError(
            f"Failed to parse database URL: {mask_database_url(url_str)}"
        ) from exc

    masked = mask_database_url(url_str)

    # 4. Validate driver / dialect
    driver = (parsed_url.drivername or "").lower()
    if not driver.startswith("postgres"):
        raise MigrationTargetError(
            f"Migration target dialect '{driver}' is not an approved PostgreSQL dialect."
        )

    # 5. Validate Host
    raw_host = parsed_url.host
    if not raw_host:
        raise MigrationTargetError(
            f"Database URL has no host specified: {masked}"
        )

    host = raw_host.strip().lower()
    # Normalize IPv6 bracket notation e.g. [::1] -> ::1
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    if approved_hosts is None:
        env_hosts = os.getenv("APPROVED_MIGRATION_HOSTS")
        if env_hosts is not None:
            hosts_set = parse_string_allowlist(env_hosts)
        else:
            try:
                from app.config import get_settings
                hosts_set = parse_string_allowlist(get_settings().APPROVED_MIGRATION_HOSTS)
            except Exception:
                hosts_set = {"localhost", "127.0.0.1", "::1"}
    elif isinstance(approved_hosts, str):
        hosts_set = parse_string_allowlist(approved_hosts)
    else:
        hosts_set = {h.lower() for h in approved_hosts}

    if not hosts_set:
        raise MigrationTargetError(
            "Approved migration hosts allowlist is empty; failing closed."
        )

    if host not in hosts_set:
        raise MigrationTargetError(
            f"Host '{host}' is not in the approved migration hosts allowlist: {sorted(hosts_set)}"
        )

    # 6. Validate Port
    port = parsed_url.port
    if port is None:
        # Default PostgreSQL port
        port = 5432

    if approved_ports is None:
        env_ports = os.getenv("APPROVED_MIGRATION_PORTS")
        if env_ports is not None:
            ports_set = parse_port_allowlist(env_ports)
        else:
            try:
                from app.config import get_settings
                ports_set = parse_port_allowlist(get_settings().APPROVED_MIGRATION_PORTS)
            except Exception:
                ports_set = {5432}
    elif isinstance(approved_ports, str):
        ports_set = parse_port_allowlist(approved_ports)
    else:
        ports_set = set(approved_ports)

    if not ports_set:
        raise MigrationTargetError(
            "Approved migration ports allowlist is empty; failing closed."
        )

    if port not in ports_set:
        raise MigrationTargetError(
            f"Port {port} is not in the approved migration ports allowlist: {sorted(ports_set)}"
        )

    # 7. Validate Database Name
    db_name = (parsed_url.database or "").strip().lower()
    if not db_name:
        raise MigrationTargetError(
            f"Database URL specifies no database name: {masked}"
        )

    if approved_db_names is None:
        env_dbs = os.getenv("APPROVED_MIGRATION_DB_NAMES")
        if env_dbs is not None:
            db_set = parse_string_allowlist(env_dbs)
        else:
            try:
                from app.config import get_settings
                db_set = parse_string_allowlist(get_settings().APPROVED_MIGRATION_DB_NAMES)
            except Exception:
                db_set = {"digital_key"}
    elif isinstance(approved_db_names, str):
        db_set = parse_string_allowlist(approved_db_names)
    else:
        db_set = {d.lower() for d in approved_db_names}

    if not db_set:
        raise MigrationTargetError(
            "Approved migration databases allowlist is empty; failing closed."
        )

    if db_name not in db_set:
        raise MigrationTargetError(
            f"Database '{db_name}' is not in the approved migration database allowlist: {sorted(db_set)}"
        )

    # 8. Validate User (if configured)
    user = parsed_url.username
    if approved_users is None:
        env_users = os.getenv("APPROVED_MIGRATION_USERS")
        if env_users is not None:
            users_set = parse_string_allowlist(env_users)
        else:
            try:
                from app.config import get_settings
                users_set = parse_string_allowlist(get_settings().APPROVED_MIGRATION_USERS)
            except Exception:
                users_set = set()
    elif isinstance(approved_users, str):
        users_set = parse_string_allowlist(approved_users)
    else:
        users_set = {u.lower() for u in approved_users}

    if users_set:
        if not user or user.lower() not in users_set:
            raise MigrationTargetError(
                f"User '{user}' is not in approved migration users allowlist."
            )

    return TargetValidationResult(
        drivername=driver,
        host=host,
        port=port,
        database=db_name,
        username=user,
        masked_url=masked,
    )
