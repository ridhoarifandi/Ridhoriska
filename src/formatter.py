"""Format sinyal menjadi pesan Telegram (Markdown) yang rapi."""
from __future__ import annotations

from datetime import datetime

from .rules import RuleSignal

_EMOJI = {"BUY": "🟢", "SELL": "🔴", "WAIT": "⚪"}
_TF_ORDER = ["4h", "1h", "30m", "15m", "5m", "1m"]


def _fmt_price(x: float | None) -> str:
    if x is None:
        return "-"
    if abs(x) >= 100:
        return f"{x:,.2f}"
    return f"{x:.5f}".rstrip("0").rstrip(".")


def _tf_table(per_tf: dict[str, float]) -> str:
    rows = []
    for tf in _TF_ORDER:
        if tf in per_tf:
            s = per_tf[tf]
            arrow = "▲" if s > 0.1 else ("▼" if s < -0.1 else "•")
            rows.append(f"{tf.upper():>4} {arrow} {s:+.2f}")
    return "\n".join(rows)


def build_message(rule_sig: RuleSignal, ai: dict | None, fund: dict | None = None,
                  action: str | None = None, lang: str = "id") -> str:
    sym = rule_sig.symbol
    if action is None:
        action = rule_sig.action
        if ai and ai.get("action") in ("BUY", "SELL", "WAIT"):
            action = ai["action"]  # bias akhir dari Claude bila ada
    emoji = _EMOJI.get(action, "⚪")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"{emoji} *{sym} — {action}*  _(scalping M1/M5)_", f"_{ts}_", ""]
    lines.append(
        f"🎯 Fokus M1/M5: *{rule_sig.focus_score:+.2f}*  "
        f"| Pelindung H1/H4: {rule_sig.guard_score:+.2f}"
    )
    lines.append(
        f"Konteks keseluruhan: {rule_sig.overall_label} ({rule_sig.overall_score:+.2f})"
    )

    lines.append("")
    lines.append("```")
    lines.append(_tf_table(rule_sig.per_tf))
    lines.append("```")

    s = rule_sig.setup
    if action in ("BUY", "SELL") and s is not None:
        if s.order_type == "market":
            lines.append("")
            lines.append(f"⚡ *Order:* {action} NOW (harga pasar — momentum kuat)")
            lines.append(f"🎯 *Entry (sekarang):* {_fmt_price(s.entry)}")
        else:
            lines.append("")
            lines.append(f"📌 *Order:* {action} LIMIT")
            lines.append(f"🎯 *Entry (limit):* {_fmt_price(s.entry)}")
        cap = " ⛔(maks 50 pips)" if s.sl_capped else ""
        lines.append(f"🛑 *SL:* {_fmt_price(s.sl)}  ({s.risk_pips:g} pips){cap}")
        for i, (tp, rr) in enumerate(zip(s.tps, s.rr), start=1):
            lines.append(f"✅ *TP{i}:* {_fmt_price(tp)}  (RR 1:{rr:g})")
        if s.order_type == "market":
            lines.append("🏃 _Posisi langsung RUNNING begitu Anda entry sekarang._")
        else:
            lines.append("⏳ _Limit — Anda akan dapat notif *POSISI RUNNING* saat harga menyentuh entry._")

    if ai and not ai.get("_error"):
        conf = ai.get("confidence")
        if conf is not None:
            lines.append("")
            lines.append(f"🤖 *Confidence Claude:* {conf}%")
        narr = ai.get("narrative_id")
        if narr:
            lines.append(f"_{narr}_")
        inval = ai.get("invalidation")
        if inval:
            lines.append(f"⚠️ Invalidasi: {inval}")
        if ai.get("agree_with_rules") is False:
            lines.append("_(Catatan: Claude mengoreksi sinyal rule-based.)_")
    elif ai and ai.get("_error"):
        lines.append("")
        lines.append(f"_(reasoning Claude dilewati: {ai['_error']})_")

    # Bagian fundamental: blackout berita, event berikutnya, headline.
    if fund:
        if fund.get("blackout") and fund.get("event"):
            ev = fund["event"]
            lines.append("")
            lines.append(f"🚫 *NEWS BLACKOUT* — tahan dulu: *{ev.get('title')}* "
                         f"(impact {ev.get('impact')}) ~{ev.get('in_minutes')} mnt lagi.")
        nxt = fund.get("next_event")
        if nxt:
            extra = []
            if nxt.get("forecast"):
                extra.append(f"f/c {nxt['forecast']}")
            if nxt.get("previous"):
                extra.append(f"prev {nxt['previous']}")
            tail = (" (" + ", ".join(extra) + ")") if extra else ""
            lines.append("")
            lines.append(f"📅 Event {nxt.get('country','')} berikutnya: *{nxt.get('title')}* "
                         f"~{nxt.get('in_minutes')} mnt{tail}")
        heads = fund.get("headlines") or []
        if heads:
            lines.append("")
            lines.append("📰 *Berita XAUUSD:*")
            for h in heads:
                age = f" _({h['age']})_" if h.get("age") else ""
                lines.append(f"• {h['title']}{age}")

    if action == "WAIT" and (rule_sig.reasons or (fund and fund.get("blackout"))):
        lines.append("")
        if fund and fund.get("blackout"):
            lines.append("_Status: WAIT karena ada berita berisiko tinggi (hindari entry menjelang rilis)._")
        elif rule_sig.reasons:
            lines.append("_" + rule_sig.reasons[0] + "_")

    lines.append("")
    lines.append("_Sinyal otomatis — eksekusi & manajemen risiko tetap keputusan Anda._")
    return "\n".join(lines)


