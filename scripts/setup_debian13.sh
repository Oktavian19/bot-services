#!/usr/bin/env bash
# ==============================================================================
# scripts/setup_debian13.sh
# Installer & Migrator Interaktif bot-services untuk VPS Debian 13 (Trixie) + systemd
#
# Fitur:
#   - Dapat dijalankan standalone (bootstrap sebelum git clone) maupun dari dalam repo
#   - Setup SSH Ed25519 & clone repositori via SSH: git@github.com:Oktavian19/bot-services.git
#   - Pilihan [1] Install Fresh atau [2] Migrasi dari VPS / arsip /backup Telegram (.zip/.db)
#   - Verifikasi PRAGMA integrity_check, row count, & kecocokan LOGBOOK_SECRET_KEY (Fernet)
#   - Setup Python .venv, dependencies, unit test, Ookla Speedtest CLI (opsional), UFW, & systemd
# ==============================================================================

set -euo pipefail

REPO_SSH_URL="git@github.com:Oktavian19/bot-services.git"
REPO_HTTPS_URL="https://github.com/Oktavian19/bot-services.git"
DEFAULT_SERVICE_NAME="bot-services"

TARGET_USER=""
TARGET_GROUP=""
TARGET_HOME=""
APP_DIR=""
MIGRATION_DIR=""
INSTALL_MODE=""
API_PORT="8088"
SSH_NEEDS_GITHUB=0
PUBKEY_PATH=""

# --- WARNA & LOGGING ---
if [[ -t 1 ]]; then
    C_RESET="\033[0m"
    C_BOLD="\033[1m"
    C_CYAN="\033[1;36m"
    C_GREEN="\033[1;32m"
    C_YELLOW="\033[1;33m"
    C_RED="\033[1;31m"
else
    C_RESET="" C_BOLD="" C_CYAN="" C_GREEN="" C_YELLOW="" C_RED=""
fi

info()    { echo -e "${C_CYAN}[INFO]${C_RESET} $*"; }
success() { echo -e "${C_GREEN}[OK]${C_RESET} $*"; }
warn()    { echo -e "${C_YELLOW}[WARN]${C_RESET} $*"; }
err()     { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }
section() { echo -e "\n${C_BOLD}========================================================================${C_RESET}\n${C_CYAN}  $*${C_RESET}\n${C_BOLD}========================================================================${C_RESET}"; }

# --- HELPER EKSEKUSI & PROMPT ---
run_root() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

run_as_user() {
    if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
        sudo -u "$TARGET_USER" -H "$@"
    else
        "$@"
    fi
}

run_in_app_dir() {
    if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
        sudo -u "$TARGET_USER" -H bash -c 'cd "$1" && shift && exec "$@"' _ "$APP_DIR" "$@"
    else
        (cd "$APP_DIR" && exec "$@")
    fi
}

prompt_default() {
    local prompt_msg="$1"
    local default_val="$2"
    local reply=""
    read -r -p "$prompt_msg [$default_val]: " reply
    echo "${reply:-$default_val}"
}

prompt_yes_no() {
    local prompt_msg="$1"
    local default_ans="${2:-y}"
    local hint="[Y/n]"
    [[ "$default_ans" =~ ^[Nn]$ ]] && hint="[y/N]"
    local reply=""
    read -r -p "$prompt_msg $hint: " reply
    reply="${reply:-$default_ans}"
    [[ "$reply" =~ ^[Yy]$ ]]
}

pause_enter() {
    local msg="${1:-Tekan ENTER untuk melanjutkan...}"
    read -r -p "$msg" _
}

