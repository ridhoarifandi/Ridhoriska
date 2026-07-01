"""Load konfigurasi dari config.yaml + variabel rahasia dari .env."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    """Baca config.yaml dan gabungkan rahasia dari .env."""
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cfg["_root"] = str(ROOT)
    cfg.setdefault("secrets", {})
    cfg["secrets"] = {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    }
    return cfg
