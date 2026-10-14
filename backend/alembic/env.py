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

# Alembic Config object
config = context.config

# Interpret config file for logging if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for migrations and autogenerate
target_metadata = Base.metadata

# Dynamically set sqlalchemy.url from environment variable or app.config
database_url = os.getenv("DATABASE_URL")
if not database_url:
    try:
        from app.config import get_settings
        database_url = get_settings().DATABASE_URL
    except Exception:
        database_url = None

if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    Emits SQL statements directly without establishing a live database connection.
    """
    url = config.get_main_option("sqlalchemy.url")
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
    """
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
