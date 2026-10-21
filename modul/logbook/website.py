import os
import re
import socket
import urllib3.util.connection as urllib3_cn
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from .database import get_user_credential, get_user_by_chat_id

# --- PATCH FORCE IPV4 ---
def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

LOGIN_URL = 'https://jti.polinema.ac.id/dermaga/login'
MONITORING_URL = 'https://jti.polinema.ac.id/dermaga/mahasiswa/monitoring'
SUBMIT_URL = 'https://jti.polinema.ac.id/dermaga/mahasiswa/monitoring/simpan'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Origin': 'https://jti.polinema.ac.id',
    'Referer': LOGIN_URL
}

def get_authenticated_session(username: str = None, password: str = None, chat_id: int = None):
    """
    Melakukan login ke DERMAGA JTI dan mengembalikan requests.Session yang terautentikasi.
    Mendukung pengambilan kredensial dinamis berdasarkan chat_id.
    """
    if chat_id and (not username or not password):
        user_cred = get_user_credential(chat_id)
        if user_cred:
            username, password = user_cred

    if not username or not password:
        raise ValueError(f"Kredensial DERMAGA tidak ditemukan untuk User {chat_id or 'aktif'}. Silakan registrasi via /daftar_logbook.")

    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. Ambil halaman login untuk mengekstrak CSRF token
    resp_login_page = session.get(LOGIN_URL, timeout=15)
    if resp_login_page.status_code != 200:
        raise ConnectionError(f"Gagal memuat halaman login DERMAGA (HTTP {resp_login_page.status_code})")

    soup = BeautifulSoup(resp_login_page.text, 'html.parser')
    csrf_input = soup.find('input', {'name': 'csrf_test_name'})
    if not csrf_input or not csrf_input.get('value'):
        raise ValueError("Gagal menemukan CSRF token pada halaman login DERMAGA.")
    
    csrf_token = csrf_input['value']

    # 2. Kirim kredensial login
    login_data = {
        'csrf_test_name': csrf_token,
        'username': username,
        'password': password,
        'remember': '1'
    }
    resp_login = session.post(LOGIN_URL, data=login_data, timeout=15, allow_redirects=True)
    if resp_login.status_code != 200:
        raise ConnectionError(f"Gagal mengirim request login DERMAGA (HTTP {resp_login.status_code})")

    login_soup = BeautifulSoup(resp_login.text, 'html.parser')
    page_title = login_soup.title.string if login_soup.title else ""
    if "Login" in page_title and "DERMAGA" in page_title:
        # Cek apakah ada alert error
        alert = login_soup.find(class_=lambda c: c and ('alert-danger' in c or 'error' in c))
        msg = alert.get_text(strip=True) if alert else "Username atau password salah."
        raise PermissionError(f"Login DERMAGA gagal: {msg}")

    return session

def test_dermaga_login(username: str, password: str) -> tuple:
    """
    Menguji kredensial login DERMAGA secara live.
    Mengembalikan (success: bool, message: str).
    """
    try:
        get_authenticated_session(username=username, password=password)
        return True, "Autentikasi DERMAGA berhasil."
    except PermissionError as pe:
        return False, str(pe)
    except ConnectionError as ce:
        return False, f"Koneksi gagal: {ce}"
    except Exception as e:
        return False, f"Terjadi kesalahan saat verifikasi: {e}"

def check_monitoring_page(session, target_date: str):
    """
    Memeriksa halaman monitoring untuk mengecek apakah entri logbook target_date sudah ada.
    Mengembalikan dict informasi keberadaan dan token CSRF terbaru.
    """
    resp = session.get(MONITORING_URL, timeout=15)
    if resp.status_code != 200:
        raise ConnectionError(f"Gagal memuat halaman monitoring DERMAGA (HTTP {resp.status_code})")

    soup = BeautifulSoup(resp.text, 'html.parser')

    # Cari CSRF token di halaman monitoring (misal di formLogbook)
    csrf_input = soup.find('input', {'name': 'csrf_test_name'})
    csrf_token = csrf_input['value'] if csrf_input else None

    # Cek tombol edit di tabel logbook
    existing_entry = None
    edit_buttons = soup.find_all(class_='btn-edit')
    for btn in edit_buttons:
        if btn.get('data-tanggal') == target_date:
            existing_entry = {
                'web_id': btn.get('data-id'),
                'tanggal': btn.get('data-tanggal'),
                'masuk': btn.get('data-masuk'),
                'pulang': btn.get('data-pulang'),
                'deskripsi': btn.get('data-deskripsi')
            }
            break

    return {
        'exists': existing_entry is not None,
        'existing_entry': existing_entry,
        'csrf_token': csrf_token
    }