# --- KONTEKS USER & DIREKTORI ---
resolve_runtime_context() {
    section "1. DETEKSI LINGKUNGAN VPS DEBIAN 13 & KONTEKS USER"

    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        info "OS Terdeteksi: ${PRETTY_NAME:-Linux} (codename: ${VERSION_CODENAME:-unknown})"
        if [[ "${ID:-}" != "debian" ]]; then
            warn "Script ini dioptimalkan untuk Debian 13 (terdeteksi: ${ID:-unknown}). Lanjut dengan penyesuaian Debian."
        fi
    fi

    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
            TARGET_USER="$SUDO_USER"
        else
            warn "Anda menjalankan script langsung sebagai root tanpa SUDO_USER."
            TARGET_USER=$(prompt_default "Masukkan username Linux non-root untuk menjalankan service bot" "oktavian")
            if ! id -u "$TARGET_USER" >/dev/null 2>&1; then
                if prompt_yes_no "User '$TARGET_USER' belum ada. Buat user '$TARGET_USER' dengan akses sudo?" "y"; then
                    adduser --gecos "" "$TARGET_USER"
                    usermod -aG sudo "$TARGET_USER"
                    success "User '$TARGET_USER' berhasil dibuat dan dimasukkan ke grup sudo."
                else
                    err "User target '$TARGET_USER' tidak ditemukan. Keluar."
                    exit 1
                fi
            fi
        fi
    else
        TARGET_USER="$(id -un)"
    fi

    TARGET_GROUP="$(id -gn "$TARGET_USER")"
    TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    if [[ -z "$TARGET_HOME" || ! -d "$TARGET_HOME" ]]; then
        err "Direktori home untuk user '$TARGET_USER' tidak valid."
        exit 1
    fi

    # Deteksi otomatis apakah script sedang berada di dalam repo bot-services
    local script_parent=""
    script_parent="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd || true)"
    local default_app_dir="$TARGET_HOME/bot-services"
    if [[ -f "$script_parent/main.py" && -f "$script_parent/requirements.txt" ]]; then
        default_app_dir="$script_parent"
    elif [[ -f "./main.py" && -f "./requirements.txt" ]]; then
        default_app_dir="$(pwd)"
    fi

    APP_DIR=$(prompt_default "Lokasi instalasi folder bot-services" "$default_app_dir")
    APP_DIR="${APP_DIR/#\~/$TARGET_HOME}"
    MIGRATION_DIR="$TARGET_HOME/bot-migration"

    info "User service   : $TARGET_USER:$TARGET_GROUP ($TARGET_HOME)"
    info "Direktori bot  : $APP_DIR"
}

choose_install_mode() {
    section "2. PILIH MODE PEMASANGAN"
    echo "Pilih jenis pemasangan pada VPS baru ini:"
    echo "  [1] Install Fresh — Mulai bersih (buat .env.bot baru, generate key Fernet, DB baru)"
    echo "  [2] Migrasi       — Pindahkan data & .env.bot dari VPS lama atau arsip .zip /backup Telegram"
    echo ""

    while true; do
        local choice=""
        read -r -p "Masukkan pilihan [1/2]: " choice
        case "$choice" in
            1)
                INSTALL_MODE="fresh"
                success "Mode dipilih: Install Fresh"
                break
                ;;
            2)
                INSTALL_MODE="migrate"
                success "Mode dipilih: Migrasi Data"
                break
                ;;
            *)
                warn "Pilihan tidak valid. Ketik 1 atau 2."
                ;;
        esac
    done
}

# --- PAKET SISTEM & SPEEDTEST CLI ---
install_system_packages() {
    section "3. INSTALASI PAKET SISTEM DEBIAN 13 & TIMEZONE"
    info "Memperbarui indeks apt dan memasang paket wajib (Python 3, venv, git, sqlite3, tzdata, dll.)..."
    run_root apt-get update -y
    run_root apt-get install -y --no-install-recommends \
        git python3 python3-venv python3-pip \
        curl ca-certificates tzdata unzip sqlite3 \
        openssh-client build-essential libffi-dev libssl-dev

    if command -v timedatectl >/dev/null 2>&1; then
        run_root timedatectl set-timezone Asia/Jakarta || warn "timedatectl gagal (abaikan jika di dalam container)."
    fi
    success "Paket sistem wajib terpasang."

    install_speedtest_optional
}

install_speedtest_optional() {
    echo ""
    if command -v speedtest >/dev/null 2>&1 && speedtest --version 2>/dev/null | grep -qi "Ookla"; then
        success "Ookla Speedtest CLI sudah terpasang."
        return
    fi

    if ! prompt_yes_no "Pasang Ookla Speedtest CLI (opsional, untuk perintah admin /speedtest)?" "y"; then
        info "Instalasi Ookla Speedtest CLI dilewati."
        return
    fi

    info "Menyiapkan repositori Ookla Speedtest CLI (non-fatal jika distro Trixie belum didukung)..."
    set +e
    local codename=""
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-bookworm}")"
    if [[ "$codename" == "trixie" ]]; then
        # Packagecloud Ookla sering kali belum menerbitkan indeks khusus 'trixie'; fallback ke 'bookworm'
        warn "Debian 13 (trixie) terdeteksi; menggunakan fallback suite 'bookworm' untuk repo Packagecloud Ookla."
        curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh \
            | run_root env os=debian dist=bookworm bash \
            && run_root apt-get install -y --no-install-recommends speedtest
    else
        curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh \
            | run_root bash \
            && run_root apt-get install -y --no-install-recommends speedtest
    fi
    local rc=$?
    set -e

    if [[ $rc -eq 0 ]] && command -v speedtest >/dev/null 2>&1; then
        success "Ookla Speedtest CLI berhasil dipasang."
    else
        warn "Pemasangan Ookla Speedtest CLI lewat apt gagal/belum tersedia. Fitur bot lain tetap berjalan normal; Anda dapat memasang binary speedtest manual ke /usr/local/bin/speedtest kapan saja."
    fi
}

