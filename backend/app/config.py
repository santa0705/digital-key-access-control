from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve repository root where .env is stored
# config.py -> app (parent) -> backend (parent) -> root (parent)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = ROOT_DIR / ".env"


class Settings(BaseSettings):
    """
    Application settings loaded from the repository root .env file.
    Follows Digital Key-Based Secure Access Control specification.
    """
    # PostgreSQL connection string (SQLAlchemy 2 + psycopg 3)
    DATABASE_URL: str = (
        "postgresql+psycopg://digital_key_user:placeholder@localhost:5432/digital_key"
    )

    # Migration safety guard settings (fail-closed by default)
    ALLOW_LOCAL_MIGRATION: bool = False
    APPROVED_MIGRATION_HOSTS: str = "localhost,127.0.0.1,::1"
    APPROVED_MIGRATION_PORTS: str = "5432"
    APPROVED_MIGRATION_DB_NAMES: str = "digital_key"
    APPROVED_MIGRATION_USERS: str = ""

    # Authentication & cryptographic keys
    JWT_SECRET: str = "replace_with_generated_jwt_secret_hex_32_bytes"
    PIN_HMAC_KEY: str = "replace_with_generated_hmac_key_hex_32_bytes"
    PIN_ENC_KEY: str = "replace_with_generated_fernet_key_base64_32_bytes"
    DEVICE_API_KEY: str = "replace_with_generated_device_api_key"

    # CORS origins (comma-separated string in .env)
    CORS_ORIGINS: str = "http://localhost:5173"

    # Fixed architectural constants (defined in code, not in .env)
    SYNC_PAGE_SIZE: int = 8
    EVENT_BATCH_MAX: int = 20
    ONLINE_WINDOW_S: int = 45

    model_config = SettingsConfigDict(
        env_file=(str(ENV_FILE_PATH), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
