import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Ensure backend package root is importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Resolve repository root where .env is stored
ROOT_DIR = BACKEND_DIR.parent
ENV_FILE = ROOT_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# Import shared models and declarative Base metadata
from app.models import Base  # noqa: E402
from app.migration_guard import validate_migration_target, mask_database_url  # noqa: E402

# Alembic Config object
config = context.config

# Interpret config file for logging if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for migrations and autogenerate
target_metadata = Base.metadata

# Resolve effective database URL:
# 1. -x url=<url> CLI argument
# 2. -o sqlalchemy.url=<url> CLI or config override
# 3. DATABASE_URL environment variable
# 4. app.config.get_settings().DATABASE_URL
x_args = context.get_x_argument(as_dictionary=True)
cli_x_url = x_args.get("url") if isinstance(x_args, dict) else None
main_opt_url = config.get_main_option("sqlalchemy.url")

effective_url = cli_x_url or main_opt_url or os.getenv("DATABASE_URL")
if not effective_url:
    try:
        from app.config import get_settings
        effective_url = get_settings().DATABASE_URL
    except Exception:
        effective_url = None

if effective_url:
    effective_url = effective_url.strip()
    if effective_url.startswith("postgres://"):
        effective_url = "postgresql+psycopg://" + effective_url[len("postgres://"):]
    elif effective_url.startswith("postgresql://") and not effective_url.startswith("postgresql+"):
        effective_url = "postgresql+psycopg://" + effective_url[len("postgresql://"):]

# Fail-closed validation before any connection, engine creation, or DDL execution
validate_migration_target(effective_url)

if effective_url:
    config.set_main_option("sqlalchemy.url", effective_url)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    Emits SQL statements directly without establishing a live database connection.
    Guarded against unapproved targets and remote/cloud databases.
    """
    url = config.get_main_option("sqlalchemy.url")
    validate_migration_target(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    Creates an Engine and associates a connection with the context.
    Guarded against unapproved targets and remote/cloud databases.
    """
    url = config.get_main_option("sqlalchemy.url")
    validate_migration_target(url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
