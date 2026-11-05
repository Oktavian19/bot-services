import threading

_user_locks = {}
_registry_lock = threading.Lock()

def get_user_lock(chat_id: int) -> threading.Lock:
    """
    Mengembalikan threading.Lock spesifik untuk chat_id pengguna.
    Menghindari tabrakan (race condition) antara scheduler pengecekan DERMAGA
    dengan submission interaktif Telegram atau draf remote logbook_cli.
    """
    with _registry_lock:
        if chat_id not in _user_locks:
            _user_locks[chat_id] = threading.Lock()
        return _user_locks[chat_id]

