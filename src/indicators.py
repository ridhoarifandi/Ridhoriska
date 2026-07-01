"""Normalisasi snapshot indikator mentah TradingView menjadi struktur rapi."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _f(d: dict, *keys: str) -> float | None:
    """Ambil nilai float pertama yang ada dari beberapa kemungkinan key (case-insensitive)."""
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


@dataclass
class TFReading:
    """Pembacaan indikator untuk satu timeframe."""
    timeframe: str
    error: str | None = None

    recommend_all: float | None = None   # komposit TradingView [-1..1]
    recommend_ma: float | None = None
    recommend_other: float | None = None
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    stoch_k: float | None = None
    adx: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    close: float | None = None
    atr: float | None = None

    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and self.recommend_all is not None

    def score(self) -> float:
        """Skor arah TF ini di rentang [-1..1] (positif=bullish)."""
        base = self.recommend_all if self.recommend_all is not None else 0.0
        # blend ringan dengan Recommend.MA agar tren MA ikut terwakili
        if self.recommend_ma is not None:
            base = 0.7 * base + 0.3 * self.recommend_ma
        return max(-1.0, min(1.0, base))


def parse_reading(timeframe: str, raw: dict[str, Any]) -> TFReading:
    if not isinstance(raw, dict) or raw.get("_error"):
        return TFReading(timeframe=timeframe, error=(raw or {}).get("_error", "data kosong"))

    r = TFReading(
        timeframe=timeframe,
        recommend_all=_f(raw, "Recommend.All"),
        recommend_ma=_f(raw, "Recommend.MA"),
        recommend_other=_f(raw, "Recommend.Other"),
        rsi=_f(raw, "RSI", "RSI7", "RSI14"),
        macd=_f(raw, "MACD.macd"),
        macd_signal=_f(raw, "MACD.signal"),
        stoch_k=_f(raw, "Stoch.K"),
        adx=_f(raw, "ADX"),
        ema20=_f(raw, "EMA20"),
        ema50=_f(raw, "EMA50"),
        ema200=_f(raw, "EMA200"),
        close=_f(raw, "close", "Close", "lp"),
        atr=_f(raw, "ATR", "ATRP"),
    )

    # catatan konfluensi (untuk narasi)
    if r.rsi is not None:
        if r.rsi >= 70:
            r.notes.append("RSI overbought")
        elif r.rsi <= 30:
            r.notes.append("RSI oversold")
    if r.macd is not None and r.macd_signal is not None:
        r.notes.append("MACD bullish" if r.macd > r.macd_signal else "MACD bearish")
    if r.close is not None and r.ema50 is not None:
        r.notes.append("harga > EMA50" if r.close > r.ema50 else "harga < EMA50")
    if r.close is not None and r.ema200 is not None:
        r.notes.append("di atas EMA200" if r.close > r.ema200 else "di bawah EMA200")
    if r.adx is not None:
        r.notes.append(f"ADX {r.adx:.0f} ({'tren kuat' if r.adx >= 25 else 'lemah/sideways'})")
    return r
