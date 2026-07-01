"""Lapisan reasoning: Claude mengkonfirmasi sinyal rule-based + beri narasi & bias akhir.

Bersifat opsional. Bila ANTHROPIC_API_KEY kosong atau reasoning.enabled=false,
sistem tetap jalan memakai output rule-based saja.
"""
from __future__ import annotations

import json
from typing import Any

from .indicators import TFReading
from .rules import RuleSignal

SYSTEM = (
    "Anda analis teknikal forex profesional yang SANGAT konservatif, spesialis "
    "SCALPING untuk akun equity kecil. Sinyal DIFOKUSKAN pada timeframe M5 & M1 "
    "(timing & arah entry); H4/H1/M30/M15 hanya konteks/pelindung tren. Anda menerima "
    "ringkasan indikator multi-timeframe dan hasil mesin rule-based yang sudah "
    "menerapkan: order LIMIT (buy/sell limit), Stop Loss maksimal 50 pips, dan Take "
    "Profit risk:reward minimal 1:3. "
    "Tugas Anda: KONFIRMASI sinyal hanya jika momentum M5 & M1 benar-benar jelas dan "
    "tidak melawan tren besar yang kuat; bila ragu, momentum M1/M5 melemah, atau dekat "
    "level berlawanan, pilih WAIT. Anda hanya boleh menyetujui (BUY/SELL sesuai mesin) "
    "atau menurunkan ke WAIT — jangan membalik arah. Pertimbangkan juga 'fundamentals' "
    "bila ada: jika event ekonomi berisiko tinggi (mis. NFP/CPI/FOMC) sebentar lagi atau "
    "berita sangat berlawanan dengan arah, cenderung WAIT. Jangan mengarang angka yang tidak "
    "diberikan. 'confidence' harus realistis. Balas HANYA JSON valid sesuai skema, tanpa teks lain."
)

SCHEMA_HINT = {
    "action": "BUY | SELL | WAIT",
    "confidence": "0-100 (integer)",
    "bias_htf": "ringkas arah H4/H1",
    "narrative_id": "2-4 kalimat alasan dalam Bahasa Indonesia",
    "invalidation": "kondisi yang membatalkan skenario (1 kalimat)",
    "agree_with_rules": "true/false",
}


def _readings_payload(readings: dict[str, TFReading]) -> dict[str, Any]:
    out = {}
    for tf, r in readings.items():
        if not r.ok:
            out[tf] = {"error": r.error or "no data"}
            continue
        out[tf] = {
            "score": round(r.score(), 3),
            "recommend_all": r.recommend_all,
            "rsi": r.rsi,
            "macd_minus_signal": (None if r.macd is None or r.macd_signal is None
                                  else round(r.macd - r.macd_signal, 6)),
            "adx": r.adx,
            "close": r.close,
            "ema50": r.ema50,
            "ema200": r.ema200,
            "notes": r.notes,
        }
    return out


def confirm(cfg: dict, symbol: str, readings: dict[str, TFReading],
            rule_sig: RuleSignal, fund: dict | None = None) -> dict | None:
    rconf = cfg.get("reasoning", {})
    if not rconf.get("enabled", False):
        return None
    api_key = cfg["secrets"]["anthropic_api_key"]
    if not api_key:
        return {"_error": "ANTHROPIC_API_KEY kosong — reasoning dilewati."}

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"_error": "paket anthropic belum terinstall."}

    setup = None
    if rule_sig.setup:
        setup = {
            "direction": rule_sig.setup.direction,
            "entry": rule_sig.setup.entry,
            "sl": rule_sig.setup.sl,
            "tps": rule_sig.setup.tps,
            "rr": rule_sig.setup.rr,
        }

    user = {
        "symbol": symbol,
        "rule_engine": {
            "action": rule_sig.action,
            "overall_score": rule_sig.overall_score,
            "overall_label": rule_sig.overall_label,
            "htf_score": rule_sig.htf_score,
            "ltf_score": rule_sig.ltf_score,
            "aligned": rule_sig.aligned,
            "setup": setup,
            "reasons": rule_sig.reasons,
        },
        "timeframes": _readings_payload(readings),
        "respond_with_json_schema": SCHEMA_HINT,
    }
    if fund:
        user["fundamentals"] = {
            "next_event": fund.get("next_event"),
            "blackout": fund.get("blackout"),
            "headlines": [h.get("title") for h in (fund.get("headlines") or [])],
        }

    client = Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model=rconf.get("model", "claude-sonnet-4-6"),
            max_tokens=int(rconf.get("max_tokens", 1000)),
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
        )
    except Exception as e:  # noqa: BLE001
        return {"_error": f"panggilan Claude gagal: {type(e).__name__}: {e}"}

    text = "".join(getattr(b, "text", "") for b in msg.content).strip()
    text = _strip_code_fence(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_error": "respons Claude bukan JSON valid", "raw": text[:500]}


def _strip_code_fence(t: str) -> str:
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()
