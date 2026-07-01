"""Mesin sinyal rule-based — FOKUS scalping M1/M5 (untuk equity kecil).

Logika keputusan:
  - Sinyal ditentukan oleh TF fokus (M5 & M1): keduanya harus searah & cukup kuat.
  - TF besar (H1/H4) jadi FILTER PELINDUNG: hanya memblokir bila tren besar
    melawan dengan kuat (hindari scalp lawan arah dump/pump besar).
  - ADX di TF entry harus menandakan ada gerak (hindari sideways mati).

Aturan risk yang dipaksakan:
  - Order diutamakan LIMIT (buy limit di bawah harga / sell limit di atas harga).
  - Stop Loss berbasis pips (default), DIBATASI maksimal `max_loss_pips` (50 pips).
    Bila data ATR tersedia, ATR dipakai (tetap di-cap 50 pips).
  - Take Profit = kelipatan risiko (R) → TP1 minimal RR 1:3.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .indicators import TFReading


def label_from_score(s: float) -> str:
    if s >= 0.5:
        return "STRONG_BUY"
    if s >= 0.1:
        return "BUY"
    if s <= -0.5:
        return "STRONG_SELL"
    if s <= -0.1:
        return "SELL"
    return "NEUTRAL"


@dataclass
class Setup:
    direction: str          # BUY / SELL
    order_type: str         # "limit" / "market"
    entry: float
    sl: float
    tps: list[float]
    rr: list[float]
    risk_pips: float
    sl_capped: bool
    sl_basis: str           # "atr" / "pips"


@dataclass
class RuleSignal:
    symbol: str
    action: str             # BUY / SELL / WAIT
    overall_score: float
    overall_label: str
    focus_score: float      # rata-rata tertimbang M5/M1 (penentu utama)
    htf_score: float
    ltf_score: float
    guard_score: float      # skor TF pelindung (H1/H4)
    aligned: bool
    per_tf: dict[str, float] = field(default_factory=dict)
    setup: Setup | None = None
    reasons: list[str] = field(default_factory=list)


def _weighted(readings: dict[str, TFReading], tfs: list[str], weights: dict) -> float:
    num = den = 0.0
    for tf in tfs:
        r = readings.get(tf)
        if r is None or not r.ok:
            continue
        w = float(weights.get(tf, 1.0))
        num += w * r.score()
        den += w
    return num / den if den else 0.0


def _tfs_agree(readings: dict[str, TFReading], tfs: list[str], sign: int, tol: float = 0.05) -> bool:
    """True bila semua TF (yang valid) di daftar searah dengan `sign`."""
    seen = False
    for tf in tfs:
        r = readings.get(tf)
        if r is None or not r.ok:
            continue
        seen = True
        s = r.score()
        if sign > 0 and s < tol:
            return False
        if sign < 0 and s > -tol:
            return False
    return seen


def _build_setup(direction: str, ref: TFReading, cfg: dict, pip_size: float,
                 order_type: str = "limit") -> Setup | None:
    if ref is None or ref.close is None or pip_size <= 0:
        return None
    sig = cfg["signal"]
    price = ref.close

    # Jarak risiko (SL): pakai ATR bila ada, kalau tidak pakai sl_pips tetap.
    if ref.atr and ref.atr > 0:
        risk = float(sig.get("atr_sl_mult", 1.2)) * ref.atr
        basis = "atr"
    else:
        risk = float(sig.get("sl_pips", 25)) * pip_size
        basis = "pips"

    max_loss_price = float(sig["max_loss_pips"]) * pip_size
    sl_capped = False
    if risk > max_loss_price:
        risk = max_loss_price
        sl_capped = True
    if risk <= 0:
        return None

    # Entry limit: pullback dari harga sekarang.
    pullback = float(sig.get("entry_pullback_pips", 8)) * pip_size
    if order_type == "limit":
        entry = price - pullback if direction == "BUY" else price + pullback
    else:
        entry = price

    sl = entry - risk if direction == "BUY" else entry + risk
    rr_mults = [float(x) for x in sig["rr_mults"]]
    if direction == "BUY":
        tps = [entry + m * risk for m in rr_mults]
    else:
        tps = [entry - m * risk for m in rr_mults]

    return Setup(
        direction=direction, order_type=order_type, entry=entry, sl=sl,
        tps=tps, rr=[round(m, 2) for m in rr_mults],
        risk_pips=round(risk / pip_size, 1), sl_capped=sl_capped, sl_basis=basis,
    )


def evaluate(symbol: str, readings: dict[str, TFReading], cfg: dict,
             pip_size: float) -> RuleSignal:
    weights = cfg["weights"]
    groups = cfg["groups"]
    sig = cfg["signal"]

    focus_tfs = sig.get("focus_tfs", ["5m", "1m"])
    guard_tfs = sig.get("htf_guard_tfs", ["1h", "4h"])

    per_tf = {tf: round(r.score(), 3) for tf, r in readings.items() if r.ok}
    overall = _weighted(readings, list(readings.keys()), weights)
    focus = _weighted(readings, focus_tfs, weights)
    htf = _weighted(readings, groups["htf"], weights)
    ltf = _weighted(readings, groups["ltf"], weights)
    guard = _weighted(readings, guard_tfs, weights)

    direction_sign = 1 if focus > 0 else -1
    focus_aligned = _tfs_agree(readings, focus_tfs, direction_sign)
    aligned = (htf > 0 and ltf > 0) or (htf < 0 and ltf < 0)

    entry_ref = readings.get(sig.get("entry_tf_for_levels", "5m"))
    adx_ok = entry_ref is not None and entry_ref.ok and (entry_ref.adx or 0) >= float(sig.get("min_adx", 0))

    reasons: list[str] = []
    action = "WAIT"

    if abs(focus) < float(sig.get("min_focus_score", 0.40)):
        reasons.append(f"Sinyal M1/M5 (skor {focus:+.2f}) belum cukup kuat → tunggu.")
    elif sig.get("require_focus_agree", True) and not focus_aligned:
        reasons.append("M5 & M1 belum searah → tunggu konfirmasi entry.")
    elif (direction_sign > 0 and guard <= -float(sig.get("htf_guard_block_score", 0.45))) or \
         (direction_sign < 0 and guard >= float(sig.get("htf_guard_block_score", 0.45))):
        reasons.append(f"TF besar (H1/H4 skor {guard:+.2f}) melawan kuat → batal scalp lawan tren.")
    elif not adx_ok:
        reasons.append(f"ADX di {sig.get('entry_tf_for_levels')} < {sig.get('min_adx')} "
                       f"(sideways) → tunggu gerak.")
    else:
        action = "BUY" if focus > 0 else "SELL"

    setup = None
    if action in ("BUY", "SELL"):
        # Sinyal sangat kuat -> masuk SEKARANG (market); selain itu limit (pullback).
        auto_now = sig.get("auto_now", True)
        now_score = float(sig.get("now_focus_score", 0.65))
        order_mode = "market" if (auto_now and abs(focus) >= now_score) else sig.get("order_type", "limit")
        setup = _build_setup(action, entry_ref, cfg, pip_size, order_mode)
        if setup is None:
            action = "WAIT"
            reasons.append("Harga tidak tersedia → level tak bisa dihitung, batal.")
        elif setup.rr and setup.rr[0] < float(sig.get("min_rr", 3.0)):
            action = "WAIT"
            reasons.append(f"RR TP1 {setup.rr[0]} < minimal {sig.get('min_rr')} → batal.")
            setup = None
        else:
            cap = " (SL dipangkas ke 50 pips)" if setup.sl_capped else ""
            reasons.append(
                f"Fokus M1/M5 {label_from_score(focus)} (skor {focus:+.2f}); "
                f"{setup.order_type} {action} — risk {setup.risk_pips} pips{cap}, RR≥{setup.rr[0]}."
            )

    return RuleSignal(
        symbol=symbol, action=action,
        overall_score=round(overall, 3), overall_label=label_from_score(overall),
        focus_score=round(focus, 3), htf_score=round(htf, 3),
        ltf_score=round(ltf, 3), guard_score=round(guard, 3),
        aligned=aligned, per_tf=per_tf, setup=setup, reasons=reasons,
    )
