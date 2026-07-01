# Market Signal Assistant

Asisten analisa market **multi-timeframe** (H4, H1, M30, M15, M5, M1) yang berjalan
terjadwal, lalu mengirim **sinyal BUY/SELL + TP/SL** ke Telegram Anda. **Eksekusi tetap
manual oleh Anda.**

- **Sumber data:** local MCP bridge TradingView, atau fallback langsung lewat library
  `tradingview_scraper` (sudah terbukti jalan). Pilihan bridge:
  `bidouilles/mcp-tradingview-server` atau `atilaahmettaner/tradingview-mcp`.
- **Otak analisa:** gabungan **rule-based** + **reasoning Claude**.
- **FOKUS scalping M1/M5** (untuk equity kecil): arah & timing sinyal ditentukan M5 & M1;
  H4/H1 hanya **filter pelindung** (memblokir scalp yang melawan tren besar yang kuat).
- **Risk rule (dipaksakan):** order diutamakan **LIMIT**, Stop Loss **maksimal 50 pips**,
  Take Profit **risk:reward minimal 1:3** (TP1 1:3, TP2 1:5, TP3 1:8).

---

## ✅ Status saat ini (sudah disiapkan & terverifikasi)

- Dependency terpasang di `.venv`. Pipeline data→sinyal teruji dengan **data live**.
- **MCP bridge** `bidouilles/mcp-tradingview-server` sudah **di-clone & dipasang** di
  `D:\my project\mcp-tradingview-server` dan terhubung (`data_backend: mcp`).
- **Task Scheduler** `MarketSignal` sudah terdaftar: **tiap 30 menit, 14:00–23:00 WIB**
  (sesi London–NY), jalan senyap via `run_silent.vbs`, log ke `logs\run.log`.
- **Backtest** tersedia (`backtest.py`). Hemat biaya: Claude hanya dipanggil saat ada
  kandidat sinyal; Telegram hanya kirim saat BUY/SELL (lihat `telegram.send_on_wait`).
- **BUY/SELL NOW** (market) saat momentum M1/M5 sangat kuat; selain itu limit. **Pelacak
  posisi** (`src/tracker.py`) kirim notif Telegram saat FILL / TP / SL (state di
  `state/positions.json`, di-commit balik oleh workflow).
- **Recap bulanan** (`src/report.py`): otomatis kirim recap bulan lalu ke Telegram di awal
  bulan baru (win rate, total R, rincian, daftar tiap trade). Manual: `python -m src.report
  [YYYY-MM] [--send] [--save]`.
- **Pembelajaran adaptif** (`src/learning.py`): jurnal semua trade (`state/trade_log.json`);
  setelah SL beruntun / win rate turun → **perketat filter** (`focus_penalty`) + **cooldown**
  (jeda sinyal baru); menang → streak putus, cooldown lepas. Deterministik, bukan black box.
- **Dukungan fundamental** (`src/fundamentals.py`): kalender ekonomi (feed gratis
  ForexFactory) + berita (tradingview_scraper). **News blackout**: sinyal ditahan jadi
  WAIT saat event USD high-impact (NFP/CPI/FOMC) imminent, dan headline emas dilampirkan
  di pesan. (Catatan: `investpy`/investing.com TIDAK dipakai — library itu sudah mati
  diblokir Investing.com; fungsinya digantikan sumber di atas.)

**Yang masih perlu Anda isi:** `.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
ANTHROPIC_API_KEY). Sebelum itu, scheduler tetap jalan tapi hanya menulis log (tidak kirim).

## 📊 Hasil backtest (indikatif, bukan jaminan)

Diuji ~50–60 hari data 5m (XAUUSD via proxy GC=F, EURUSD via EURUSD=X), M1 dihilangkan
karena batas data, skor indikator direkonstruksi:

| Instrumen | Win rate (TP 1:3 vs SL) | Ekspektasi/trade |
|---|---|---|
| XAUUSD | ~28% | +0.11–0.14 R (tipis di atas impas) |
| EURUSD | rendah, mayoritas timeout | belum layak dgn setelan ini |

Karena RR 1:3, **impas hanya butuh win rate 25%**. Tetap: ini indikatif, tanpa
spread/komisi. Jalankan `.\.venv\Scripts\python.exe backtest.py --help` untuk uji parameter.

## ⚠️ Soal "akurasi 95%"

Tidak ada sistem trading jujur yang bisa **menjamin** win rate di atas 95%. Yang dilakukan
sistem ini adalah **memperketat filter** agar sinyal hanya keluar saat probabilitas tinggi:

- skor fokus **M5 & M1** minimal **0.40** dan keduanya wajib searah,
- ADX di TF entry (M5) minimal **18** (hindari sideways),
- **diblokir** bila H1/H4 melawan kuat (skor ≥ 0.45),
- dikonfirmasi Claude, dan **diturunkan ke WAIT** bila confidence < ambang.

Efeknya: **sinyal jarang, tapi seleksinya ketat.** Win rate sebenarnya hanya bisa diukur
lewat **backtest** pada data historis — bukan dijanjikan di muka. Semua angka risk/RR di atas
boleh Anda atur di `config.yaml`. **Ini alat bantu, bukan jaminan profit.**

---

## 1. Instalasi

```powershell
cd "D:\my project\market-signal-assistant"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Setup Telegram