# --- SSH KEY GITHUB & CLONE REPOSITORY ---
ensure_ssh_key() {
    local ssh_dir="$TARGET_HOME/.ssh"
    local key_path="$ssh_dir/id_ed25519"
    PUBKEY_PATH="${key_path}.pub"

    run_as_user mkdir -p "$ssh_dir"
    run_as_user chmod 700 "$ssh_dir"

    if [[ ! -f "$key_path" || ! -f "$PUBKEY_PATH" ]]; then
        info "Membuat SSH key baru (Ed25519) untuk user '$TARGET_USER'..."
        run_as_user ssh-keygen -t ed25519 -C "bot-services@${HOSTNAME:-vps}" -N "" -f "$key_path"
        run_as_user chmod 600 "$key_path"
        run_as_user chmod 644 "$PUBKEY_PATH"
        success "SSH key dibuat di: $key_path"
    else
        info "SSH key sudah ada: $key_path"
    fi

    local known_hosts="$ssh_dir/known_hosts"
    run_as_user touch "$known_hosts"
    run_as_user chmod 644 "$known_hosts"
    if ! run_as_user ssh-keygen -F github.com -f "$known_hosts" >/dev/null 2>&1; then
        info "Menambahkan fingerprint host github.com ke $known_hosts..."
        ssh-keyscan -T 10 -t ed25519,rsa github.com 2>/dev/null | run_as_user tee -a "$known_hosts" >/dev/null || true
    fi
}

test_github_ssh() {
    local out=""
    set +e
    out=$(run_as_user ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -T git@github.com 2>&1)
    set -e
    echo "$out" | grep -qi "successfully authenticated"
}

show_ssh_pubkey_instructions() {
    echo ""
    echo -e "${C_YELLOW}------------------ SSH PUBLIC KEY VPS INI ------------------${C_RESET}"
    cat "$PUBKEY_PATH"
    echo -e "${C_YELLOW}------------------------------------------------------------${C_RESET}"
    echo "Tambahkan key di atas ke GitHub agar VPS bisa mengakses repo lewat SSH:"
    echo "  • Akun GitHub    : https://github.com/settings/ssh/new"
    echo "  • Deploy Key repo: https://github.com/Oktavian19/bot-services/settings/keys/new"
    echo ""
}

setup_github_ssh_and_repo() {
    section "4. KONFIGURASI SSH GITHUB & CLONE REPOSITORY"
    ensure_ssh_key

    if [[ -f "$APP_DIR/main.py" && -f "$APP_DIR/requirements.txt" ]]; then
        success "Direktori kode sudah tersedia di: $APP_DIR"
        if [[ -d "$APP_DIR/.git" ]]; then
            local curr_remote=""
            curr_remote="$(run_as_user git -C "$APP_DIR" remote get-url origin 2>/dev/null || true)"
            if [[ "$curr_remote" != "$REPO_SSH_URL" ]]; then
                info "Mengubah remote 'origin' ke SSH ($REPO_SSH_URL)..."
                run_as_user git -C "$APP_DIR" remote set-url origin "$REPO_SSH_URL"
            fi
        fi

        if test_github_ssh; then
            success "Autentikasi SSH ke GitHub terverifikasi!"
            if [[ -d "$APP_DIR/.git" ]] && prompt_yes_no "Jalankan 'git pull --ff-only' untuk pembaruan terbaru?" "y"; then
                run_as_user git -C "$APP_DIR" pull --ff-only || warn "git pull gagal; pastikan working tree bersih."
            fi
        else
            warn "SSH key VPS belum terhubung ke GitHub. Script tetap lanjut dan akan mengingatkan di akhir."
            SSH_NEEDS_GITHUB=1
        fi
        return
    fi

    # Direktori bot belum ada -> lakukan clone via SSH
    while true; do
        if test_github_ssh; then
            success "Autentikasi SSH ke GitHub berhasil!"
            info "Melakukan clone $REPO_SSH_URL -> $APP_DIR..."
            run_as_user git clone "$REPO_SSH_URL" "$APP_DIR"
            success "Repository berhasil di-clone lewat SSH."
            return
        fi

        warn "Koneksi SSH ke git@github.com belum terautentikasi."
        show_ssh_pubkey_instructions
        echo "Pilihan langkah:"
        echo "  [1] Saya sudah menempelkan key di GitHub — cek ulang SSH & lanjut clone SSH"
        echo "  [2] Clone sementara via HTTPS (khusus repo public), lalu ubah remote ke SSH & ingatkan di akhir"
        local ssh_opt=""
        read -r -p "Pilih [1/2]: " ssh_opt
        if [[ "$ssh_opt" == "2" ]]; then
            info "Mencoba clone via HTTPS sementara..."
            if run_as_user git clone "$REPO_HTTPS_URL" "$APP_DIR"; then
                run_as_user git -C "$APP_DIR" remote set-url origin "$REPO_SSH_URL"
                SSH_NEEDS_GITHUB=1
                success "Clone berhasil dan remote origin telah disetel ke $REPO_SSH_URL."
                return
            else
                err "Clone HTTPS gagal (kemungkinan repo private). Silakan pasang SSH key di GitHub lalu pilih [1]."
            fi
        fi
    done
}

