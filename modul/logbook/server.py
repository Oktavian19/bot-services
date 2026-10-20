import http.server
import json
import os
import sys
from .database import create_or_get_draft

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
                'service': 'bot-services-logbook'
            })
        else:
            self.send_json_response(404, {'error': 'Not Found'})

    def do_POST(self):
        if self.path != '/api/logbook':
            self.send_json_response(404, {'error': 'Not Found'})
            return

        # 1. Validasi Autentikasi Bearer Token
        expected_token = os.environ.get('LOGBOOK_API_TOKEN')
        auth_header = self.headers.get('Authorization', '')
        
        if not expected_token:
            print("[LOGBOOK-API - WARNING] LOGBOOK_API_TOKEN belum dikonfigurasi di environment VPS!")
            self.send_json_response(500, {'error': 'Server API token not configured'})
            return

        if not auth_header.startswith('Bearer ') or auth_header[7:].strip() != expected_token:
            print("[LOGBOOK-API - WARN] Unauthorized request to /api/logbook")
            self.send_json_response(401, {'error': 'Unauthorized: Invalid or missing Bearer token'})
            return

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

        # 4. Simpan ke database
        try:
            draft, is_new = create_or_get_draft(
                idempotency_key=idempotency_key,
                date=date_str,
                projects=projects,
                commits_summary=summary,
                raw_metadata=commits,
                jam_masuk=jam_masuk,
                jam_pulang=jam_pulang
            )

            print(f"[LOGBOOK-API] Draf #{draft['id']} (is_new={is_new}) diterima dari remote client.")

            # Jika draf baru dan callback notifikasi terdaftar, kirim pesan Telegram
            if is_new and _on_draft_callback:
                try:
                    _on_draft_callback(draft)
                except Exception as cb_err:
                    print(f"[LOGBOOK-API - ERROR] Callback Telegram error: {cb_err}")

            status_code = 201 if is_new else 200
            self.send_json_response(status_code, {
                'status': 'ok',
                'draft_id': draft['id'],
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
    print(f"[LOGBOOK-API] HTTP Receiver aktif di http://{bind_host}:{bind_port}/api/logbook")
    httpd.serve_forever()
