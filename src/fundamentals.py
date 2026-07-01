"""Dukungan fundamental: kalender ekonomi + berita.

Mengganti peran investing.com/investpy (yang sudah tidak berfungsi) dengan:
  - Kalender ekonomi: feed gratis ForexFactory (faireconomy) — event USD high-impact
    seperti NFP, CPI, FOMC. Dipakai sebagai 'news blackout': tahan sinyal saat event
    berisiko tinggi sedang imminent.
  - Berita: tradingview_scraper.NewsScraper — headline terbaru untuk simbol.

Semua bersifat 'best effort': bila sumber gagal diakses, sistem tetap jalan
(tidak memblokir sinyal hanya karena error jaringan).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

DEFAULT_CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_UA = {"User-Agent": "Mozilla/5.0"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _fetch_calendar(url: str) -> list[dict]:
    r = requests.get(url, timeout=25, headers=_UA)
    data = r.json()
    return data if isinstance(data, list) else []


def assess(cfg: dict, symbol: str, exchange: str) -> dict:
    """Gabungan: status blackout, event berikutnya, dan headline berita."""
    f = cfg.get("fundamentals", {})
    out: dict[str, Any] = {
        "blackout": False, "event": None, "next_event": None,
        "headlines": [], "cal_error": None,
    }

    currencies = set(f.get("currencies", ["USD"]))
    impacts = set(f.get("impact_filter", ["High"]))
    before = timedelta(minutes=float(f.get("news_blackout_minutes_before", 30)))
    after = timedelta(minutes=float(f.get("news_blackout_minutes_after", 15)))
    url = f.get("calendar_url", DEFAULT_CAL_URL)

    # 1) Kalender ekonomi -> blackout + event berikutnya
    try:
        events = _fetch_calendar(url)
        now = _now_utc()
        future = []
        for e in events:
            if e.get("country") not in currencies or e.get("impact") not in impacts:
                continue
            dt = _parse_dt(e.get("date"))
            if dt is None:
                continue
            if (dt - before) <= now <= (dt + after):
                out["blackout"] = True
                mins = int((dt - now).total_seconds() // 60)
                out["event"] = {
                    "title": e.get("title"), "impact": e.get("impact"),
                    "in_minutes": mins, "country": e.get("country"),
                }
            if dt >= now:
                future.append((dt, e))
        future.sort(key=lambda x: x[0])
        if future:
            dt, e = future[0]
            out["next_event"] = {
                "title": e.get("title"),
                "in_minutes": int((dt - now).total_seconds() // 60),
                "forecast": e.get("forecast"), "previous": e.get("previous"),
                "country": e.get("country"),
            }
    except Exception as ex:  # noqa: BLE001
        out["cal_error"] = f"{type(ex).__name__}: {ex}"

    # 2) Berita terbaru (best effort)
    n = int(f.get("show_headlines", 3))
    if n > 0:
        out["headlines"] = latest_headlines(symbol, exchange, n)
    return out


def latest_headlines(symbol: str, exchange: str, n: int = 3) -> list[dict]:
    try:
        from tradingview_scraper.symbols.news import NewsScraper
        items = NewsScraper().scrape_headlines(symbol=symbol, exchange=exchange, sort="latest")
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    now = time.time()
    for it in (items or []):
        if not isinstance(it, dict) or not it.get("title"):
            continue
        ts = it.get("published")
        age = ""
        if isinstance(ts, (int, float)):
            hrs = (now - ts) / 3600
            age = f"{int(hrs)}j lalu" if hrs >= 1 else f"{max(0,int(hrs*60))}m lalu"
        out.append({"title": it.get("title"), "age": age, "source": it.get("source")})
        if len(out) >= n:
            break
    return out