# --- VIRTUAL ENVIRONMENT & UNIT TEST ---
setup_python_venv() {
    section "5. SETUP PYTHON VIRTUAL ENVIRONMENT (.venv) & UNIT TEST"
    if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
        info "Membuat virtual environment di $APP_DIR/.venv..."
        run_as_user python3 -m venv "$APP_DIR/.venv"
    fi

    info "Memasang dependensi dari requirements.txt..."
    run_in_app_dir "$APP_DIR/.venv/bin/pip" install --upgrade pip
    run_in_app_dir "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
    success "Dependensi Python terpasang di $APP_DIR/.venv."

    if prompt_yes_no "Jalankan unit test proyek untuk memverifikasi environment?" "y"; then
        info "Menjalankan unittest..."
        run_in_app_dir "$APP_DIR/.venv/bin/python" -m unittest discover -s tests
        success "Seluruh unit test lulus."
    fi
}

# --- KONFIGURASI FRESH VS MIGRASI ---
read_api_port_from_settings() {
    API_PORT="$(run_in_app_dir "$APP_DIR/.venv/bin/python" -c 'from app.core.config import get_settings; print(get_settings().LOGBOOK_API_PORT)')"
}

run_fresh_setup() {
    section "6. KONFIGURASI INSTALL FRESH (.env.bot & INISIALISASI DB)"
    info "Lokasi file config target : $APP_DIR/.env.bot"
    info "Lokasi folder DB target   : $APP_DIR/data/"

    local env_target="$APP_DIR/.env.bot"
    if [[ -f "$env_target" ]]; then
        if ! prompt_yes_no "File $env_target sudah ada. Timpa dengan konfigurasi baru?" "n"; then
            info "Mempertahankan $env_target yang sudah ada."
            read_api_port_from_settings
            initialize_empty_dbs
            return
        fi
        run_as_user cp "$env_target" "${env_target}.bak_$(date +%Y%m%d_%H%M%S)"
    fi

    local tg_token=""
    while [[ -z "$tg_token" ]]; do
        read -r -p "Masukkan TELEGRAM_TOKEN (dari @BotFather): " tg_token
        tg_token="${tg_token// /}"
        [[ -z "$tg_token" ]] && warn "TELEGRAM_TOKEN wajib diisi."
    done

    local admin_id=""
    while true; do
        read -r -p "Masukkan ADMIN_CHAT_ID (angka ID Telegram admin, kosongkan jika belum ada): " admin_id
        admin_id="${admin_id// /}"
        if [[ -z "$admin_id" || "$admin_id" =~ ^-?[0-9]+$ ]]; then
            break
        fi
        warn "ADMIN_CHAT_ID harus berupa angka integer (contoh: 1186123456)."
    done

    API_PORT=$(prompt_default "Masukkan LOGBOOK_API_PORT" "8088")
    local detected_ip=""
    detected_ip="$(curl -fsS -4 --max-time 3 https://ifconfig.me 2>/dev/null || echo "127.0.0.1")"
    local default_pub_url="http://${detected_ip}:${API_PORT}/api/logbook"
    local pub_url=""
    pub_url=$(prompt_default "Masukkan LOGBOOK_PUBLIC_URL" "$default_pub_url")
    local log_level=""
    log_level=$(prompt_default "Masukkan LOG_LEVEL (INFO/DEBUG/WARNING)" "INFO")

    info "Membuat kunci enkripsi Fernet otomatis (LOGBOOK_SECRET_KEY & MAGANG_SECRET_KEY)..."
    local key_logbook="" key_magang="" api_master_token=""
    key_logbook="$("$APP_DIR/.venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    key_magang="$("$APP_DIR/.venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    api_master_token="$("$APP_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_hex(16))')"

    cat <<EOF | run_as_user tee "$env_target" >/dev/null
