#!/usr/bin/env bash
# ============================================================
#  Setup Market Signal Assistant di VPS Ubuntu (22.04 / 24.04)
#  Jalankan dari folder project:  bash deploy/setup_vps.sh
# ============================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
echo ">> Folder project: $APP_DIR"

# 0) Normalkan akhir baris (kalau file diupload dari Windows / CRLF)
sed -i 's/\r$//' deploy/run_once.sh deploy/setup_vps.sh 2>/dev/null || true

echo ">> [1/6] Update sistem & install Python..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip tzdata cron

echo ">> [2/6] Set timezone ke Asia/Jakarta (WIB)..."
sudo timedatectl set-timezone Asia/Jakarta || sudo ln -sf /usr/share/zoneinfo/Asia/Jakarta /etc/localtime

echo ">> [3/6] Buat virtualenv & install dependencies..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

echo ">> [4/6] Set data_backend=direct (paling simpel utk VPS headless)..."
sed -i 's/^data_backend:.*/data_backend: direct/' config.yaml

echo ">> [5/6] Siapkan .env (kalau belum ada)..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "   -> .env dibuat dari contoh. WAJIB diisi: nano .env"
fi
chmod +x deploy/run_once.sh

echo ">> [6/6] Pasang cron: tiap 30 menit, 14:00-23:00 WIB, Senin-Jumat..."
RUN="$APP_DIR/deploy/run_once.sh"
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'run_once.sh' > "$TMP" || true
echo "*/30 14-22 * * 1-5 $RUN"   >> "$TMP"   # 14:00, 14:30, ... 22:30
echo "0 23 * * 1-5 $RUN"         >> "$TMP"   # 23:00
crontab "$TMP"
rm -f "$TMP"

echo ""
echo "============================================================"
echo "SELESAI. Langkah terakhir:"
echo "  1) Isi kredensial:        nano .env"
echo "     (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY opsional)"
echo "  2) Tes manual:            .venv/bin/python -m src.main --dry-run --backend direct"
echo "  3) Tes kirim Telegram:    .venv/bin/python -m src.main"
echo "  Cek jadwal cron:          crontab -l"
echo "  Cek log:                  tail -f logs/run.log"
echo "============================================================"
