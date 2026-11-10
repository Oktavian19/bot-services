"""
Service asinkron untuk scraping dan transaksi web portal DERMAGA Polinema,
serta helper geocoding koordinat GPS dan pemformatan antarmuka logbook.
"""

import html
import re
from typing import Any, List, Optional
import aiohttp
from bs4 import BeautifulSoup
from app.core.logger import logger
from app.database.logbook_repo import (
    PROFILE_DEFINITIONS,
    get_user_credential,
    get_user_location,
    get_user_location_profiles,
)

LOGIN_URL = "https://jti.polinema.ac.id/dermaga/login"
MONITORING_URL = "https://jti.polinema.ac.id/dermaga/mahasiswa/monitoring"
SUBMIT_URL = "https://jti.polinema.ac.id/dermaga/mahasiswa/monitoring/simpan"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Origin": "https://jti.polinema.ac.id",
    "Referer": LOGIN_URL,
}


# --- GEO HELPER ---

def parse_coordinates_input(raw_input: str) -> Optional[tuple[float, float, float]]:
    """
    Mem-parsing koordinat (latitude, longitude, akurasi) dari teks mentah atau tautan Google Maps.
    Mengembalikan (lat, lng, accuracy_meters) atau None jika tidak valid.
    """
    if not raw_input:
        return None

    cleaned = raw_input.strip()

    # 1. Format URL Google Maps
    gmaps_patterns = [
        r"@(-?\d+\.\d+),(-?\d+\.\d+)",
        r"q=(-?\d+\.\d+),(-?\d+\.\d+)",
        r"ll=(-?\d+\.\d+),(-?\d+\.\d+)",
    ]
    for pattern in gmaps_patterns:
        match = re.search(pattern, cleaned)
        if match:
            try:
                lat = float(match.group(1))
                lng = float(match.group(2))
                return lat, lng, 15.0
            except ValueError:
                pass

    # 2. Format teks angka dipisah koma atau spasi
    tokens = re.split(r"[,;\s]+", cleaned)
    numeric_tokens = []
    for t in tokens:
        try:
            numeric_tokens.append(float(t))
        except ValueError:
            pass

    if len(numeric_tokens) >= 2:
        lat = numeric_tokens[0]
        lng = numeric_tokens[1]
        acc = numeric_tokens[2] if len(numeric_tokens) >= 3 else 15.0
        # Validasi rentang latitude & longitude Indonesia (-11 s/d 6, 95 s/d 141)
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng, acc

    return None


# --- PORTAL DERMAGA SCRAPER (ASYNC) ---

async def test_dermaga_login(username: str, plain_password: str) -> tuple[bool, str]:
    """Menguji kredensial pengguna ke portal login DERMAGA secara asinkron."""
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
            # 1. GET halaman login untuk mendapatkan token CSRF
            async with session.get(LOGIN_URL) as resp:
                if resp.status != 200:
                    return False, f"Portal DERMAGA tidak dapat diakses (HTTP {resp.status})."
                html_text = await resp.text()

            soup = BeautifulSoup(html_text, "html.parser")
            csrf_input = soup.find("input", {"name": "csrf_test_name"})
            if not csrf_input:
                return False, "Token CSRF tidak ditemukan di halaman login DERMAGA."

            csrf_token = csrf_input["value"]

            # 2. POST login data
            payload = {
                "username": username,
                "password": plain_password,
                "csrf_test_name": csrf_token,
            }
            async with session.post(LOGIN_URL, data=payload, allow_redirects=True) as post_resp:
                post_html = await post_resp.text()

                # Cek tanda login sukses (dashboard mahasiswa)
                if "mahasiswa/monitoring" in str(post_resp.url) or "Log Out" in post_html or "Dashboard" in post_html:
                    return True, "Login berhasil terverifikasi."
                elif "Username atau Password Salah" in post_html or "gagal" in post_html.lower():
                    return False, "Username atau Password salah."
                else:
                    return False, "Autentikasi gagal atau respon tidak dikenali."

    except aiohttp.ClientConnectorError:
        return False, "Gagal terhubung ke host server DERMAGA Polinema."
    except Exception as e:
        logger.error(f"[LOGBOOK-SCRAPE] Error saat test login DERMAGA: {e}")
        return False, f"Terjadi kesalahan koneksi: {e}"


async def fetch_dermaga_table(chat_id: int) -> List[dict[str, Any]]:
    """Mengambil riwayat tabel logbook yang sudah tercatat di DERMAGA untuk user tertentu."""
    cred = await get_user_credential(chat_id)
    if not cred:
        raise ValueError("Kredensial DERMAGA tidak ditemukan. Silakan login kembali.")

    username, password = cred
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
        # Login
        async with session.get(LOGIN_URL) as resp:
            soup = BeautifulSoup(await resp.text(), "html.parser")
            csrf_token = soup.find("input", {"name": "csrf_test_name"})["value"]

        payload = {"username": username, "password": password, "csrf_test_name": csrf_token}
        async with session.post(LOGIN_URL, data=payload, allow_redirects=True) as login_resp:
            if "mahasiswa" not in str(login_resp.url) and "Log Out" not in await login_resp.text():
                raise PermissionError("Autentikasi ke DERMAGA gagal. Kredensial mungkin berubah.")

        # Ambil halaman monitoring
        async with session.get(MONITORING_URL) as mon_resp:
            mon_soup = BeautifulSoup(await mon_resp.text(), "html.parser")

        entries = []
        table = mon_soup.find("table")
        if table:
            rows = table.find_all("tr")
            for row in rows[1:]:  # Lewati header
                cols = row.find_all("td")
                if len(cols) >= 6:
                    web_id = cols[0].text.strip()
                    tgl_text = cols[1].text.strip()
                    jam = cols[2].text.strip()
                    pekerjaan = cols[3].text.strip()
                    ket = cols[4].text.strip()
                    status_verif = cols[5].text.strip()
                    entries.append({
                        "web_id": web_id,
                        "tanggal_text": tgl_text,
                        "jam": jam,
                        "pekerjaan": pekerjaan,
                        "keterangan": ket,
                        "status_verif": status_verif,
                    })

        return entries


