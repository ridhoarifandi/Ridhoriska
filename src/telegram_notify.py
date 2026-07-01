"""Kirim pesan ke Telegram via Bot API."""
from __future__ import annotations

import requests


def send(cfg: dict, text: str) -> tuple[bool, str]:
    tg = cfg.get("telegram", {})
    if not tg.get("enabled", True):
        return False, "telegram dinonaktifkan di config"
    token = cfg["secrets"]["telegram_bot_token"]
    chat_id = cfg["secrets"]["telegram_chat_id"]
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID kosong di .env"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": tg.get("parse_mode", "Markdown"),
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200 and r.json().get("ok"):
            return True, "terkirim"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.RequestException as e:
        return False, f"{type(e).__name__}: {e}"
