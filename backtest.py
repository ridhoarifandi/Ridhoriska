"""Backtest strategi scalping M5 (aproksimasi dari sistem live M1/M5).

PENTING — keterbatasan yang harus disadari:
  - Sumber data: Yahoo Finance (yfinance). XAUUSD tidak ada di Yahoo -> dipakai
    proxy GC=F (emas berjangka COMEX, sangat berkorelasi). EURUSD pakai EURUSD=X.
  - Intraday 5m di Yahoo dibatasi ~60 hari; M1 dibatasi ~7 hari -> **M1 DIHILANGKAN**
    di backtest. Jadi backtest mengukur versi yang digerakkan M5 (+ filter H1/H4).
  - Skor indikator DIHITUNG ULANG sendiri (EMA/RSI/MACD/ADX/Stoch), BUKAN angka
    Recommend.All asli TradingView. Maka hasilnya INDIKATIF, bukan replika persis.
  - Asumsi konservatif: bila SL & TP tersentuh di bar yang sama -> dianggap SL dulu.
    Spread/komisi/slippage TIDAK dimodelkan.

Gunakan ini untuk gambaran kasar ekspektasi, bukan jaminan hasil live.

Jalankan:
    .\.venv\Scripts\python.exe backtest.py
    .\.venv\Scripts\python.exe backtest.py --days 60 --rr 3
"""
from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Yahoo symbol, pip_size, label
SYMBOLS = [
    ("XAUUSD", "GC=F", 0.1),
]

# parameter strategi (selaras config.yaml)
MIN_FOCUS = 0.40          # kekuatan minimum skor M5
MIN_ADX = 18.0
GUARD_BLOCK = 0.45        # blok bila H1/H4 melawan >= ini
ENTRY_PULLBACK_PIPS = 8
SL_PIPS = 25
MAX_LOSS_PIPS = 50
ENTRY_VALID_BARS = 6      # limit harus ke-fill dalam N bar, kalau tidak batal
MAX_HOLD_BARS = 48        # horizon (48 x 5m = 4 jam)


# --------------------------- indikator (pandas) --------------------------- #
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd_hist(close: pd.Series) -> pd.Series:
    m = ema(close, 12) - ema(close, 26)
    return m - ema(m, 9)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up = h.diff()
    dn = -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean().fillna(0)


def stoch_k(df: pd.DataFrame, n: int = 14) -> pd.Series:
    ll = df["Low"].rolling(n).min()
    hh = df["High"].rolling(n).max()
    return (100 * (df["Close"] - ll) / (hh - ll).replace(0, np.nan)).fillna(50)


