import socket
import urllib3.util.connection as urllib3_cn
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from .database import get_active_credential

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

def get_authenticated_session(username: str = None, password: str = None):
    """
    Melakukan login ke DERMAGA JTI dan mengembalikan requests.Session yang terautentikasi.
    """
    if not username or not password:
        username, password = get_active_credential()
    
    if not username or not password:
        raise ValueError("Kredensial DERMAGA tidak ditemukan di database.")

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

def submit_logbook_to_dermaga(draft_dict: dict, override_id: str = None, force: bool = False):
    """
    Mengeksekusi pengisian logbook ke portal DERMAGA.
    - Jika entri hari ini sudah ada dan override_id is None serta not force:
      mengembalikan status 'EXISTS' dan informasi entri lama agar pengguna dapat memilih di Telegram.
    - Jika submit berhasil: mengembalikan status 'SUCCESS'.
    """
    target_date = draft_dict.get('date', datetime.now().strftime('%Y-%m-%d'))
    summary = draft_dict.get('commits_summary', '')
    jam_masuk = draft_dict.get('jam_masuk') or '07:10'
    jam_pulang = draft_dict.get('jam_pulang') or '16:25'

    try:
        session = get_authenticated_session()
        mon_info = check_monitoring_page(session, target_date)

        # Jika logbook hari ini sudah ada dan belum ada konfirmasi timpa/override
        if mon_info['exists'] and not override_id and not force:
            return {
                'status': 'EXISTS',
                'web_id': mon_info['existing_entry']['web_id'],
                'existing_deskripsi': mon_info['existing_entry']['deskripsi'],
                'message': f"Logbook untuk tanggal {target_date} sudah ada di DERMAGA (ID: {mon_info['existing_entry']['web_id']})."
            }

        csrf_token = mon_info['csrf_token']
        if not csrf_token:
            # Fallback ambil csrf dari halaman monitoring
            soup = BeautifulSoup(session.get(MONITORING_URL).text, 'html.parser')
            csrf_token = soup.find('input', {'name': 'csrf_test_name'})['value']

        payload = {
            'csrf_test_name': csrf_token,
            'id': override_id if override_id else (mon_info['existing_entry']['web_id'] if force and mon_info['exists'] else ''),
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

        print(f"[LOGBOOK-WEB] Sukses submit logbook tanggal {target_date} ke DERMAGA.")
        return {
            'status': 'SUCCESS',
            'message': f"Logbook berhasil disimpan ke DERMAGA (ID: {payload['id'] or 'Baru'})."
        }

    except Exception as e:
        print(f"[LOGBOOK-WEB - ERROR] Gagal submit ke DERMAGA: {e}")
        return {
            'status': 'ERROR',
            'message': str(e)
        }
