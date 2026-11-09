import http.server
import json
import os
import sys
from .database import create_or_get_draft, get_user_by_token

_on_draft_callback = None

class LogbookRequestHandler(http.server.BaseHTTPRequestHandler):
    def send_json_response(self, status_code: int, data: dict):
        response_bytes = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        if self.path == '/api/health':
            self.send_json_response(200, {
                'status': 'healthy',
                'service': 'bot-services-logbook',
                'multi_user': True
            })
        else:
            self.send_json_response(404, {'error': 'Not Found'})

    def do_POST(self):
        if self.path != '/api/logbook':
            self.send_json_response(404, {'error': 'Not Found'})
            return

        # 1. Validasi Autentikasi Bearer Token Per-User
        auth_header = self.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            self.send_json_response(401, {'error': 'Unauthorized: Missing or invalid Bearer token header'})
            return

        token = auth_header[7:].strip()
        user = get_user_by_token(token)

        # Fallback ke admin jika menggunakan token master server
        if not user:
            admin_token = os.environ.get('LOGBOOK_API_TOKEN')
            admin_chat = os.environ.get('ADMIN_CHAT_ID')
            if admin_token and token == admin_token and admin_chat:
                user = {'chat_id': int(admin_chat.strip("'\" "))}

        if not user:
            print(f"[LOGBOOK-API - WARN] Unauthorized request with unregistered token: {token[:8]}...")
            self.send_json_response(401, {
                'error': 'Unauthorized: Token API tidak terdaftar di sistem bot. Gunakan /daftar_logbook di Telegram untuk registrasi akun dan mendapatkan token.'
            })
            return

        chat_id = user['chat_id']

        # 2. Baca dan validasi ukuran payload
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            self.send_json_response(400, {'error': 'Invalid Content-Length'})
            return

        if content_length > 1024 * 1024:  # Maksimum 1MB
            self.send_json_response(413, {'error': 'Payload Too Large'})
            return

        try:
            body = self.rfile.read(content_length).decode('utf-8')
            payload = json.loads(body)
        except Exception as e:
            self.send_json_response(400, {'error': f'Malformed JSON: {str(e)}'})
            return

        # 3. Validasi field payload
        required_fields = ['date', 'projects', 'summary', 'idempotency_key']
        missing = [f for f in required_fields if f not in payload]
        if missing:
            self.send_json_response(400, {'error': f'Missing required fields: {", ".join(missing)}'})
            return

        date_str = str(payload['date'])
        projects = payload['projects']
        summary = str(payload['summary'])
        idempotency_key = str(payload['idempotency_key'])
        commits = payload.get('commits', [])
        jam_masuk = str(payload.get('jam_masuk') or '07:10')
        jam_pulang = str(payload.get('jam_pulang') or '16:25')

        # 3.5 Ekstrak parameter lokasi / profile jika dikirimkan oleh CLI
        location_raw = payload.get('location') or payload.get('profile') or payload.get('location_profile')
        target_profile = None
        custom_lat = None
        custom_lng = None
        custom_akurasi = None

        if isinstance(location_raw, str):
            clean_loc = location_raw.strip().lower()
            if clean_loc in ('office', 'kantor', 'wfo'):
                target_profile = 'office'
            elif clean_loc in ('home', 'rumah', 'kos', 'wfh'):
                target_profile = 'home'
            elif clean_loc in ('other', 'lain', 'klien'):
                target_profile = 'other'
            elif ',' in clean_loc or ' ' in clean_loc:
                try:
                    from .main import parse_coordinates_input
                    parsed = parse_coordinates_input(clean_loc)
                    if parsed:
                        custom_lat = f"{parsed[0]:.6f}"
                        custom_lng = f"{parsed[1]:.6f}"
                        custom_akurasi = str(int(round(parsed[2])))
                except Exception:
                    pass

        elif isinstance(location_raw, dict):
            if 'profile' in location_raw and isinstance(location_raw['profile'], str):
                p = location_raw['profile'].strip().lower()
                if p in ('office', 'wfo', 'kantor'): target_profile = 'office'
                elif p in ('home', 'wfh', 'rumah', 'kos'): target_profile = 'home'
                elif p in ('other', 'lain', 'klien'): target_profile = 'other'

            c_lat = location_raw.get('lat') or location_raw.get('latitude')
            c_lng = location_raw.get('lng') or location_raw.get('longitude')
            c_acc = location_raw.get('akurasi') or location_raw.get('accuracy')
            if c_lat is not None and c_lng is not None:
                try:
                    f_lat = float(c_lat)
                    f_lng = float(c_lng)
                    if -90.0 <= f_lat <= 90.0 and -180.0 <= f_lng <= 180.0:
                        custom_lat = f"{f_lat:.6f}"
                        custom_lng = f"{f_lng:.6f}"
                        custom_akurasi = str(int(round(float(c_acc)))) if c_acc else "15"
                except (ValueError, TypeError):
                    pass

        # Cek jika ada field latitude/longitude langsung di root payload
        if not custom_lat and ('latitude' in payload or 'lat' in payload) and ('longitude' in payload or 'lng' in payload):
            try:
                f_lat = float(payload.get('latitude') or payload.get('lat'))
                f_lng = float(payload.get('longitude') or payload.get('lng'))
                f_acc = payload.get('akurasi') or payload.get('accuracy')
                if -90.0 <= f_lat <= 90.0 and -180.0 <= f_lng <= 180.0:
                    custom_lat = f"{f_lat:.6f}"
                    custom_lng = f"{f_lng:.6f}"
                    custom_akurasi = str(int(round(float(f_acc)))) if f_acc else "15"
            except (ValueError, TypeError):
                pass

        # 4. Simpan ke database dengan asosiasi chat_id user
        try:
            draft, is_new = create_or_get_draft(
                chat_id=chat_id,
                idempotency_key=idempotency_key,
                date=date_str,
                projects=projects,
                commits_summary=summary,
                raw_metadata=commits,
                jam_masuk=jam_masuk,
                jam_pulang=jam_pulang,
                location_profile=target_profile,
                custom_lat=custom_lat,
                custom_lng=custom_lng,
                custom_akurasi=custom_akurasi
            )

            print(f"[LOGBOOK-API] Draf #{draft['id']} (is_new={is_new}) diterima dari remote client untuk User {chat_id}.")

            # Jika draf baru dan callback notifikasi terdaftar, kirim pesan Telegram ke chat_id user
            if is_new and _on_draft_callback:
                try:
                    _on_draft_callback(draft)
                except Exception as cb_err:
                    print(f"[LOGBOOK-API - ERROR] Callback Telegram error untuk User {chat_id}: {cb_err}")

            status_code = 201 if is_new else 200
            self.send_json_response(status_code, {
                'status': 'ok',
                'draft_id': draft['id'],
                'chat_id': chat_id,
                'is_duplicate': not is_new,
                'message': 'Draft processed successfully'
            })

        except Exception as db_err:
            print(f"[LOGBOOK-API - ERROR] Database error: {db_err}")
            self.send_json_response(500, {'error': f'Internal server error: {str(db_err)}'})

    def log_message(self, format, *args):
        # Mute default stderr logging standard library agar log tetap bersih
        pass

def run_http_server(on_draft_cb=None, host: str = None, port: int = None):
    global _on_draft_callback
    _on_draft_callback = on_draft_cb

    bind_host = host or os.environ.get('LOGBOOK_API_HOST', '127.0.0.1')
    bind_port = port or int(os.environ.get('LOGBOOK_API_PORT', 8088))

    server_address = (bind_host, bind_port)
    httpd = http.server.ThreadingHTTPServer(server_address, LogbookRequestHandler)
    print(f"[LOGBOOK-API] HTTP Receiver aktif di http://{bind_host}:{bind_port}/api/logbook (Multi-User Mode)")
    httpd.serve_forever()
