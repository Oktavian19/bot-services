"""
Service asinkron untuk scraping dan transaksi web portal DERMAGA Polinema,
serta helper geocoding koordinat GPS dan pemformatan antarmuka logbook.
"""

import html
import json
import math
import random
import re
import time
from typing import Any, List, Optional
import aiohttp
from bs4 import BeautifulSoup
from app.core.logger import logger
from app.database.logbook_repo import (
    DEFAULT_ACCURACY,
    DEFAULT_LAT,
    DEFAULT_LNG,
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


def apply_gps_jitter(
    lat_str: str,
    lng_str: str,
    min_radius_m: float = 2.0,
    max_radius_m: float = 5.0,
) -> tuple[str, str, str, float]:
    """
    Menghasilkan koordinat realistis dengan deviasi acak (micro-jitter) radius 2-5 meter
    dan akurasi natural 8-15 meter untuk mensimulasikan GPS perangkat nyata.
    """
    try:
        lat0 = float(lat_str)
        lng0 = float(lng_str)
    except (ValueError, TypeError):
        return str(lat_str), str(lng_str), str(DEFAULT_ACCURACY), 0.0

    r = random.uniform(min_radius_m, max_radius_m)
    theta = random.uniform(0.0, 2.0 * math.pi)

    dx = r * math.cos(theta)
    dy = r * math.sin(theta)

    meters_per_deg_lat = 111139.0
    meters_per_deg_lng = 111139.0 * math.cos(math.radians(lat0))
    if abs(meters_per_deg_lng) < 1e-6:
        meters_per_deg_lng = 111139.0

    d_lat = dy / meters_per_deg_lat
    d_lng = dx / meters_per_deg_lng

    jittered_lat = f"{lat0 + d_lat:.6f}"
    jittered_lng = f"{lng0 + d_lng:.6f}"
    jittered_akurasi = str(random.randint(8, 15))

    return jittered_lat, jittered_lng, jittered_akurasi, r


def extract_feedback_message(html_text: str) -> tuple[Optional[bool], str]:
    """Mengekstrak notifikasi SweetAlert atau script notify dari HTML response DERMAGA."""
    if not html_text:
        return None, ""

    soup = BeautifulSoup(html_text, "html.parser")
    for s in soup.find_all("script"):
        txt = s.string or s.text or ""
        if "notify(" in txt:
            if "notify('success'" in txt or 'notify("success"' in txt:
                m = re.search(r'notify\(\s*[\'"]success[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]', txt)
                return True, m.group(1) if m else "Logbook berhasil disimpan."
            elif "notify('error'" in txt or 'notify("error"' in txt or "notify('warning'" in txt:
                m = re.search(r'notify\(\s*[\'"][^\'"]+[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]', txt)
                return False, m.group(1) if m else "Gagal menyimpan logbook."

        if "Swal.fire" in txt:
            m_icon = re.search(r'icon:\s*[\'"]([^\'"]+)[\'"]', txt)
            m_title = re.search(r'title:\s*[\'"]([^\'"]+)[\'"]', txt)
            m_html = re.search(r'html:\s*[\'"]([^\'"]+)[\'"]', txt)
            icon = m_icon.group(1) if m_icon else "warning"
            title = m_title.group(1) if m_title else "Peringatan"
            detail = m_html.group(1) if m_html else ""
            clean_detail = re.sub(r"<[^>]+>", " ", detail).strip()
            msg = f"{title}: {clean_detail}" if clean_detail else title
            return (False if icon in ["warning", "error"] else True), msg

    for alert in soup.find_all(class_=lambda c: c and ("alert-danger" in c or "alert-warning" in c)):
        classes = alert.get("class", [])
        if "d-none" not in classes:
            txt = alert.get_text(strip=True)
            if txt:
                return False, txt

    return None, ""



MONTH_NAMES = {
    "01": "Januari", "02": "Februari", "03": "Maret", "04": "April",
    "05": "Mei", "06": "Juni", "07": "Juli", "08": "Agustus",
    "09": "September", "10": "Oktober", "11": "November", "12": "Desember"
}

MONTH_SHORT = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "Mei", "06": "Jun", "07": "Jul", "08": "Agu",
    "09": "Sep", "10": "Okt", "11": "Nov", "12": "Des"
}


