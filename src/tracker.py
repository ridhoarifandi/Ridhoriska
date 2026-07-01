"""Pelacak posisi: pantau sinyal yang sudah dikirim, deteksi FILL / TP / SL.

State disimpan di JSON (di GitHub Actions di-commit balik ke repo agar persisten
antar-run). Harga cek diambil dari close TF entry tiap run (granularitas ~30 menit,
jadi bisa saja melewatkan spike singkat — keterbatasan yang wajar).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_hours(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return 0.0


def load(path: Path) -> list[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def save(path: Path, positions: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # simpan semua yang terbuka + maksimal 40 yang sudah ditutup (biar tidak membengkak)
    open_pos = [x for x in positions if x.get("status") != "closed"]
    closed = [x for x in positions if x.get("status") == "closed"][-40:]
    p.write_text(json.dumps(open_pos + closed, ensure_ascii=False, indent=2), encoding="utf-8")


def has_open(positions: list[dict], symbol: str, direction: str) -> bool:
    return any(
        x for x in positions
        if x.get("symbol") == symbol and x.get("direction") == direction
        and x.get("status") in ("pending", "active")
    )


def register(positions: list[dict], symbol: str, setup, direction: str, cfg: dict,
             context: dict | None = None) -> dict | None:
    """Daftarkan sinyal baru sebagai posisi. Dedup: satu posisi terbuka per arah."""
    if setup is None:
        return None
    if has_open(positions, symbol, direction):
        return None
    is_market = getattr(setup, "order_type", "limit") == "market"
    pos = {
        "id": f"{symbol}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{direction}",
        "symbol": symbol,
        "direction": direction,
        "order_type": getattr(setup, "order_type", "limit"),
        "entry": setup.entry,
        "sl": setup.sl,
        "tps": list(setup.tps),
        "rr": list(setup.rr),
        "status": "active" if is_market else "pending",
        "opened_at": _now(),
        "filled_at": _now() if is_market else None,
        "closed_at": None,
        "tp_hit": [False] * len(setup.tps),
        "result": None,
        "context": context or {},
    }
    positions.append(pos)
    return pos


def update(positions: list[dict], symbol: str, price: float, cfg: dict) -> list[dict]:
    """Perbarui status posisi symbol terhadap harga sekarang. Return daftar notifikasi."""
    tconf = cfg.get("tracking", {})
    max_age = float(tconf.get("max_age_hours", 24))
    notifs: list[dict] = []

    for p in positions:
        if p.get("symbol") != symbol or p.get("status") == "closed":
            continue
        d = p["direction"]
        entry, sl, tps = p["entry"], p["sl"], p["tps"]

        # kadaluarsa
        if _age_hours(p["opened_at"]) > max_age and p["status"] in ("pending", "active"):
            p["status"] = "closed"
            p["result"] = "expired"
            p["closed_at"] = _now()
            continue

        if p["status"] == "pending":
            filled = (d == "BUY" and price <= entry) or (d == "SELL" and price >= entry)
            invalid = (d == "BUY" and price <= sl) or (d == "SELL" and price >= sl)
            if filled:
                p["status"] = "active"
                p["filled_at"] = _now()
                notifs.append({"type": "filled", "pos": p, "price": price})
            elif invalid:
                p["status"] = "closed"
                p["result"] = "cancelled"
                p["closed_at"] = _now()
                notifs.append({"type": "cancelled", "pos": p, "price": price})
            continue

        if p["status"] == "active":
            hit_sl = (d == "BUY" and price <= sl) or (d == "SELL" and price >= sl)
            if hit_sl:
                p["status"] = "closed"
                p["result"] = "SL"
                p["closed_at"] = _now()
                notifs.append({"type": "sl", "pos": p, "price": price})
                continue
            for i, tp in enumerate(tps):
                if p["tp_hit"][i]:
                    continue
                reached = (d == "BUY" and price >= tp) or (d == "SELL" and price <= tp)
                if reached:
                    p["tp_hit"][i] = True
                    notifs.append({"type": "tp", "pos": p, "price": price,
                                   "tp_index": i, "tp": tp, "rr": p["rr"][i]})
                    if i == len(tps) - 1:  # TP terakhir -> tutup
                        p["status"] = "closed"
                        p["result"] = f"TP{i+1}"
                        p["closed_at"] = _now()
    return notifs