def tracking_message(nf: dict) -> str:
    """Pesan notif untuk event posisi: fill / TP / SL / cancelled."""
    p = nf["pos"]
    sym = p["symbol"]
    d = p["direction"]
    arrow = "🟢" if d == "BUY" else "🔴"
    price = _fmt_price(nf.get("price"))
    t = nf["type"]

    if t == "tp":
        i = nf["tp_index"] + 1
        last = (nf["tp_index"] == len(p["tps"]) - 1)
        head = f"🎯 *TAKE PROFIT — TP{i} KENA!* {arrow}"
        body = [
            f"{sym} {d} menyentuh *TP{i}* @ {_fmt_price(nf['tp'])} (RR 1:{nf['rr']:g}).",
            f"Harga sekarang: {price}.",
        ]
        if last:
            body.append("Ini TP terakhir — posisi dianggap selesai. 🎉")
        else:
            body.append("Saatnya amankan sebagian profit / geser SL ke break-even. 💰")
        return head + "\n" + "\n".join(body)

    if t == "sl":
        return (f"🛑 *STOP LOSS KENA* {arrow}\n{sym} {d} menyentuh SL @ {_fmt_price(p['sl'])}. "
                f"Harga: {price}. Posisi ditutup sesuai rencana risiko.")

    if t == "filled":
        tps = p.get("tps") or []
        tp_line = " | ".join(f"TP{i+1} {_fmt_price(v)}" for i, v in enumerate(tps))
        return (f"🏃 *POSISI RUNNING* {arrow}\n"
                f"{sym} {d} — harga menyentuh entry {_fmt_price(p['entry'])}. "
                f"Order Anda mestinya sudah ke-fill; *posisi sekarang berjalan*.\n"
                f"🛑 SL {_fmt_price(p['sl'])} | {tp_line}\n"
                f"Pantau — notif menyusul saat TP/SL kena.")

    if t == "cancelled":
        return (f"⚪ *ORDER BATAL* — {sym} {d} limit @ {_fmt_price(p['entry'])} tidak ke-fill "
                f"(harga menembus SL dulu). Setup dibatalkan.")
    return f"{sym} {d}: update {t}."
