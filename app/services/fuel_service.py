"""
Service bisnis untuk modul Konsumsi BBM dan Motor.
Menangani perakitan pesan dasbor, kalkulasi konsumsi, status interval oli, dan detail riwayat.
"""

from typing import Any, Optional


def render_fuel_hub_text(motor: Optional[dict[str, Any]], stats: dict[str, float], status_oli: Optional[dict[str, Any]]) -> str:
    """Menyusun teks HTML untuk menu utama dasbor /bensin."""
    if not motor:
        return (
            "🏍 <b>Manajemen Bensin & Motor</b>\n\n"
            "Anda belum mendaftarkan motor. Silakan daftarkan terlebih dahulu untuk melacak konsumsi BBM dan jadwal ganti oli."
        )

    nama_motor = motor["nama_motor"]
    odo_awal = motor["odometer_awal"]
    odo_akhir = motor["odometer_terakhir"]
    total_jarak = odo_akhir - odo_awal

    if stats.get("rata_rata", 0) > 0:
        teks_kml = (
            f"📊 <b>Rata-rata BBM:</b> {stats['rata_rata']:.2f} km/L\n"
            f"📈 <b>Konsumsi Terakhir:</b> {stats['terakhir']:.2f} km/L\n\n"
        )
    else:
        teks_kml = "📊 <b>Data Konsumsi:</b> Belum ada riwayat pengisian bensin.\n\n"

    if not status_oli or status_oli["status"] == "belum_diatur":
        teks_oli = "🛢 <b>Status Oli:</b> ⚠️ Belum diatur (Klik 'Cek & Atur Oli')\n\n"
    elif status_oli["status"] == "aman":
        teks_oli = f"🛢 <b>Status Oli:</b> 🟢 Aman (Sisa {status_oli['sisa_km']:.0f} km menuju {status_oli['target_oli']:.0f} km)\n\n"
    elif status_oli["status"] == "mendekati":
        teks_oli = f"🛢 <b>Status Oli:</b> ⚠️ <b>Mendekati Ganti Oli!</b> (Sisa {status_oli['sisa_km']:.0f} km menuju {status_oli['target_oli']:.0f} km)\n\n"
    else:
        teks_oli = f"🛢 <b>Status Oli:</b> 🚨 <b>SUDAH MELEWATI JADWAL!</b> (Terlewat {abs(status_oli['sisa_km']):.0f} km dari {status_oli['target_oli']:.0f} km)\n\n"

    return (
        f"🏍 <b>Manajemen Motor: {nama_motor}</b>\n\n"
        f"📟 <b>Odometer Awal:</b> {odo_awal:.1f} km\n"
        f"📟 <b>Odometer Terakhir:</b> {odo_akhir:.1f} km\n"
        f"🛣 <b>Total Terpantau:</b> {total_jarak:.1f} km\n\n"
        f"{teks_kml}"
        f"{teks_oli}"
        f"Silakan pilih menu di bawah ini:"
    )


def render_log_detail_text(log: dict[str, Any]) -> str:
    """Menyusun teks detail satu log pengisian bensin."""
    log_id = log["id"]
    odo = log["odometer"]
    rupiah = log["rupiah"]
    liter = log["liter"]
    jarak = log["jarak_tempuh"]
    kml = log["konsumsi_kml"]
    tgl = log["tanggal"]

    if odo is None:
        odo_teks = "- (Tanpa Odometer)"
        jarak_teks = "- (Belum ada odo)"
        kml_teks = "- (Menunggu odo berikutnya)"
    else:
        odo_teks = f"{odo:.1f} km"
        jarak_teks = f"{jarak:.1f} km"
        kml_teks = f"{kml:.2f} km/L"

    return (
        f"📝 <b>Detail Log Bensin #{log_id}</b>\n\n"
        f"📅 <b>Tanggal:</b> {tgl}\n"
        f"📟 <b>Odometer:</b> {odo_teks}\n"
        f"💰 <b>Biaya:</b> Rp{rupiah:,}\n"
        f"💧 <b>Volume:</b> {liter:.2f} Liter\n"
        f"🛣 <b>Jarak Tempuh:</b> {jarak_teks}\n"
        f"📊 <b>Konsumsi:</b> {kml_teks}"
    )


def render_oil_menu_text(status_oli: dict[str, Any]) -> str:
    """Menyusun teks status & jadwal ganti oli motor."""
    if status_oli["status"] == "belum_diatur":
        return (
            f"🛢 <b>Informasi & Pengingat Ganti Oli</b>\n\n"
            f"⚠️ <b>Status:</b> Belum diatur.\n"
            f"📟 <b>Odometer Motor Saat Ini:</b> {status_oli['odo_sekarang']:.1f} km\n\n"
            f"<i>Silakan atur kilometer saat terakhir ganti oli agar bot dapat memantau jadwal penggantian oli setiap 3.000 km.</i>"
        )

    terakhir_oli = status_oli["terakhir_oli"]
    target_oli = status_oli["target_oli"]
    odo_sekarang = status_oli["odo_sekarang"]
    jarak_sejak = status_oli["jarak_sejak_oli"]
    sisa_km = status_oli["sisa_km"]

    if status_oli["status"] == "aman":
        badge_status = f"🟢 <b>Aman</b> (Sisa {sisa_km:.0f} km)"
    elif status_oli["status"] == "mendekati":
        badge_status = f"⚠️ <b>Mendekati Jadwal!</b> (Sisa {sisa_km:.0f} km)"
    else:
        badge_status = f"🚨 <b>SUDAH MELEWATI JADWAL!</b> (Terlewat {abs(sisa_km):.0f} km)"

    return (
        f"🛢 <b>Informasi & Pengingat Ganti Oli</b>\n\n"
        f"📊 <b>Status:</b> {badge_status}\n"
        f"📟 <b>Odometer Motor Saat Ini:</b> {odo_sekarang:.1f} km\n"
        f"🔧 <b>Terakhir Ganti Oli:</b> {terakhir_oli:.1f} km\n"
        f"🎯 <b>Jadwal Ganti Oli Berikutnya:</b> {target_oli:.1f} km\n"
        f"🛣 <b>Jarak Sejak Ganti Oli:</b> {jarak_sejak:.1f} km\n\n"
        f"<i>Jadwal ganti oli dihitung setiap 3.000 km dari kilometer ganti oli terakhir.</i>"
    )