# Generated by scripts/setup_debian13.sh on $(date -Iseconds)
TELEGRAM_TOKEN=$tg_token
ADMIN_CHAT_ID=$admin_id

LOGBOOK_SECRET_KEY=$key_logbook
MAGANG_SECRET_KEY=$key_magang

LOGBOOK_API_PORT=$API_PORT
LOGBOOK_API_HOST=0.0.0.0
LOGBOOK_PUBLIC_URL=$pub_url
LOGBOOK_API_TOKEN=$api_master_token

LOG_LEVEL=$log_level
TIMEZONE=Asia/Jakarta
EOF
    run_as_user chmod 600 "$env_target"
    success "Konfigurasi tersimpan aman di $env_target (chmod 600)."

    initialize_empty_dbs
}

initialize_empty_dbs() {
    info "Menginisialisasi struktur tabel SQLite awal di $APP_DIR/data/..."
    run_as_user mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
    run_in_app_dir "$APP_DIR/.venv/bin/python" - <<'PYEOF'
import asyncio
from app.core.config import get_settings
from app.database.reminder_repo import init_reminder_db
from app.database.fuel_repo import init_fuel_db
from app.database.logbook_repo import init_logbook_db

async def init_all():
    s = get_settings()
    await init_reminder_db()
    await init_fuel_db()
    await init_logbook_db()
    print("Initialized DBs in:", s.LOGBOOK_DB_PATH.parent.resolve())

asyncio.run(init_all())
PYEOF
    success "Database SQLite awal siap."
}

print_migration_placement_guide() {
    local vps_ip=""
    vps_ip="$(curl -fsS -4 --max-time 3 https://ifconfig.me 2>/dev/null || echo "<IP_VPS_BARU>")"
    run_as_user mkdir -p "$MIGRATION_DIR"

    echo ""
    echo -e "${C_BOLD}--- LOKASI PELETAKAN FILE MIGRASI ---${C_RESET}"
    echo "Letakkan file backup dan konfigurasi lama ke folder staging berikut:"
    echo "  Folder staging : $MIGRATION_DIR/"
    echo "  File wajib     : .env.bot (atau .env) -> berisi TELEGRAM_TOKEN & LOGBOOK_SECRET_KEY lama"
    echo "  File database  : salah satu dari:"
    echo "    • Arsip ZIP hasil command /backup bot Telegram (bot-services_backup_*.zip)"
    echo "    • ATAU file SQLite mentah (*.db): reminders.db, bensin.db, logbook.db, users.db"
    echo ""
    echo "Contoh perintah scp dari VPS lama atau laptop Anda:"
    echo "  scp .env.bot ${TARGET_USER}@${vps_ip}:${MIGRATION_DIR}/"
    echo "  scp bot-services_backup_*.zip ${TARGET_USER}@${vps_ip}:${MIGRATION_DIR}/"
    echo "  # atau jika menyalin file database mentah:"
    echo "  scp data/*.db ${TARGET_USER}@${vps_ip}:${MIGRATION_DIR}/"
    echo ""
    echo "Lokasi target akhir sesudah diimpor script:"
    echo "  • Config final : $APP_DIR/.env.bot"
    echo "  • Data DB final: $APP_DIR/data/*.db"
    echo ""
}

