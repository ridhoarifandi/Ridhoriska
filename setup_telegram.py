"""Pembantu koneksi Telegram.

Langkah:
  1. Buat bot di Telegram lewat @BotFather -> dapat TOKEN.
  2. Isi TELEGRAM_BOT_TOKEN di file .env (skrip ini TIDAK menyentuh token Anda).
  3. Buka chat bot Anda di Telegram, kirim pesan apa saja (mis. "halo").
  4. Jalankan:  .\.venv\Scripts\python.exe setup_telegram.py

Skrip akan: ambil chat_id otomatis dari pesan terakhir -> tulis ke .env -> kirim
pesan tes untuk memastikan koneksi berhasil.
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env"


def _set_env_line(key: str, value: str) -> None:
    """Tulis/ubah satu baris KEY=value di .env tanpa merusak baris lain."""
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(ENV)
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token or token.startswith("123456789:AA"):
        print("❌ TELEGRAM_BOT_TOKEN belum diisi di .env.")
        print("   Buat bot lewat @BotFather, salin token-nya ke .env, lalu ulangi.")
        return 1

    # 1) Ambil chat_id dari update terakhir
    print("→ Mengambil chat_id dari pesan terakhir ke bot...")
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
        data = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"❌ Gagal menghubungi Telegram: {e}")
        return 1

    if not data.get("ok"):
        print(f"❌ Token ditolak Telegram: {data}")
        print("   Pastikan token dari @BotFather benar.")
        return 1

    chat_id = None
    name = ""
    for upd in reversed(data.get("result", [])):
        msg = upd.get("message") or upd.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            chat_id = chat["id"]
            name = chat.get("first_name") or chat.get("title") or ""
            break

    if chat_id is None:
        print("⚠️  Belum ada pesan terdeteksi.")
        print("   Buka chat bot Anda di Telegram, kirim 'halo', lalu jalankan ulang skrip ini.")
        return 1

    _set_env_line("TELEGRAM_CHAT_ID", str(chat_id))
    print(f"✅ chat_id ditemukan: {chat_id} ({name}) — sudah ditulis ke .env")

    # 2) Kirim pesan tes
    print("→ Mengirim pesan tes...")
    test = ("✅ *Market Signal Assistant* terhubung!\n"
            "Bot siap mengirim sinyal XAUUSD (scalping M1/M5) ke sini.")
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": test, "parse_mode": "Markdown"},
            timeout=20,
        )
        if r.json().get("ok"):
            print("🎉 Berhasil! Cek Telegram Anda — pesan tes sudah masuk.")
            print("   Koneksi Telegram beres. Sisa: isi ANTHROPIC_API_KEY (opsional) di .env.")
            return 0
        print(f"❌ Gagal kirim: {r.text}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"❌ Gagal kirim pesan tes: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