def fetch_dermaga_table(chat_id: int = None, username: str = None, password: str = None):
    """
    Mengambil seluruh daftar logbook yang saat ini tercatat di tabel DERMAGA milik akun pengguna.
    Mengembalikan list of dict entri logbook.
    """
    session = get_authenticated_session(username=username, password=password, chat_id=chat_id)
    resp = session.get(MONITORING_URL, timeout=15)
    if resp.status_code != 200:
        raise ConnectionError(f"Gagal memuat monitoring (HTTP {resp.status_code})")

    soup = BeautifulSoup(resp.text, 'html.parser')
    tbl = soup.find(id='tblLogbook')
    if not tbl:
        return []

    entries = []
    tbody = tbl.find('tbody')
    if not tbody:
        return []

    for tr in tbody.find_all('tr'):
        tds = tr.find_all('td')
        if len(tds) < 8:
            continue
        
        tgl_cell = tds[0]
        tgl_order = tgl_cell.get('data-order') or ''
        tgl_text = " ".join(tgl_cell.stripped_strings)

        keterangan = tds[2].get_text(strip=True)
        jam_masuk = tds[3].get_text(strip=True)
        jam_pulang = tds[4].get_text(strip=True)
        pekerjaan = tds[5].get_text(strip=True)
        status_verif = tds[7].get_text(strip=True)

        btn_edit = tr.find(class_='btn-edit')
        web_id = btn_edit.get('data-id') if btn_edit else None

        entries.append({
            'web_id': web_id,
            'tanggal_iso': tgl_order,
            'tanggal_text': tgl_text,
            'keterangan': keterangan,
            'jam': f"{jam_masuk} - {jam_pulang}",
            'pekerjaan': pekerjaan,
            'status_verif': status_verif
        })

    return entries

def extract_feedback_message(html_text: str) -> tuple:
    """
    Mengekstrak pesan feedback/notifikasi dari respons HTML DERMAGA:
    Mengembalikan (is_success: bool|None, message: str).
    """
    if not html_text:
        return None, ""

    if not isinstance(html_text, (str, bytes)):
        html_text = str(html_text)

    soup = BeautifulSoup(html_text, 'html.parser')

    # 1. Cek notifikasi script SweetAlert atau notify()
    for s in soup.find_all('script'):
        txt = s.string or s.text or ''
        if 'notify(' in txt:
            if "notify('success'" in txt or 'notify("success"' in txt:
                m = re.search(r'notify\(\s*[\'"]success[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]', txt)
                return True, m.group(1) if m else "Logbook berhasil disimpan."
            elif "notify('error'" in txt or 'notify("error"' in txt or "notify('warning'" in txt:
                m = re.search(r'notify\(\s*[\'"][^\'"]+[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]', txt)
                return False, m.group(1) if m else "Gagal menyimpan logbook."

        if 'Swal.fire' in txt:
            m_icon = re.search(r'icon:\s*[\'"]([^\'"]+)[\'"]', txt)
            m_title = re.search(r'title:\s*[\'"]([^\'"]+)[\'"]', txt)
            m_html = re.search(r'html:\s*[\'"]([^\'"]+)[\'"]', txt)
            icon = m_icon.group(1) if m_icon else "warning"
            title = m_title.group(1) if m_title else "Peringatan"
            detail = m_html.group(1) if m_html else ""
            clean_detail = re.sub(r'<[^>]+>', ' ', detail).strip()
            msg = f"{title}: {clean_detail}" if clean_detail else title
            return (False if icon in ['warning', 'error'] else True), msg

    # 2. Cek elemen alert HTML biasa
    for alert in soup.find_all(class_=lambda c: c and ('alert-danger' in c or 'alert-warning' in c)):
        classes = alert.get('class', [])
        if 'd-none' not in classes:
            txt = alert.get_text(strip=True)
            if txt:
                return False, txt

    return None, ""

