"""Recap bulanan performa trade — statistik + daftar tiap trade.

Dipakai dua cara:
  - Otomatis: dikirim ke Telegram di awal bulan baru (recap bulan sebelumnya).
  - Manual:   python -m src.report [YYYY-MM] [--send] [--save]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_RR_FALLBACK = {"TP1": 3.0, "TP2": 5.0, "TP3": 8.0}
_BULAN = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember"]
_WIB = timezone(timedelta(hours=7))


def _dt(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso).astimezone(_WIB)
    except Exception:  # noqa: BLE001
        return None


def month_key(iso: str | None) -> str | None:
    d = _dt(iso)
    return d.strftime("%Y-%m") if d else None


def month_label(month: str) -> str:
    try:
        y, m = month.split("-")
        return f"{_BULAN[int(m)]} {y}"
    except Exception:  # noqa: BLE001
        return month


def prev_month_of(dt: datetime) -> str:
    first = dt.replace(day=1)
    last_prev = first - timedelta(days=1)
    return last_prev.strftime("%Y-%m")


def r_value(t: dict) -> float:
    res = t.get("result")
    if res == "SL":
        return -1.0
    if res and str(res).startswith("TP"):
        try:
            idx = int(str(res)[2:]) - 1
        except ValueError:
            return _RR_FALLBACK.get(res, 0.0)
        rr = t.get("rr")
        if isinstance(rr, list) and 0 <= idx < len(rr):
            return float(rr[idx])
        return _RR_FALLBACK.get(res, 0.0)
    return 0.0  # expired / cancelled


def trades_in_month(trade_log: list[dict], month: str) -> list[dict]:
    out = [t for t in trade_log
           if month_key(t.get("closed_at") or t.get("opened_at")) == month]
    out.sort(key=lambda t: t.get("closed_at") or t.get("opened_at") or "")
    return out


def build_recap(trade_log: list[dict], month: str, max_list: int = 40) -> str:
    trades = trades_in_month(trade_log, month)
    head = f"📊 *RECAP BULANAN — {month_label(month)}*"
    if not trades:
        return head + "\n\nBelum ada trade yang selesai di bulan ini."

    wins = [t for t in trades if str(t.get("result")).startswith("TP")]
    losses = [t for t in trades if t.get("result") == "SL"]
    other = [t for t in trades if t.get("result") in ("expired", "cancelled")]
    decided = len(wins) + len(losses)
    wr = (len(wins) / decided * 100) if decided else 0.0
    total_r = sum(r_value(t) for t in trades)
    exp_r = total_r / decided if decided else 0.0

    by_res: dict[str, int] = {}
    for t in trades:
        by_res[t.get("result")] = by_res.get(t.get("result"), 0) + 1
    mkt = sum(1 for t in trades if t.get("order_type") == "market")
    lim = sum(1 for t in trades if t.get("order_type") == "limit")

    lines = [head, ""]
    lines.append(f"Trade selesai: *{decided}*  (menang {len(wins)} / kalah {len(losses)})")
    lines.append(f"Win rate: *{wr:.1f}%*")
    res_str = " | ".join(f"{k} {v}" for k, v in sorted(by_res.items()))
    lines.append(f"Rincian: {res_str}")
    lines.append(f"Hasil: *{total_r:+.1f} R* total  (ekspektasi {exp_r:+.2f} R/trade)")
    lines.append(f"Order: NOW {mkt} | limit {lim}")
    if other:
        lines.append(f"_(+{len(other)} order tak ke-fill/kadaluarsa)_")

    # daftar tiap trade (dibatasi biar tidak kepanjangan)
    lines.append("")
    lines.append("*Daftar trade:*")
    shown = trades[-max_list:]
    if len(trades) > max_list:
        lines.append(f"_(menampilkan {max_list} terakhir dari {len(trades)})_")
    lines.append("```")
    for t in shown:
        d = _dt(t.get("closed_at") or t.get("opened_at"))
        tgl = d.strftime("%d/%m %H:%M") if d else "-"
        ot = "NOW" if t.get("order_type") == "market" else "lim"
        res = t.get("result") or "-"
        r = r_value(t)
        lines.append(f"{tgl}  {t.get('direction','?'):4} {ot}  {res:9} {r:+.0f}R")
    lines.append("```")
    lines.append("_Recap otomatis. Bukan nasihat keuangan._")
    return "\n".join(lines)


def _main(argv=None) -> int:
    from . import config as config_mod
    from . import learning as learning_mod
    from . import telegram_notify

    p = argparse.ArgumentParser(description="Recap bulanan performa trade")
    p.add_argument("month", nargs="?", help="YYYY-MM (default: bulan ini WIB)")
    p.add_argument("--send", action="store_true", help="kirim ke Telegram")
    p.add_argument("--save", action="store_true", help="simpan ke reports/RECAP-YYYY-MM.md")
    args = p.parse_args(argv)

    cfg = config_mod.load_config()
    tl_path = Path(cfg["_root"]) / cfg["learning"]["trade_log"]
    trade_log = learning_mod.load_log(tl_path)
    month = args.month or datetime.now(_WIB).strftime("%Y-%m")

    text = build_recap(trade_log, month)
    print(text)

    if args.save:
        rp = Path(cfg["_root"]) / "reports"
        rp.mkdir(exist_ok=True)
        (rp / f"RECAP-{month}.md").write_text(text, encoding="utf-8")
        print(f"\n[disimpan: reports/RECAP-{month}.md]")
    if args.send:
        ok, info = telegram_notify.send(cfg, text)
        print(f"[Telegram: {info}]")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