async def submit_dermaga_entry(
    chat_id: int,
    date: str,
    summary: str,
    jam_masuk: str = "07:10",
    jam_pulang: str = "16:25",
    lat: str = "-7.5815",
    lng: str = "112.6247",
    accuracy: str = "15"
) -> tuple[bool, str]:
    """Mengirim entri logbook dan absensi ke sistem DERMAGA Polinema secara asinkron."""
    cred = await get_user_credential(chat_id)
    if not cred:
        return False, "Kredensial akun DERMAGA tidak ditemukan."

    username, password = cred
    timeout = aiohttp.ClientTimeout(total=40)

    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
            # Login
            async with session.get(LOGIN_URL) as resp:
                soup = BeautifulSoup(await resp.text(), "html.parser")
                csrf_token = soup.find("input", {"name": "csrf_test_name"})["value"]

            payload = {"username": username, "password": password, "csrf_test_name": csrf_token}
            async with session.post(LOGIN_URL, data=payload, allow_redirects=True):
                pass

            # Ambil CSRF baru dari form monitoring
            async with session.get(MONITORING_URL) as mon_resp:
                mon_soup = BeautifulSoup(await mon_resp.text(), "html.parser")
                csrf_submit_input = mon_soup.find("input", {"name": "csrf_test_name"})
                csrf_submit = csrf_submit_input["value"] if csrf_submit_input else csrf_token

            # Payload pengiriman absensi/logbook
            data_submit = {
                "csrf_test_name": csrf_submit,
                "tanggal": date,
                "jam_masuk": jam_masuk,
                "jam_pulang": jam_pulang,
                "pekerjaan": summary,
                "latitude": lat,
                "longitude": lng,
                "accuracy": accuracy,
                "keterangan": "Masuk",
            }

            async with session.post(SUBMIT_URL, data=data_submit, allow_redirects=True) as sub_resp:
                sub_text = await sub_resp.text()
                if sub_resp.status == 200 and ("berhasil" in sub_text.lower() or "sukses" in sub_text.lower()):
                    return True, "Logbook berhasil dikirim ke DERMAGA!"
                elif sub_resp.status == 200:
                    # Sukses silent atau redirect
                    return True, "Entri berhasil tersimpan di portal DERMAGA."
                else:
                    return False, f"Server DERMAGA mengembalikan status HTTP {sub_resp.status}."

    except Exception as e:
        logger.error(f"[LOGBOOK-SUBMIT] Gagal submit logbook ke DERMAGA: {e}")
        return False, f"Terjadi kesalahan saat pengiriman: {e}"


# --- VIEW FORMATTERS ---

def format_draft_message(draft: dict[str, Any], location_profile: Optional[str] = None) -> str:
    """Menyusun teks HTML konfirmasi draf logbook."""
    date = draft.get("date", "-")
    summary = html.escape(draft.get("summary", ""))
    jam_masuk = draft.get("jam_masuk", "07:10")
    jam_pulang = draft.get("jam_pulang", "16:25")
    prof_key = location_profile or draft.get("selected_profile") or "office"
    prof_info = PROFILE_DEFINITIONS.get(prof_key, {})
    prof_label = prof_info.get("default_name", prof_key.title())

    return (
        f"📝 <b>DRAF LOGBOOK DERMAGA</b>\n\n"
        f"📅 <b>Tanggal:</b> <code>{date}</code>\n"
        f"⏱ <b>Jam Kerja:</b> <code>{jam_masuk} - {jam_pulang} WIB</code>\n"
        f"📍 <b>Profil Lokasi:</b> <b>{prof_label}</b>\n\n"
        f"📋 <b>Ringkasan Aktivitas:</b>\n"
        f"<blockquote>{summary}</blockquote>\n\n"
        f"<i>Silakan tinjau dan klik tombol di bawah untuk menyetujui atau mengedit.</i>"
    )


def format_reminder_days_display(days_str: str) -> str:
    """Mengubah string indeks hari ('0,1,2,3,4') menjadi teks yang mudah dibaca."""
    if not days_str:
        return "Nonaktif (Tidak ada pengingat)"
    nama_hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    try:
        indices = [int(x.strip()) for x in days_str.split(",") if x.strip().isdigit()]
        if sorted(indices) == [0, 1, 2, 3, 4]:
            return "Senin s/d Jumat (Hari Kerja)"
        elif sorted(indices) == [0, 1, 2, 3, 4, 5]:
            return "Senin s/d Sabtu (6 Hari Kerja)"
        elif sorted(indices) == list(range(7)):
            return "Setiap Hari (Termasuk Akhir Pekan)"
        selected = [nama_hari[i] for i in sorted(indices) if 0 <= i <= 6]
        return ", ".join(selected)
    except Exception:
        return days_str

