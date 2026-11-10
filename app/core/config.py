"""
Modul konfigurasi aplikasi menggunakan Pydantic Settings.
Menyediakan validasi tipe data ketat dan pembacaan otomatis dari environment/file .env.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.bot"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # --- BOT CONFIGURATION ---
    TELEGRAM_TOKEN: str = Field(..., description="Token bot Telegram dari @BotFather")
    ADMIN_CHAT_ID: Optional[int] = Field(None, description="Chat ID Telegram Administrator")

    # --- CRYPTOGRAPHY ---
    MAGANG_SECRET_KEY: Optional[str] = Field(None, description="Fernet key untuk enkripsi modul magang")
    LOGBOOK_SECRET_KEY: Optional[str] = Field(None, description="Fernet key untuk enkripsi modul logbook")

    # --- LOGBOOK HTTP API & PORTAL ---
    LOGBOOK_API_PORT: int = Field(8088, description="Port listener HTTP receiver logbook")
    LOGBOOK_API_HOST: str = Field("0.0.0.0", description="Host listener HTTP receiver logbook")
    LOGBOOK_PUBLIC_URL: str = Field("http://127.0.0.1:8088/api/logbook", description="URL publik API logbook")
    LOGBOOK_API_TOKEN: Optional[str] = Field(None, description="Token API master fallback untuk CLI")

    # --- DATABASE PATHS ---
    REMINDER_DB_PATH: Path = Field(
        default_factory=lambda: Path("data/reminders.db"),
        description="Path database SQLite untuk reminder"
    )
    BENSIN_DB_PATH: Path = Field(
        default_factory=lambda: Path("data/bensin.db"),
        description="Path database SQLite untuk bensin"
    )
    LOGBOOK_DB_PATH: Path = Field(
        default_factory=lambda: Path("data/logbook.db"),
        description="Path database SQLite untuk logbook"
    )
    MAGANG_DB_PATH: Path = Field(
        default_factory=lambda: Path("data/users.db"),
        description="Path database SQLite untuk magang"
    )

    # --- LOGGING & TIMEZONE ---
    LOG_LEVEL: str = Field("INFO", description="Level logging (DEBUG, INFO, WARNING, ERROR)")
    LOG_FILE_PATH: Path = Field(
        default_factory=lambda: Path("logs/bot.log"),
        description="Path file log rotasi loguru"
    )
    TIMEZONE: str = Field("Asia/Jakarta", description="Zona waktu bot")

    @field_validator("ADMIN_CHAT_ID", mode="before")
    @classmethod
    def parse_admin_chat_id(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip("'\" ")
            if not v:
                return None
            return int(v)
        return int(v)

    @property
    def effective_logbook_secret_key(self) -> Optional[str]:
        """Mengambil kunci rahasia logbook, fallback ke MAGANG_SECRET_KEY bila belum diatur."""
        return self.LOGBOOK_SECRET_KEY or self.MAGANG_SECRET_KEY


_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """Singleton getter untuk instance Settings."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def set_settings(custom_settings: Optional[Settings] = None) -> None:
    """Mengatur atau mereset instance singleton Settings (terutama untuk testing)."""
    global _settings_instance
    _settings_instance = custom_settings

