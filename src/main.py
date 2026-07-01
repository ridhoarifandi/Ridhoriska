"""Orkestrator satu kali jalan: ambil data -> rule -> reasoning -> kirim Telegram.

Dipanggil oleh Windows Task Scheduler pada jam tertentu.

Contoh:
    python -m src.main                 # jalan penuh (kirim Telegram)
    python -m src.main --dry-run       # cetak ke layar, tidak kirim
    python -m src.main --backend direct
    python -m src.main --no-reasoning
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config as config_mod
from . import fundamentals as fundamentals_mod
from . import learning as learning_mod
from . import reasoning as reasoning_mod
from . import report as report_mod
from . import rules as rules_mod
from . import telegram_notify
from . import tracker as tracker_mod
from . import tv_client
from .formatter import build_message, tracking_message
from .indicators import parse_reading


def _force_utf8_console() -> None:
    """Hindari UnicodeEncodeError di console Windows (cp1252) saat cetak emoji."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def run(cfg: dict, dry_run: bool = False) -> int:
    _log(f"Backend data: {cfg['data_backend']} | symbols: "
         f"{[s['symbol'] for s in cfg['symbols']]}")

    try:
        raw = tv_client.fetch_indicators(cfg)
    except Exception as e:  # noqa: BLE001
        _log(f"GAGAL ambil data: {type(e).__name__}: {e}")
        return 2

    signals_dir = Path(cfg["_root"]) / cfg["logging"]["signals_dir"]
    signals_dir.mkdir(exist_ok=True)
    sent = 0

    min_conf = float(cfg["reasoning"].get("min_confidence_to_signal", 0))

    # Pelacak posisi (untuk notif fill / TP / SL).
    tracking_on = cfg.get("tracking", {}).get("enabled", False)
    state_path = Path(cfg["_root"]) / cfg["tracking"]["state_file"] if tracking_on else None
    positions = tracker_mod.load(state_path) if tracking_on else []

    # Pembelajaran adaptif (belajar dari kekalahan).
    learn_on = cfg.get("learning", {}).get("enabled", False)
    trade_log: list = []
    adaptive: dict = {}
    cooling = False
    tl_path = ad_path = None
    if learn_on:
        tl_path = Path(cfg["_root"]) / cfg["learning"]["trade_log"]
        ad_path = Path(cfg["_root"]) / cfg["learning"]["adaptive_file"]
        trade_log = learning_mod.load_log(tl_path)
        adaptive = learning_mod.load_adaptive(ad_path)
        base_focus = float(cfg["signal"]["min_focus_score"])
        penalty = float(adaptive.get("focus_penalty", 0) or 0)
        cfg["signal"]["min_focus_score"] = round(base_focus + penalty, 3)
        cooling = learning_mod.in_cooldown(adaptive)
        if penalty or cooling:
            _log(f"Adaptif: min_focus {base_focus}->{cfg['signal']['min_focus_score']} "
                 f"(penalty {penalty}); SL beruntun {adaptive.get('consecutive_sl',0)}; "
                 f"cooldown={'AKTIF' if cooling else 'tidak'}")

    for s in cfg["symbols"]:
        symbol = s["symbol"]
        pip_size = float(s.get("pip_size", 0.0001))
        readings = {
            tf: parse_reading(tf, raw.get((symbol, tf), {}))
            for tf in cfg["timeframes"]
        }
        ok_tfs = [tf for tf, r in readings.items() if r.ok]
        _log(f"{symbol}: TF valid {ok_tfs or '— tidak ada data!'}")
        if not ok_tfs:
            _log(f"{symbol}: dilewati (tidak ada data indikator).")
            continue

        # --- Pantau posisi terbuka terhadap harga sekarang (fill / TP / SL) ---
        if tracking_on:
            eref = readings.get(cfg["signal"].get("entry_tf_for_levels", "5m"))
            price = eref.close if (eref and eref.ok and eref.close) else \
                next((r.close for r in readings.values() if r.ok and r.close), None)
            if price is not None:
                for nf in tracker_mod.update(positions, symbol, price, cfg):
                    if nf["type"] == "filled" and not cfg["tracking"].get("notify_on_fill", True):
                        continue
                    nmsg = tracking_message(nf)
                    _log(f"{symbol}: EVENT {nf['type']} @ {price}")
                    if dry_run:
                        print("\n[NOTIF]\n" + nmsg + "\n")
                    else:
                        ok, info = telegram_notify.send(cfg, nmsg)
                        _log(f"{symbol}: notif {nf['type']} -> {info}")
                        if ok:
                            sent += 1

        rule_sig = rules_mod.evaluate(symbol, readings, cfg, pip_size)

        # Fundamental (kalender ekonomi + berita) hanya saat ada kandidat sinyal.
        fund = None
        if rule_sig.action in ("BUY", "SELL") and cfg.get("fundamentals", {}).get("enabled"):
            fund = fundamentals_mod.assess(cfg, symbol, s["exchange"])
            if fund.get("blackout"):
                ev = fund.get("event") or {}
                _log(f"{symbol}: NEWS BLACKOUT — {ev.get('title')} "
                     f"(impact {ev.get('impact')}, ~{ev.get('in_minutes')} mnt) -> WAIT")

        blackout = bool(fund and fund.get("blackout"))
        if cooling and rule_sig.action in ("BUY", "SELL"):
            _log(f"{symbol}: COOLDOWN adaptif aktif (setelah SL beruntun) -> tahan sinyal baru")

        # Hemat biaya: panggil Claude HANYA saat ada kandidat, tidak blackout & tidak cooldown.
        ai = None
        if rule_sig.action in ("BUY", "SELL") and not blackout and not cooling:
            ai = reasoning_mod.confirm(cfg, symbol, readings, rule_sig, fund)

        # Gate confidence: Claude hanya boleh konfirmasi atau menurunkan ke WAIT.
        if ai and not ai.get("_error") and rule_sig.action in ("BUY", "SELL"):
            conf = ai.get("confidence")
            if ai.get("action") == "WAIT":
                ai["action"] = "WAIT"
                _log(f"{symbol}: Claude menurunkan sinyal -> WAIT")
            elif conf is not None and float(conf) < min_conf:
                ai["action"] = "WAIT"
                ai["gate_note"] = f"confidence {conf}% < ambang {min_conf:g}%"
                _log(f"{symbol}: confidence {conf}% < {min_conf:g}% -> WAIT")
            else:
                ai["action"] = rule_sig.action

        # aksi efektif: blackout berita atau cooldown adaptif memaksa WAIT.
        if blackout or cooling:
            final_action = "WAIT"
        else:
            final_action = ai["action"] if (ai and ai.get("action")) else rule_sig.action

        message = build_message(rule_sig, ai, fund=fund, action=final_action,
                                lang=cfg["reasoning"].get("language", "id"))

        _persist(signals_dir, symbol, rule_sig, ai, message, fund)
        _log(f"{symbol}: aksi={final_action} fokus={rule_sig.focus_score:+.2f}")

        # Catat posisi baru untuk dipantau (fill/TP/SL) — hanya sinyal nyata.
        if tracking_on and final_action in ("BUY", "SELL") and rule_sig.setup is not None:
            eref2 = readings.get(cfg["signal"].get("entry_tf_for_levels", "5m"))
            hour_wib = (datetime.now(timezone.utc) + timedelta(hours=7)).hour
            context = {
                "focus": rule_sig.focus_score,
                "guard": rule_sig.guard_score,
                "adx": round(eref2.adx, 1) if (eref2 and eref2.ok and eref2.adx) else None,
                "order_type": rule_sig.setup.order_type,
                "hour_wib": hour_wib,
                "near_news": bool(fund and (fund.get("next_event") or {}).get("in_minutes", 9e9) < 60),
            }
            newp = tracker_mod.register(positions, symbol, rule_sig.setup, final_action, cfg, context)
            if newp:
                _log(f"{symbol}: posisi dicatat ({newp['order_type']} {final_action}) id={newp['id']}")

        if dry_run:
            print("\n" + "-" * 48)
            print(message)
            print("-" * 48 + "\n")
            continue

        # Hanya kirim saat ada sinyal, kecuali send_on_wait=true.
        if final_action == "WAIT" and not cfg["telegram"].get("send_on_wait", False):
            _log(f"{symbol}: WAIT — tidak dikirim (send_on_wait=false).")
            continue

        ok, info = telegram_notify.send(cfg, message)
        _log(f"{symbol}: Telegram -> {info}")
        if ok:
            sent += 1

    # Pembelajaran: catat trade yang baru ditutup ke jurnal & hitung ulang adaptasi.
    if learn_on:
        newly = learning_mod.sync(trade_log, positions)
        new_sl = any(t.get("result") == "SL" for t in newly)
        adaptive = learning_mod.recompute(trade_log, cfg, adaptive, new_sl)
        if not dry_run:
            learning_mod.save_json(tl_path, trade_log)
            learning_mod.save_json(ad_path, adaptive)
        if newly:
            _log(f"Belajar: +{len(newly)} trade ditutup; winrate={adaptive.get('recent_winrate')} "
                 f"SL_beruntun={adaptive.get('consecutive_sl')} penalty={adaptive.get('focus_penalty')}")

        # Recap bulanan otomatis: awal bulan baru -> kirim recap bulan sebelumnya (sekali).
        if not dry_run and cfg.get("report", {}).get("monthly_auto", True):
            rc_path = Path(cfg["_root"]) / cfg["report"].get("state_file", "state/recap.json")
            try:
                rc = json.loads(rc_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                rc = {}
            prev_m = report_mod.prev_month_of(datetime.now(timezone(timedelta(hours=7))))
            if rc.get("last_month") != prev_m:
                if report_mod.trades_in_month(trade_log, prev_m):
                    text = report_mod.build_recap(trade_log, prev_m)
                    ok, info = telegram_notify.send(cfg, text)
                    _log(f"Recap {prev_m} -> Telegram: {info}")
                    if ok:
                        sent += 1
                rc["last_month"] = prev_m
                rc_path.parent.mkdir(parents=True, exist_ok=True)
                rc_path.write_text(json.dumps(rc, ensure_ascii=False, indent=2), encoding="utf-8")

    if tracking_on and not dry_run and state_path is not None:
        tracker_mod.save(state_path, positions)

    _log(f"Selesai. Pesan terkirim: {sent}.")
    return 0


def _persist(signals_dir: Path, symbol: str, rule_sig, ai, message: str, fund=None) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "action": rule_sig.action,
        "overall_score": rule_sig.overall_score,
        "overall_label": rule_sig.overall_label,
        "htf_score": rule_sig.htf_score,
        "ltf_score": rule_sig.ltf_score,
        "per_tf": rule_sig.per_tf,
        "setup": None if rule_sig.setup is None else {
            "direction": rule_sig.setup.direction,
            "entry": rule_sig.setup.entry,
            "sl": rule_sig.setup.sl,
            "tps": rule_sig.setup.tps,
            "rr": rule_sig.setup.rr,
        },
        "reasons": rule_sig.reasons,
        "fundamentals": fund,
        "ai": ai,
        "message": message,
    }
    (signals_dir / f"{symbol}_{stamp}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # log harian ringkas
    daily = signals_dir / f"signals_{datetime.now():%Y%m%d}.md"
    with daily.open("a", encoding="utf-8") as f:
        f.write(f"## {datetime.now():%H:%M} — {symbol} — {rule_sig.action} "
                f"({rule_sig.overall_score:+.2f})\n\n{message}\n\n---\n\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Market Signal Assistant — satu kali jalan")
    p.add_argument("--config", default=None, help="path config.yaml")
    p.add_argument("--dry-run", action="store_true", help="cetak saja, tidak kirim Telegram")
    p.add_argument("--backend", choices=["mcp", "direct"], help="override data_backend")
    p.add_argument("--no-reasoning", action="store_true", help="lewati lapisan Claude")
    args = p.parse_args(argv)

    _force_utf8_console()
    cfg = config_mod.load_config(args.config)
    if args.backend:
        cfg["data_backend"] = args.backend
    if args.no_reasoning:
        cfg["reasoning"]["enabled"] = False
    return run(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
