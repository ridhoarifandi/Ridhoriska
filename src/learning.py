"""Pembelajaran adaptif berbasis hasil trade (belajar dari kekalahan).

Filosofi: JANGAN overfit ke sedikit trade. Yang dilakukan:
  - Catat semua trade yang ditutup ke jurnal (state/trade_log.json).
  - Dari hasil terakhir, hitung win rate & jumlah SL beruntun.
  - Setelah SL beruntun / win rate turun: PERKETAT filter (tambah 'focus_penalty'
    ke ambang skor) dan aktifkan COOLDOWN (jeda sinyal baru sementara).
  - Saat performa membaik (ada TP): penalti mengecil sendiri (dihitung ulang dari
    riwayat, bukan menumpuk).

Semua transparan & deterministik — bukan black box.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

DECIDED = {"SL", "TP1", "TP2", "TP3"}


def _read(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def load_log(path: Path) -> list[dict]:
    d = _read(path)
    return d if isinstance(d, list) else []


def load_adaptive(path: Path) -> dict:
    d = _read(path)
    return d if isinstance(d, dict) else {}


def save_json(path: Path, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sync(trade_log: list[dict], positions: list[dict]) -> list[dict]:
    """Tambah posisi yang baru DITUTUP ke jurnal (idempoten by id). Return yang baru."""
    known = {t.get("id") for t in trade_log}
    added: list[dict] = []
    for p in positions:
        if p.get("status") == "closed" and p.get("id") not in known:
            rec = {
                "id": p["id"], "symbol": p["symbol"], "direction": p["direction"],
                "order_type": p.get("order_type"), "result": p.get("result"),
                "entry": p.get("entry"), "sl": p.get("sl"), "rr": p.get("rr"),
                "opened_at": p.get("opened_at"), "closed_at": p.get("closed_at"),
                "context": p.get("context") or {},
            }
            trade_log.append(rec)
            added.append(rec)
    # jaga ukuran jurnal (simpan 500 terakhir)
    if len(trade_log) > 500:
        del trade_log[:-500]
    return added


def _in_cooldown(cu: str | None) -> bool:
    if not cu:
        return False
    try:
        return datetime.now(timezone.utc) < datetime.fromisoformat(cu)
    except Exception:  # noqa: BLE001
        return False


def in_cooldown(adaptive: dict) -> bool:
    return _in_cooldown(adaptive.get("cooldown_until"))


def recompute(trade_log: list[dict], cfg: dict, prev: dict, new_sl: bool) -> dict:
    lc = cfg.get("learning", {})
    window = int(lc.get("recent_window", 20))
    target = float(lc.get("target_winrate", 0.30))
    step = float(lc.get("focus_penalty_step", 0.05))
    pmax = float(lc.get("focus_penalty_max", 0.15))
    cd_n = int(lc.get("cooldown_after_consecutive_sl", 3))
    cd_h = float(lc.get("cooldown_hours", 6))

    decided = [t for t in trade_log if t.get("result") in DECIDED]

    consec = 0
    for t in reversed(decided):
        if t["result"] == "SL":
            consec += 1
        else:
            break

    recent = decided[-window:]
    wins = sum(1 for t in recent if str(t["result"]).startswith("TP"))
    wr = (wins / len(recent)) if recent else None

    # penalti dihitung ulang dari riwayat (tidak menumpuk antar-run)
    penalty = 0.0
    if consec >= 2:
        penalty += step * min(consec - 1, 3)
    if len(recent) >= 8 and wr is not None and wr < target:
        penalty += step
    penalty = round(min(penalty, pmax), 3)

    # cooldown: dipicu SL BARU yang capai ambang; tidak menumpuk; lepas saat streak putus.
    active_prev = _in_cooldown(prev.get("cooldown_until"))
    cooldown_until = prev.get("cooldown_until") if active_prev else None
    if consec == 0:
        cooldown_until = None  # ada kemenangan / tidak ada SL beruntun -> lepas cooldown
    elif new_sl and consec >= cd_n and not active_prev:
        cooldown_until = (datetime.now(timezone.utc) + timedelta(hours=cd_h)).isoformat()

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "decided_trades": len(decided),
        "recent_winrate": None if wr is None else round(wr, 3),
        "consecutive_sl": consec,
        "focus_penalty": penalty,
        "cooldown_until": cooldown_until,
    }