run_migration_setup() {
    section "6. MIGRASI DATA & KONFIGURASI DARI VPS LAMA"
    print_migration_placement_guide

    local src_dir=""
    src_dir=$(prompt_default "Masukkan path folder sumber file migrasi" "$MIGRATION_DIR")
    src_dir="${src_dir/#\~/$TARGET_HOME}"
    run_as_user mkdir -p "$src_dir" "$APP_DIR/data" "$APP_DIR/logs"

    while true; do
        local has_env=0 has_db_source=0 latest_zip=""
        [[ -f "$src_dir/.env.bot" || -f "$src_dir/.env" || -f "$APP_DIR/.env.bot" || -f "$APP_DIR/.env" ]] && has_env=1

        latest_zip="$(find "$src_dir" -maxdepth 1 -type f -name '*.zip' 2>/dev/null | sort | tail -n 1 || true)"
        if [[ -n "$latest_zip" ]] || compgen -G "$src_dir/*.db" >/dev/null || compgen -G "$APP_DIR/data/*.db" >/dev/null; then
            has_db_source=1
        fi

        if [[ $has_env -eq 1 && $has_db_source -eq 1 ]]; then
            break
        fi

        warn "File migrasi belum lengkap ditemukan."
        [[ $has_env -eq 0 ]] && echo "  - Belum ditemukan .env.bot / .env di $src_dir maupun $APP_DIR"
        [[ $has_db_source -eq 0 ]] && echo "  - Belum ditemukan arsip .zip atau file *.db di $src_dir maupun $APP_DIR/data/"
        echo "Silakan transfer file terlebih dahulu (buka terminal lain untuk scp), lalu tekan ENTER."
        pause_enter "Tekan ENTER setelah file selesai diletakkan (atau Ctrl+C untuk batal)..."
    done

    # 1. Impor .env.bot / .env
    if [[ -f "$src_dir/.env.bot" ]]; then
        run_as_user cp "$src_dir/.env.bot" "$APP_DIR/.env.bot"
        success "Menyalin $src_dir/.env.bot -> $APP_DIR/.env.bot"
    elif [[ -f "$src_dir/.env" ]]; then
        run_as_user cp "$src_dir/.env" "$APP_DIR/.env.bot"
        success "Menyalin $src_dir/.env -> $APP_DIR/.env.bot"
    fi
    [[ -f "$APP_DIR/.env.bot" ]] && run_as_user chmod 600 "$APP_DIR/.env.bot"

    # 2. Cadangkan DB eksisting di target sebelum ditimpa (jika ada)
    if compgen -G "$APP_DIR/data/*.db" >/dev/null; then
        local pre_bak="$APP_DIR/backups/pre_migration_$(date +%Y%m%d_%H%M%S)"
        run_as_user mkdir -p "$pre_bak"
        run_as_user cp "$APP_DIR"/data/*.db* "$pre_bak/" 2>/dev/null || true
        info "Database eksisting di $APP_DIR/data/ dicadangkan ke $pre_bak"
    fi

    # 3. Ekstrak ZIP atau salin *.db dari folder sumber
    latest_zip="$(find "$src_dir" -maxdepth 1 -type f -name '*.zip' 2>/dev/null | sort | tail -n 1 || true)"
    if [[ -n "$latest_zip" ]]; then
        info "Mengekstrak arsip backup: $latest_zip -> $APP_DIR/data/"
        local tmp_unzip=""
        tmp_unzip="$(run_as_user mktemp -d)"
        run_as_user unzip -o -q "$latest_zip" -d "$tmp_unzip"
        # Bersihkan WAL/SHM usang sebelum menaruh snapshot konsisten dari ZIP
        rm -f "$APP_DIR"/data/*.db-wal "$APP_DIR"/data/*.db-shm
        while IFS= read -r db_file; do
            run_as_user cp "$db_file" "$APP_DIR/data/"
            success "Impor dari ZIP: $(basename "$db_file")"
        done < <(find "$tmp_unzip" -type f -name '*.db')
        rm -rf "$tmp_unzip"
    elif compgen -G "$src_dir/*.db" >/dev/null; then
        info "Menyalin file *.db dari $src_dir -> $APP_DIR/data/"
        rm -f "$APP_DIR"/data/*.db-wal "$APP_DIR"/data/*.db-shm
        for db_file in "$src_dir"/*.db; do
            [[ -f "$db_file" ]] || continue
            run_as_user cp "$db_file" "$APP_DIR/data/"
            [[ -f "${db_file}-wal" ]] && run_as_user cp "${db_file}-wal" "$APP_DIR/data/"
            [[ -f "${db_file}-shm" ]] && run_as_user cp "${db_file}-shm" "$APP_DIR/data/"
            success "Impor file DB: $(basename "$db_file")"
        done
    else
        info "Menggunakan file *.db yang sudah tersedia langsung di $APP_DIR/data/."
    fi

    run_root chown -R "${TARGET_USER}:${TARGET_GROUP}" "$APP_DIR/data" "$APP_DIR/logs"
    verify_migrated_environment
}

verify_migrated_environment() {
    info "Memverifikasi integritas SQLite, jumlah baris, konfigurasi env, & kecocokan LOGBOOK_SECRET_KEY..."
    run_in_app_dir "$APP_DIR/.venv/bin/python" - <<'PYEOF'
import asyncio
from contextlib import closing
import sqlite3
import sys
from app.core.config import get_settings
from app.database.fuel_repo import init_fuel_db
from app.database.logbook_repo import init_logbook_db
from app.database.reminder_repo import init_reminder_db
from app.services.crypto import decrypt_text

settings = get_settings()
print("[CFG] TELEGRAM_TOKEN terdeteksi | ADMIN_CHAT_ID =", settings.ADMIN_CHAT_ID, "| PORT =", settings.LOGBOOK_API_PORT)

db_files = [
    settings.REMINDER_DB_PATH,
    settings.BENSIN_DB_PATH,
    settings.LOGBOOK_DB_PATH,
    settings.MAGANG_DB_PATH,
]

for p in db_files:
    if not p.exists():
        print(f"[DB] {p.name} belum ada (akan dibuat saat inisialisasi).")
        continue
    with closing(sqlite3.connect(str(p))) as conn:
        cur = conn.cursor()
        chk = cur.execute("PRAGMA integrity_check;").fetchall()
        status = "OK" if (len(chk) == 1 and str(chk[0][0]).lower() == "ok") else str(chk)
        if status != "OK":
            print(f"[ERR] Integrity check GAGAL pada {p}: {status}", file=sys.stderr)
            sys.exit(2)
        tables = [
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            ).fetchall()
        ]
        counts = {
            t: cur.execute(f'SELECT COUNT(*) FROM "{t.replace(chr(34), chr(34)*2)}";').fetchone()[0]
            for t in tables
        }
        print(f"[DB OK] {p.name}: integrity={status} | tables={counts}")

        if p == settings.LOGBOOK_DB_PATH and "logbook_credentials" in tables:
            row = cur.execute("SELECT chat_id, username, password_encrypted FROM logbook_credentials LIMIT 1").fetchone()
            if row and row[2]:
                try:
                    decrypt_text(row[2])
                    print(f"[CRYPTO OK] LOGBOOK_SECRET_KEY cocok dengan data terenkripsi (contoh user: {row[1]}).")
                except Exception as exc:
                    print(
                        f"[ERR] LOGBOOK_SECRET_KEY di .env.bot TIDAK COCOK dengan data di logbook.db ({exc})! "
                        "Pastikan LOGBOOK_SECRET_KEY / MAGANG_SECRET_KEY sama persis dengan VPS lama.",
                        file=sys.stderr,
                    )
                    sys.exit(3)

async def sync_schemas():
    await init_reminder_db()
    await init_fuel_db()
    await init_logbook_db()

asyncio.run(sync_schemas())
PYEOF
    read_api_port_from_settings
    success "Seluruh database migrasi lolos integrity check & skema terbaru tersinkronisasi."
}

# --- FIREWALL & SYSTEMD ---
configure_firewall_and_systemd() {
    section "7. KONFIGURASI FIREWALL (UFW) & SERVICE SYSTEMD"

    if command -v ufw >/dev/null 2>&1; then
        local ufw_status=""
        ufw_status="$(run_root ufw status 2>/dev/null | head -n 1 || true)"
        info "Status UFW: ${ufw_status:-unknown}"
        if echo "$ufw_status" | grep -qi "active"; then
            if prompt_yes_no "Buka port TCP $API_PORT di UFW (untuk receiver HTTP logbook-cli)?" "y"; then
                run_root ufw allow "${API_PORT}/tcp"
                success "Port ${API_PORT}/tcp diizinkan pada UFW."
            fi
        fi
    fi

    if [[ "$INSTALL_MODE" == "migrate" ]]; then
        echo ""
        warn "PENTING UNTUK MIGRASI: Pastikan service bot di VPS LAMA sudah dimatikan (sudo systemctl stop bot-services) agar tidak terjadi bentrok polling TELEGRAM_TOKEN!"
        pause_enter "Tekan ENTER jika bot di VPS lama sudah dimatikan..."
    fi

    local service_file="/etc/systemd/system/${DEFAULT_SERVICE_NAME}.service"
    info "Menulis unit file systemd ke $service_file..."
    cat <<EOF | run_root tee "$service_file" >/dev/null
[Unit]
Description=Bot Telegram Service (${DEFAULT_SERVICE_NAME})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${TARGET_USER}
Group=${TARGET_GROUP}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/main.py
Restart=always
RestartSec=5
TimeoutStopSec=15
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

[Install]
WantedBy=multi-user.target
EOF

    run_root systemctl daemon-reload
    run_root systemctl enable "$DEFAULT_SERVICE_NAME"
    run_root systemctl restart "$DEFAULT_SERVICE_NAME"
    success "Service systemd '$DEFAULT_SERVICE_NAME' aktif dan di-enable untuk auto-start saat boot."
}

# --- VERIFIKASI & RINGKASAN AKHIR ---
verify_running_service() {
    section "8. VERIFIKASI LAYANAN & ENDPOINT HEALTH"
    sleep 3

    local active_state=""
    active_state="$(run_root systemctl is-active "$DEFAULT_SERVICE_NAME" || true)"
    if [[ "$active_state" == "active" ]]; then
        success "Status systemd: active (running)"
    else
        err "Service belum berstatus active (status: $active_state). Cek log dengan: sudo journalctl -u $DEFAULT_SERVICE_NAME -n 50 --no-pager"
    fi

    local health_out=""
    if health_out="$(curl -fsS --max-time 5 "http://127.0.0.1:${API_PORT}/api/health" 2>/dev/null)"; then
        success "HTTP Health API (port $API_PORT): $health_out"
    else
        warn "HTTP Health API di port $API_PORT belum merespons. Cek journalctl/logs."
    fi
}

print_final_summary() {
    section "9. RINGKASAN LOKASI FILE & LANGKAH MANUAL AKHIR"
    echo "Lokasi seluruh file penting bot-services di VPS Anda:"
    echo "  • Direktori proyek : $APP_DIR"
    echo "  • Virtualenv       : $APP_DIR/.venv"
    echo "  • Config & Secret  : $APP_DIR/.env.bot  (chmod 600)"
    echo "  • Database SQLite  : $APP_DIR/data/  (reminders.db, bensin.db, logbook.db)"
    echo "  • Log aplikasi     : $APP_DIR/logs/bot.log"
    echo "  • Unit systemd     : /etc/systemd/system/${DEFAULT_SERVICE_NAME}.service"
    echo ""
    echo "Perintah operasional berguna:"
    echo "  sudo systemctl status $DEFAULT_SERVICE_NAME"
    echo "  sudo systemctl restart $DEFAULT_SERVICE_NAME"
    echo "  sudo journalctl -u $DEFAULT_SERVICE_NAME -n 50 -f"
    echo "  tail -n 50 -f $APP_DIR/logs/bot.log"
    echo ""
    echo -e "${C_CYAN}[KEAMANAN]${C_RESET} Simpan salinan LOGBOOK_SECRET_KEY & MAGANG_SECRET_KEY dari $APP_DIR/.env.bot ke password manager terpisah dari arsip /backup."
    echo ""

    if [[ "$SSH_NEEDS_GITHUB" -eq 1 ]] || ! test_github_ssh; then
        echo -e "${C_YELLOW}========================================================================${C_RESET}"
        echo -e "${C_YELLOW}  TINDAKAN MANUAL DIPERLUKAN: TAMBAHKAN SSH KEY VPS KE GITHUB${C_RESET}"
        echo -e "${C_YELLOW}========================================================================${C_RESET}"
        echo "Script tidak dapat mengunggah SSH public key ke akun GitHub Anda secara otomatis."
        echo "Agar 'git pull' via SSH (git@github.com:Oktavian19/bot-services.git) berfungsi,"
        echo "salin public key di bawah ini dan tempelkan ke GitHub Anda:"
        echo ""
        [[ -f "$PUBKEY_PATH" ]] && cat "$PUBKEY_PATH"
        echo ""
        echo "  1. Buka: https://github.com/settings/ssh/new"
        echo "     (atau Deploy Key repo: https://github.com/Oktavian19/bot-services/settings/keys/new)"
        echo "  2. Tempel public key di atas dan simpan."
        echo "  3. Uji dari VPS: ssh -T git@github.com"
        echo ""
    else
        success "SSH key GitHub VPS ini sudah aktif. 'git pull' via SSH siap digunakan."
    fi

    echo -e "${C_GREEN}Setup selesai! Silakan uji dengan mengirim /start atau /ping ke bot Telegram Anda.${C_RESET}"
}

main() {
    resolve_runtime_context
    choose_install_mode
    install_system_packages
    setup_github_ssh_and_repo
    setup_python_venv

    if [[ "$INSTALL_MODE" == "fresh" ]]; then
        run_fresh_setup
    else
        run_migration_setup
    fi

    configure_firewall_and_systemd
    verify_running_service
    print_final_summary
}

main "$@"