def validate_time_format(time_str: str) -> bool:
    """Memvalidasi format 24 jam HH:MM (00:00 s/d 23:59)."""
    try:
        parts = time_str.strip().split(":")
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        return False


def format_month_name(ym: str) -> str:
    """Mengubah format YYYY-MM menjadi nama bulan (contoh: 2026-11 -> November 2026)."""
    try:
        parts = ym.split("-")
        if len(parts) == 2:
            return f"{MONTH_NAMES.get(parts[1], parts[1])} {parts[0]}"
    except Exception:
        pass
    return ym


def format_short_date(tanggal_iso: str) -> str:
    """Mengubah format YYYY-MM-DD menjadi label pendek (contoh: 2026-11-04 -> 04 Nov)."""
    try:
        parts = tanggal_iso.split("-")
        if len(parts) == 3:
            return f"{parts[2]} {MONTH_SHORT.get(parts[1], parts[1])}"
    except Exception:
        pass
    return tanggal_iso


def group_entries_by_month(entries: list) -> dict[str, list]:
    """Mengelompokkan entri logbook DERMAGA berdasarkan YYYY-MM."""
    grouped: dict[str, list] = {}
    for e in entries:
        tgl = e.get("tanggal_iso", "") or e.get("tanggal_text", "")
        ym = tgl[:7] if (len(tgl) >= 7 and "-" in tgl) else "Lainnya"
        if ym not in grouped:
            grouped[ym] = []
        grouped[ym].append(e)
    return grouped


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
                    btn_edit = row.find(class_="btn-edit")
                    web_id = (btn_edit.get("data-id") if btn_edit else None) or cols[0].text.strip()
                    btn_tgl = btn_edit.get("data-tanggal") if btn_edit else None
                    btn_masuk = btn_edit.get("data-masuk") if btn_edit else None
                    btn_pulang = btn_edit.get("data-pulang") if btn_edit else None
                    btn_desk = btn_edit.get("data-deskripsi") if btn_edit else None
                    btn_ket = btn_edit.get("data-keterangan") if btn_edit else None

                    tgl_order = cols[0].get("data-order") or ""
                    tgl_text = cols[1].text.strip() if len(cols) >= 6 else cols[0].text.strip()
                    jam_text = cols[2].text.strip() if len(cols) >= 6 else ""

                    final_tgl_iso = btn_tgl or tgl_order or tgl_text
                    final_masuk = btn_masuk or (jam_text.split("-")[0].strip() if "-" in jam_text else "07:10")
                    final_pulang = btn_pulang or (jam_text.split("-")[1].strip() if "-" in jam_text else "16:25")
                    final_deskripsi = btn_desk or cols[3].text.strip()
                    final_keterangan = btn_ket or cols[4].text.strip()
                    status_verif = cols[5].text.strip() if len(cols) >= 6 else ""

                    entries.append({
                        "web_id": web_id,
                        "tanggal_iso": final_tgl_iso,
                        "tanggal_text": tgl_text,
                        "jam_masuk": final_masuk,
                        "jam_pulang": final_pulang,
                        "jam": f"{final_masuk} - {final_pulang}",
                        "pekerjaan": final_deskripsi,
                        "keterangan": final_keterangan,
                        "status_verif": status_verif,
                    })

        return entries


def parse_weekly_cards_from_html(html_text: str) -> List[dict[str, Any]]:
    """Mengekstrak data seluruh kartu minggu (minggu-card) dari HTML halaman monitoring DERMAGA."""
    soup = BeautifulSoup(html_text, "html.parser")
    cards = soup.find_all(class_="minggu-card")
    results = []
    seen = set()

    for card in cards:
        data_awal = card.get("data-awal", "").strip()
        lbl_elem = card.find(class_="minggu-label")
        label = lbl_elem.get_text(strip=True) if lbl_elem else ""

        # Dedup jika elemen terduplikasi pada DOM
        card_key = (data_awal, label)
        if card_key in seen:
            continue
        seen.add(card_key)

        date_div = card.find(class_="text-muted")
        rentang_tanggal = date_div.get_text(strip=True) if date_div else ""

        # Hitung hari terisi
        hari_terisi = 0
        for d in card.find_all("div"):
            if "hari terisi" in d.text:
                m = re.search(r"(\d+)\s*hari", d.text)
                if m:
                    hari_terisi = int(m.group(1))
                break

        # Ambil status badge
        status = "Belum diajukan"
        badges = card.find_all(class_="badge")
        for b in badges:
            txt = b.get_text(strip=True)
            if txt != "Minggu ini":
                status = txt
                break

        results.append({
            "label": label,
            "data_awal": data_awal,
            "rentang_tanggal": rentang_tanggal,
            "hari_terisi": hari_terisi,
            "status": status,
            "is_minggu_ini": "minggu-berjalan" in card.get("class", []),
        })

    return results