1. Buka Telegram, chat **@BotFather** → `/newbot` → ikuti langkahnya → dapat **token**.
2. Chat bot baru Anda (kirim "halo") supaya bot bisa membalas.
3. Ambil **chat_id**: buka di browser
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → cari `"chat":{"id":...}`.
4. Salin `.env.example` → `.env`, isi `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
   dan `ANTHROPIC_API_KEY` (dari https://console.anthropic.com/).

## 3. Setup sumber data

### Opsi A — Local MCP bridge (default, `data_backend: mcp`)

```powershell
cd "D:\my project"
git clone https://github.com/bidouilles/mcp-tradingview-server.git
cd mcp-tradingview-server
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e .
```

Alternatif bridge: `atilaahmettaner/tradingview-mcp`
(`git clone https://github.com/atilaahmettaner/tradingview-mcp.git`) — sesuaikan
`bridge.command/args/cwd` ke cara start repo tersebut bila Anda memilih ini.

Lalu samakan `bridge.cwd` & `bridge.command` di `config.yaml` dengan lokasi bridge.
Tanpa `uv`, pakai python venv bridge:

```yaml
bridge:
  command: "D:/my project/mcp-tradingview-server/.venv/Scripts/python.exe"
  args: ["-m", "mcp_tradingview"]
  cwd: "D:/my project/mcp-tradingview-server"
```

### Opsi B — Tanpa bridge (`data_backend: direct`)

Set `data_backend: direct` di `config.yaml`. Data diambil langsung lewat
`tradingview_scraper` (sudah ikut terinstall di requirements). Paling simpel untuk mulai.

## 4. Uji coba

```powershell
# cetak sinyal ke layar, tidak kirim Telegram, tanpa Claude:
python -m src.main --dry-run --no-reasoning --backend direct

# uji penuh (kirim ke Telegram):
python -m src.main
```

## 5. Jadwalkan (Windows Task Scheduler)

Jalankan otomatis tiap 15 menit di jam sesi London–New York (≈14:00–23:00 WIB).
Contoh membuat task tiap 15 menit:

```powershell
schtasks /Create /TN "MarketSignal" /SC MINUTE /MO 15 ^
  /TR "\"D:\my project\market-signal-assistant\run_once.bat\"" /ST 14:00 /F
```

- Ganti interval/jam sesuai selera (mis. hanya saat candle M15 close).
- Hapus task: `schtasks /Delete /TN "MarketSignal" /F`.
- Untuk MCP backend, pastikan tidak butuh app desktop (bidouilles headless — aman).

---

## Konfigurasi penting (`config.yaml`)

| Kunci | Arti |
|---|---|
| `data_backend` | `mcp` (bridge) atau `direct` |
| `symbols[].pip_size` | nilai 1 pip (XAUUSD `0.1`, EURUSD `0.0001`) |
| `signal.focus_tfs` | TF penentu sinyal (default `["5m","1m"]`) |
| `signal.min_focus_score` / `require_focus_agree` | ketatnya sinyal M1/M5 |
| `signal.htf_guard_block_score` | ambang H1/H4 untuk memblokir scalp lawan tren |
| `signal.sl_pips` / `max_loss_pips` | jarak SL & batas keras (default 25 / 50) |
| `signal.rr_mults` | kelipatan risiko utk TP (default 3/5/8 → RR 1:3 dst) |
| `signal.order_type` | `limit` (default) atau `market` |
| `reasoning.model` | `claude-sonnet-4-6` (murah) / `claude-opus-4-8` (tajam) |
| `reasoning.min_confidence_to_signal` | di bawah ini → WAIT |

## Struktur

```
src/
  tv_client.py    ambil data (MCP bridge / direct)
  indicators.py   normalisasi indikator TradingView
  rules.py        konfluensi multi-TF + level limit/SL/TP (50pips, RR>=1:3)
  reasoning.py    konfirmasi & narasi Claude
  formatter.py    susun pesan Telegram
  telegram_notify.py
  main.py         orkestrator satu kali jalan (dipanggil scheduler)
signals/          log JSON + ringkasan harian .md
```

## Disclaimer

Trading berisiko tinggi. Sinyal ini alat bantu analisa, **bukan nasihat keuangan** dan
**bukan jaminan profit**. Semua keputusan & risiko ada pada Anda.
