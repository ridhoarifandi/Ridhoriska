#!/usr/bin/env bash
# Dipanggil oleh cron tiap 30 menit. Jalankan satu analisa lalu keluar.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
mkdir -p logs
echo "[$(date '+%F %T %Z')] === run start ===" >> logs/run.log
"$APP_DIR/.venv/bin/python" -m src.main "$@" >> logs/run.log 2>&1
