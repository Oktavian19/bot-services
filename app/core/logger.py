"""
Konfigurasi logging terpusat menggunakan Loguru.
Mendukung format terstruktur, rotasi file log otomatis, dan interseptor logging standar Python.
"""

import logging
import sys
from pathlib import Path
from loguru import logger
from app.core.config import get_settings


class InterceptHandler(logging.Handler):
    """
    Handler standar logging Python yang meneruskan semua log ke Loguru sink.
    Memungkinkan library eksternal (aiogram, aiohttp, apscheduler) terpusat di Loguru.
    """
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logger() -> None:
    """Menginisialisasi konfigurasi Loguru sink dan standard logging interception."""
    settings = get_settings()

    # Hapus handler bawaan Loguru
    logger.remove()

    # Format log console
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Sink Console
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=console_format,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # Sink File (Rotasi 10 MB, Retensi 10 Hari)
    log_file: Path = settings.LOG_FILE_PATH
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{name}:{function}:{line} - {message}"
    )

    logger.add(
        str(log_file),
        level=settings.LOG_LEVEL,
        format=file_format,
        rotation="10 MB",
        retention="10 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,  # Thread-safe / async-safe
    )

    # Alihkan standard logging ke Loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for lib in ("aiogram", "aiohttp", "apscheduler", "asyncio"):
        logging.getLogger(lib).handlers = [InterceptHandler()]
        logging.getLogger(lib).propagate = False

