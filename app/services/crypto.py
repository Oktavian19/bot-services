"""
Modul enkripsi simetris Fernet untuk mengamankan password di database.
"""

from typing import Optional
from cryptography.fernet import Fernet
from app.core.config import get_settings
from app.core.logger import logger


def get_fernet_suite(custom_key: Optional[str] = None) -> Fernet:
    """Mengembalikan instance cipher Fernet."""
    settings = get_settings()
    key_str = custom_key or settings.effective_logbook_secret_key
    if not key_str:
        raise ValueError(
            "MAGANG_SECRET_KEY atau LOGBOOK_SECRET_KEY belum dikonfigurasi di environment!"
        )
    key_bytes = key_str.strip().encode()
    return Fernet(key_bytes)


def encrypt_text(plain_text: str, custom_key: Optional[str] = None) -> str:
    """Mengenkripsi teks biasa menjadi ciphertext Fernet string."""
    try:
        suite = get_fernet_suite(custom_key)
        return suite.encrypt(plain_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"[CRYPTO] Gagal enkripsi teks: {e}")
        raise


def decrypt_text(cipher_text: str, custom_key: Optional[str] = None) -> str:
    """Mendekripsi ciphertext Fernet string menjadi teks biasa."""
    try:
        suite = get_fernet_suite(custom_key)
        return suite.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"[CRYPTO] Gagal dekripsi teks: {e}")
        raise