def submit_logbook_to_dermaga(draft_dict: dict, override_id: str = None, force: bool = False):
    """
    Mengeksekusi pengisian logbook ke portal DERMAGA dengan akun spesifik user dan verifikasi nyata.
    - Mengirim payload lengkap (keterangan, koordinat lokasi, jam kerja, deskripsi).
    - Memverifikasi secara langsung keberadaan baris pada tabel tblLogbook pasca submit.
    """
    chat_id = draft_dict.get('chat_id')
    target_date = draft_dict.get('date', datetime.now().strftime('%Y-%m-%d'))
    summary = draft_dict.get('commits_summary', '')
    jam_masuk = draft_dict.get('jam_masuk') or '07:10'
    jam_pulang = draft_dict.get('jam_pulang') or '16:25'

    # Ambil metadata lokasi user jika ada, fallback ke default
    user_meta = get_user_by_chat_id(chat_id) if chat_id else None
    default_lat = (user_meta.get('default_lat') if user_meta else None) or os.environ.get('DERMAGA_DEFAULT_LAT', '-7.5815')
    default_lng = (user_meta.get('default_lng') if user_meta else None) or os.environ.get('DERMAGA_DEFAULT_LNG', '112.6247')
    default_akurasi = (user_meta.get('default_akurasi') if user_meta else None) or os.environ.get('DERMAGA_DEFAULT_AKURASI', '15')

    try:
        session = get_authenticated_session(chat_id=chat_id)
        mon_info = check_monitoring_page(session, target_date)

        # Jika logbook hari ini sudah ada dan belum ada konfirmasi timpa/override
        if mon_info['exists'] and not override_id and not force:
            return {
                'status': 'EXISTS',
                'web_id': mon_info['existing_entry']['web_id'],
                'existing_deskripsi': mon_info['existing_entry']['deskripsi'],
                'message': f"Logbook untuk tanggal {target_date} sudah ada di DERMAGA (ID: {mon_info['existing_entry']['web_id']})."
            }

        csrf_token = mon_info.get('csrf_token')
        if not csrf_token:
            soup = BeautifulSoup(session.get(MONITORING_URL, timeout=15).text, 'html.parser')
            csrf_input = soup.find('input', {'name': 'csrf_test_name'})
            csrf_token = csrf_input['value'] if csrf_input else ''

        payload = {
            'csrf_test_name': csrf_token,
            'id': override_id if override_id else (mon_info['existing_entry']['web_id'] if (force and mon_info['exists']) else ''),
            'keterangan': 'hadir',
            'latitude': default_lat,
            'longitude': default_lng,
            'akurasi': default_akurasi,
            'jam_masuk': jam_masuk,
            'jam_pulang': jam_pulang,
            'deskripsi': summary
        }

        session.headers.update({'Referer': MONITORING_URL})
        resp_submit = session.post(SUBMIT_URL, data=payload, timeout=15, allow_redirects=True)

        if resp_submit.status_code != 200:
            return {
                'status': 'FAILED',
                'message': f"Server DERMAGA merespons dengan HTTP {resp_submit.status_code}"
            }

        # Periksa respon feedback (misal alert / Swal warning dari backend)
        is_success, feedback_msg = extract_feedback_message(resp_submit.text)
        if is_success is False:
            return {
                'status': 'FAILED',
                'message': f"DERMAGA menolak penyimpanan: {feedback_msg}"
            }

        # Verifikasi nyata: periksa ulang keberadaan baris pada tabel tblLogbook
        verify_check = check_monitoring_page(session, target_date)
        if not verify_check['exists']:
            msg = feedback_msg or "Entri logbook tidak ditemukan di tabel setelah proses simpan."
            return {
                'status': 'FAILED',
                'message': f"Verifikasi gagal: {msg}"
            }

        entry = verify_check['existing_entry']
        web_id = entry.get('web_id') or payload['id'] or 'Tercatat'
        print(f"[LOGBOOK-WEB] Sukses & Terverifikasi submit logbook tanggal {target_date} ke DERMAGA untuk User {chat_id} (ID: #{web_id}).")
        return {
            'status': 'SUCCESS',
            'web_id': web_id,
            'message': f"Logbook tanggal {target_date} terverifikasi berhasil tersimpan di tabel DERMAGA (ID: #{web_id})."
        }

    except Exception as e:
        print(f"[LOGBOOK-WEB - ERROR] Gagal submit ke DERMAGA untuk User {chat_id}: {e}")
        return {
            'status': 'ERROR',
            'message': str(e)
        }
