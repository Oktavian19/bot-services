"""
Service untuk pemantauan konektivitas jaringan server dan eksekusi speedtest.
"""

import asyncio
from datetime import datetime
import subprocess
from typing import Optional
from aiogram import Bot
from app.core.logger import logger

speedtest_lock = asyncio.Lock()


async def check_connection_async() -> bool:
    """Mengecek apakah server terhubung ke internet via socket non-blocking ke 1.1.1.1:53."""
    try:
        loop = asyncio.get_running_loop()
        # Non-blocking connection check ke Cloudflare DNS port 53
        _, writer = await asyncio.wait_for(
            loop.open_connection("1.1.1.1", 53),
            timeout=3.0,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def run_speedtest_async() -> tuple[bool, str]:
    """
    Menjalankan Ookla CLI speedtest secara asinkron dengan proteksi concurrency lock dan timeout 60 detik.
    Mengembalikan (success: bool, output_or_error: str).
    """
    if speedtest_lock.locked():
        return False, "⏳ Speedtest sedang berjalan oleh pengguna lain/proses sebelumnya. Silakan tunggu hingga selesai."

    async with speedtest_lock:
        try:
            process = await asyncio.create_subprocess_exec(
                "speedtest",
                "--accept-license",
                "--accept-gdpr",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                logger.warning("[JARINGAN - TIMEOUT] Proses Speedtest dihentikan paksa (>60 detik).")
                return False, "❌ Speedtest gagal karena batas waktu (Timeout > 60 detik)."

            if process.returncode == 0:
                output = stdout_data.decode("utf-8", errors="replace").strip()
                return True, output
            else:
                err = stderr_data.decode("utf-8", errors="replace").strip()
                logger.error(f"[JARINGAN - ERROR] Speedtest exit code {process.returncode}: {err}")
                return False, f"❌ <b>Gagal melakukan Speedtest:</b>\n<pre><code>{err}</code></pre>"

        except FileNotFoundError:
            logger.error("[JARINGAN - FATAL] Binary 'speedtest' tidak ditemukan di OS.")
            return False, "❌ Paket <b>Speedtest</b> tidak ditemukan di server. Pastikan sudah terinstall."
        except Exception as e:
            logger.error(f"[JARINGAN - FATAL] Error internal speedtest: {e}")
            return False, f"❌ Terjadi error internal:\n<code>{e}</code>"


async def network_monitor_task(bot: Bot, admin_chat_id: Optional[int]) -> None:
    """
    Background worker yang berjalan terus menerus untuk memantau status jaringan server.
    Jika koneksi terputus lalu pulih setelah >= 3 kali gagal, mengirim pesan notifikasi ke admin.
    """
    if not admin_chat_id:
        logger.warning("[JARINGAN] ADMIN_CHAT_ID tidak diatur; monitoring notifikasi dimatikan.")
        return

    was_connected = True
    downtime_start: Optional[datetime] = None
    fail_count = 0
    toleransi_gagal = 3

    logger.info("[JARINGAN] Background network monitor loop dimulai.")

    while True:
        try:
            is_connected = await check_connection_async()

            if is_connected:
                fail_count = 0
                if not was_connected and downtime_start:
                    downtime_end = datetime.now()
                    durasi = downtime_end - downtime_start
                    menit_mati = durasi.total_seconds() / 60

                    await asyncio.sleep(5)  # Beri jeda sejenak agar koneksi benar-benar stabil

                    msg = (
                        f"🔄 <b>Koneksi Server Pulih!</b>\n\n"
                        f"Server sempat terputus dari internet sejak:\n"
                        f"⏱ <code>{downtime_start.strftime('%H:%M:%S')}</code>\n\n"
                        f"Durasi terputus: <b>{menit_mati:.1f} menit</b>."
                    )

                    try:
                        await bot.send_message(admin_chat_id, msg, parse_mode="HTML")
                        logger.info(f"[{downtime_end.strftime('%H:%M:%S')}] Jaringan pulih, notifikasi terkirim.")
                    except Exception as e:
                        logger.error(f"Gagal kirim notifikasi jaringan: {e}")

                    was_connected = True
                    downtime_start = None
            else:
                fail_count += 1
                if fail_count >= toleransi_gagal and was_connected:
                    downtime_start = datetime.now()
                    logger.warning(f"[{downtime_start.strftime('%H:%M:%S')}] Jaringan terputus! Menunggu pemulihan...")
                    was_connected = False

            await asyncio.sleep(90 if was_connected else 15)

        except asyncio.CancelledError:
            logger.info("[JARINGAN] Background network monitor task dibatalkan (Shutdown).")
            break
        except Exception as e:
            logger.error(f"[JARINGAN] Error loop jaringan: {e}")
            await asyncio.sleep(15)