async def fetch_weekly_logbook_cards(chat_id: int) -> List[dict[str, Any]]:
    """Mengambil daftar kartu minggu (minggu-card) dari slider di portal DERMAGA secara asinkron."""
    cred = await get_user_credential(chat_id)
    if not cred:
        raise ValueError("Kredensial DERMAGA tidak ditemukan. Silakan login kembali.")

    username, password = cred
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
        # 1. Login
        async with session.get(LOGIN_URL) as resp:
            soup = BeautifulSoup(await resp.text(), "html.parser")
            csrf_token = soup.find("input", {"name": "csrf_test_name"})["value"]

        payload = {"username": username, "password": password, "csrf_test_name": csrf_token}
        async with session.post(LOGIN_URL, data=payload, allow_redirects=True) as login_resp:
            if "mahasiswa" not in str(login_resp.url) and "Log Out" not in await login_resp.text():
                raise PermissionError("Autentikasi ke DERMAGA gagal. Kredensial mungkin berubah.")

        # 2. Ambil halaman monitoring
        async with session.get(MONITORING_URL) as mon_resp:
            mon_html = await mon_resp.text()

    return parse_weekly_cards_from_html(mon_html)


def parse_weeks_and_parties_from_html(html_text: str) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Mengekstrak data konstanta JavaScript WEEKS dan NAMA_PIHAK dari halaman monitoring DERMAGA.
    Mengembalikan tuple: (weeks_dict, parties_dict).
    """
    weeks_data: dict[str, Any] = {}
    parties: dict[str, str] = {
        "supervisor": "Pembimbing Lapangan",
        "dosen": "Dosen Pembimbing",
    }

    # 1. Ekstrak WEEKS menggunakan JSONDecoder raw_decode untuk parsing robust
    idx = html_text.find("const WEEKS =")
    if idx != -1:
        brace_idx = html_text.find("{", idx)
        if brace_idx != -1:
            try:
                decoder = json.JSONDecoder()
                weeks_data, _ = decoder.raw_decode(html_text[brace_idx:])
            except Exception as e:
                logger.warning(f"[LOGBOOK-SCRAPE] Gagal parse JSON WEEKS via raw_decode: {e}")
                m = re.search(r"const\s+WEEKS\s*=\s*(\{.*?\});", html_text, re.DOTALL)
                if m:
                    try:
                        weeks_data = json.loads(m.group(1))
                    except Exception:
                        pass

    # 2. Ekstrak NAMA_PIHAK
    m_pihak = re.search(r"const\s+NAMA_PIHAK\s*=\s*\{([^}]+)\};", html_text, re.DOTALL)
    if m_pihak:
        content = m_pihak.group(1)
        sup = re.search(r'supervisor:\s*["\']([^"\']+)["\']', content)
        dos = re.search(r'dosen:\s*["\']([^"\']+)["\']', content)
        if sup:
            parties["supervisor"] = sup.group(1).strip()
        if dos:
            parties["dosen"] = dos.group(1).strip()

    return weeks_data, parties


async def fetch_weeks_and_parties(chat_id: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Mengambil dan mengekstrak data WEEKS dan NAMA_PIHAK dari portal DERMAGA secara asinkron."""
    cred = await get_user_credential(chat_id)
    if not cred:
        raise ValueError("Kredensial DERMAGA tidak ditemukan. Silakan login kembali.")

    username, password = cred
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
        # 1. Login
        async with session.get(LOGIN_URL) as resp:
            soup = BeautifulSoup(await resp.text(), "html.parser")
            csrf_token = soup.find("input", {"name": "csrf_test_name"})["value"]

        payload = {"username": username, "password": password, "csrf_test_name": csrf_token}
        async with session.post(LOGIN_URL, data=payload, allow_redirects=True) as login_resp:
            if "mahasiswa" not in str(login_resp.url) and "Log Out" not in await login_resp.text():
                raise PermissionError("Autentikasi ke DERMAGA gagal. Kredensial mungkin berubah.")

        # 2. Ambil halaman monitoring
        async with session.get(MONITORING_URL) as mon_resp:
            mon_html = await mon_resp.text()

    return parse_weeks_and_parties_from_html(mon_html)