def composite_score(df: pd.DataFrame) -> pd.Series:
    """Skor arah [-1..1] meniru komposit MA+oscillator TradingView."""
    c = df["Close"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    ma_sig = (
        np.sign(c - e20) + np.sign(c - e50) + np.sign(c - e200)
        + np.sign(e20 - e50) + np.sign(e50 - e200)
    ) / 5.0
    r = rsi(c)
    osc = (
        np.sign(r - 50) * (r.sub(50).abs() / 50).clip(upper=1)
        + np.sign(macd_hist(c))
        + np.sign(stoch_k(df) - 50)
    ) / 3.0
    return (0.6 * ma_sig + 0.4 * osc).clip(-1, 1)


# ------------------------------ data ------------------------------ #
def fetch_5m(yahoo: str, days: int) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(yahoo, period=f"{min(days,60)}d", interval="5m",
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.index = pd.to_datetime(df.index)
    return df


def htf_score_on(base: pd.DataFrame, rule: str) -> pd.Series:
    """Hitung skor di TF lebih tinggi, lalu petakan (asof) ke timestamp base 5m."""
    agg = base.resample(rule).agg({"Open": "first", "High": "max",
                                   "Low": "min", "Close": "last"}).dropna()
    sc = composite_score(agg)
    return sc.reindex(base.index, method="ffill")


# ------------------------------ simulasi ------------------------------ #
def simulate(base: pd.DataFrame, pip: float, rr: float,
             min_focus: float = MIN_FOCUS, min_adx: float = MIN_ADX,
             require_align: bool = False, sl_pips: float = SL_PIPS) -> list[dict]:
    c = base["Close"].values
    hi = base["High"].values
    lo = base["Low"].values
    sc5 = composite_score(base).values
    adx5 = adx(base).values
    sc1h = htf_score_on(base, "1h").values
    sc4h = htf_score_on(base, "4h").values

    pullback = ENTRY_PULLBACK_PIPS * pip
    risk = min(sl_pips, MAX_LOSS_PIPS) * pip
    n = len(base)
    trades: list[dict] = []
    i = 200  # lewati warmup indikator
    while i < n - 1:
        f, a1h, a4h, ad = sc5[i], sc1h[i], sc4h[i], adx5[i]
        guard = (a1h + a4h) / 2.0
        sig = 0
        if abs(f) >= min_focus and ad >= min_adx:
            direction = 1 if f > 0 else -1
            opposed = (direction > 0 and guard <= -GUARD_BLOCK) or \
                      (direction < 0 and guard >= GUARD_BLOCK)
            # require_align: H1/H4 harus SEARAH (bukan sekadar tidak melawan)
            align_ok = (not require_align) or (np.sign(guard) == direction and abs(guard) >= 0.15)
            if not opposed and align_ok:
                sig = direction
        if sig == 0:
            i += 1
            continue

        price = c[i]
        entry = price - pullback if sig > 0 else price + pullback
        sl = entry - risk if sig > 0 else entry + risk
        tp = entry + sig * rr * risk

        # 1) tunggu limit ke-fill
        filled = -1
        for j in range(i + 1, min(i + 1 + ENTRY_VALID_BARS, n)):
            if (sig > 0 and lo[j] <= entry) or (sig < 0 and hi[j] >= entry):
                filled = j
                break
        if filled < 0:
            i += 1
            continue

        # 2) setelah fill, mana dulu: SL atau TP (asumsi SL dulu bila sebar sama)
        outcome = None
        for k in range(filled, min(filled + MAX_HOLD_BARS, n)):
            hit_sl = lo[k] <= sl if sig > 0 else hi[k] >= sl
            hit_tp = hi[k] >= tp if sig > 0 else lo[k] <= tp
            if hit_sl:
                outcome = ("loss", -1.0)
                break
            if hit_tp:
                outcome = ("win", rr)
                break
        if outcome is None:
            # tutup di harga terakhir horizon -> R parsial
            last = c[min(filled + MAX_HOLD_BARS - 1, n - 1)]
            r_val = sig * (last - entry) / risk
            outcome = ("timeout", round(r_val, 2))

        trades.append({"i": i, "dir": "BUY" if sig > 0 else "SELL",
                       "result": outcome[0], "R": outcome[1]})
        i = filled + 1  # jangan overlap dari entry yang sama
    return trades


def report(label: str, yahoo: str, trades: list[dict], rr: float) -> dict:
    wins = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]
    timeouts = [t for t in trades if t["result"] == "timeout"]
    decided = len(wins) + len(losses)
    wr = (len(wins) / decided * 100) if decided else 0.0
    total_R = sum(t["R"] for t in trades)
    exp_R = (total_R / len(trades)) if trades else 0.0
    print(f"\n=== {label}  (data: {yahoo}) ===")
    print(f"  Total sinyal     : {len(trades)}")
    print(f"  Menang/Kalah     : {len(wins)} / {len(losses)}  "
          f"(timeout {len(timeouts)})")
    print(f"  Win rate (TP{rr:g}R vs SL): {wr:.1f}%  [dari {decided} trade selesai]")
    print(f"  Total R          : {total_R:+.1f} R")
    print(f"  Ekspektasi/trade : {exp_R:+.2f} R")
    # win rate impas utk RR ini:
    be = 1 / (1 + rr) * 100
    print(f"  Win rate impas   : {be:.1f}%  -> {'PROFIT' if wr>be else 'rugi/impas'} secara teori")
    return {"label": label, "n": len(trades), "win_rate": wr, "exp_R": exp_R}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--rr", type=float, default=3.0, help="RR target TP1 (default 3 = 1:3)")
    p.add_argument("--focus", type=float, default=MIN_FOCUS, help="ambang skor M5")
    p.add_argument("--adx", type=float, default=MIN_ADX, help="ambang ADX M5")
    p.add_argument("--align", action="store_true", help="wajib H1/H4 SEARAH (lebih ketat)")
    p.add_argument("--sl", type=float, default=SL_PIPS, help="SL pips (cap 50)")
    args = p.parse_args()

    print("Backtest scalping M5 (aproksimasi sistem M1/M5).")
    print(f"Param: focus>={args.focus}, ADX>={args.adx}, align={args.align}, "
          f"SL={min(args.sl,MAX_LOSS_PIPS):g} pips, RR=1:{args.rr:g}, hold<={MAX_HOLD_BARS} bar.")
    summary = []
    for label, yahoo, pip in SYMBOLS:
        try:
            base = fetch_5m(yahoo, args.days)
        except Exception as e:  # noqa: BLE001
            print(f"\n{label}: gagal ambil data ({type(e).__name__}: {e})")
            continue
        if len(base) < 300:
            print(f"\n{label}: data kurang ({len(base)} bar).")
            continue
        span = f"{base.index[0]:%Y-%m-%d} s/d {base.index[-1]:%Y-%m-%d} ({len(base)} bar 5m)"
        print(f"\n[{label}] {span}")
        trades = simulate(base, pip, args.rr, min_focus=args.focus, min_adx=args.adx,
                          require_align=args.align, sl_pips=args.sl)
        summary.append(report(label, yahoo, trades, args.rr))

    print("\n" + "=" * 60)
    print("CATATAN: hasil INDIKATIF (data Yahoo, M1 dihilangkan, skor rekonstruksi,")
    print("tanpa spread/komisi). Bukan jaminan performa live.")


if __name__ == "__main__":
    main()