_weeks_cache: dict[int, tuple[float, dict[str, Any], dict[str, str]]] = {}


async def get_cached_weeks_and_parties(
    chat_id: int,
    force_refresh: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Mengambil data WEEKS dan NAMA_PIHAK dengan in-memory cache per-chat_id (TTL 5 menit)
    untuk respon cepat saat navigasi kartu minggu.
    """
    now = time.time()
    if not force_refresh and chat_id in _weeks_cache:
        timestamp, cached_weeks, cached_parties = _weeks_cache[chat_id]
        if now - timestamp < 300:  # 5 menit
            return cached_weeks, cached_parties

    weeks_data, parties = await fetch_weeks_and_parties(chat_id)
    _weeks_cache[chat_id] = (now, weeks_data, parties)
    return weeks_data, parties



async def check_monitoring_today(chat_id: int, target_date: str) -> dict[str, Any]:
    """
    Memeriksa halaman monitoring portal DERMAGA secara real-time untuk mengecek
    apakah logbook tanggal target_date sudah diisi.
    Jika web gagal diakses, lakukan fallback pengecekan ke database lokal.
    """
    cred = await get_user_credential(chat_id)
    if not cred:
        return {"exists": False, "entry": None, "error": "Kredensial belum didaftarkan."}

    username, password = cred
    timeout = aiohttp.ClientTimeout(total=20)

    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
            # 1. Login
            async with session.get(LOGIN_URL) as resp:
                soup = BeautifulSoup(await resp.text(), "html.parser")
                csrf_token = soup.find("input", {"name": "csrf_test_name"})["value"]

            payload = {"username": username, "password": password, "csrf_test_name": csrf_token}
            async with session.post(LOGIN_URL, data=payload, allow_redirects=True) as login_resp:
                if "mahasiswa" not in str(login_resp.url) and "Log Out" not in await login_resp.text():
                    raise PermissionError("Autentikasi gagal. Kredensial DERMAGA mungkin tidak valid.")

            # 2. Ambil halaman monitoring
            async with session.get(MONITORING_URL) as mon_resp:
                mon_soup = BeautifulSoup(await mon_resp.text(), "html.parser")

            # 3. Cari entri untuk tanggal target_date
            # A: Cek class btn-edit
            edit_buttons = mon_soup.find_all(class_="btn-edit")
            for btn in edit_buttons:
                btn_date = btn.get("data-tanggal")
                if btn_date == target_date:
                    return {
                        "exists": True,
                        "entry": {
                            "web_id": btn.get("data-id") or "-",
                            "tanggal": btn_date,
                            "masuk": btn.get("data-masuk") or "07:10",
                            "pulang": btn.get("data-pulang") or "16:25",
                            "deskripsi": btn.get("data-deskripsi") or "",
                        },
                        "error": None,
                    }

            # B: Cek baris tabel jika tombol edit tidak langsung cocok
            table = mon_soup.find("table")
            if table:
                for tr in table.find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) >= 4:
                        tgl_cell = tds[1].text.strip() if len(tds) >= 6 else tds[0].text.strip()
                        if target_date in tgl_cell:
                            return {
                                "exists": True,
                                "entry": {
                                    "web_id": tds[0].text.strip(),
                                    "tanggal": target_date,
                                    "masuk": "07:10",
                                    "pulang": "16:25",
                                    "deskripsi": tds[3].text.strip() if len(tds) >= 4 else "",
                                },
                                "error": None,
                            }

            return {"exists": False, "entry": None, "error": None}

    except Exception as e:
        logger.warning(f"[LOGBOOK-CHECK] Gagal cek live DERMAGA untuk chat_id={chat_id}: {e}. Memeriksa database lokal...")
        from app.database.logbook_repo import get_recent_drafts
        drafts = await get_recent_drafts(chat_id, limit=5)
        for d in drafts:
            if d.get("date") == target_date and d.get("status") == "submitted":
                return {
                    "exists": True,
                    "entry": {
                        "web_id": "Lokal",
                        "tanggal": target_date,
                        "masuk": d.get("jam_masuk", "07:10"),
                        "pulang": d.get("jam_pulang", "16:25"),
                        "deskripsi": d.get("summary", ""),
                    },
                    "error": None,
                    "is_fallback": True,
                }
        return {"exists": False, "entry": None, "error": str(e), "is_fallback": True}


async def submit_dermaga_entry(
    chat_id: int,
    date: str,
    summary: str,
    jam_masuk: str = "07:10",
    jam_pulang: str = "16:25",
    lat: str = "-7.5815",
    lng: str = "112.6247",
    accuracy: str = "15",
    override_id: Optional[str] = None,
) -> tuple[bool, str]:
    """Mengirim entri logbook dan absensi ke sistem DERMAGA Polinema secara asinkron."""
    cred = await get_user_credential(chat_id)
    if not cred:
        return False, "Kredensial akun DERMAGA tidak ditemukan."

    username, password = cred
    timeout = aiohttp.ClientTimeout(total=40)

    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
            # 1. Login
            async with session.get(LOGIN_URL) as resp:
                soup = BeautifulSoup(await resp.text(), "html.parser")
                csrf_token = soup.find("input", {"name": "csrf_test_name"})["value"]

            payload = {"username": username, "password": password, "csrf_test_name": csrf_token}
            async with session.post(LOGIN_URL, data=payload, allow_redirects=True) as login_resp:
                if "mahasiswa" not in str(login_resp.url) and "Log Out" not in await login_resp.text():
                    return False, "Autentikasi gagal. Periksa username dan password DERMAGA."

            # 2. Ambil CSRF baru dari form monitoring
            async with session.get(MONITORING_URL) as mon_resp:
                mon_soup = BeautifulSoup(await mon_resp.text(), "html.parser")
                csrf_submit_input = mon_soup.find("input", {"name": "csrf_test_name"})
                csrf_submit = csrf_submit_input["value"] if csrf_submit_input else csrf_token

            # 3. Micro-jitter GPS natural
            sub_lat, sub_lng, sub_acc, _ = apply_gps_jitter(lat, lng)

            # 4. Payload pengiriman absensi/logbook
            data_submit = {
                "csrf_test_name": csrf_submit,
                "id": override_id or "",
                "tanggal": date,
                "jam_masuk": jam_masuk,
                "jam_pulang": jam_pulang,
                "pekerjaan": summary,
                "deskripsi": summary,
                "latitude": sub_lat,
                "longitude": sub_lng,
                "accuracy": sub_acc,
                "akurasi": sub_acc,
                "keterangan": "hadir",
            }

            session.headers.update({"Referer": MONITORING_URL})
            async with session.post(SUBMIT_URL, data=data_submit, allow_redirects=True) as sub_resp:
                sub_text = await sub_resp.text()

                if sub_resp.status != 200:
                    return False, f"Server DERMAGA merespons dengan HTTP {sub_resp.status}."

                is_success, feedback_msg = extract_feedback_message(sub_text)
                if is_success is False:
                    return False, f"DERMAGA menolak penyimpanan: {feedback_msg}"

                if is_success is True:
                    return True, feedback_msg or "Logbook berhasil disimpan di DERMAGA!"

                if "berhasil" in sub_text.lower() or "sukses" in sub_text.lower():
                    return True, "Logbook berhasil dikirim ke DERMAGA!"

                return True, "Entri berhasil tersimpan di portal DERMAGA."

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

    # Cek override_id di metadata jika ada
    override_id = None
    if draft.get("raw_metadata"):
        try:
            raw = draft["raw_metadata"]
            meta = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(meta, dict):
                override_id = meta.get("override_id")
            elif isinstance(meta, list) and meta and isinstance(meta[0], dict):
                override_id = meta[0].get("override_id")
        except Exception:
            pass

    header = "📝 <b>DRAF LOGBOOK DERMAGA</b>"
    if override_id:
        header += f" <i>(Update/Timpa ID #{override_id})</i>"

    return (
        f"{header}\n\n"
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

