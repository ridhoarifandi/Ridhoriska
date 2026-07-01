# Deploy ke VPS (jalan 24/7 tanpa tergantung PC Anda)

Bot ini Python murni, jadi bisa dipindah ke VPS Linux dan berjalan terus. Panduan ini
memakai **Ubuntu 22.04/24.04** dan backend **`direct`** (data TradingView sama, tanpa bridge).

---

## 1. Sewa VPS (pilih salah satu)

Spesifikasi minimal cukup kecil: **1 vCPU, 1 GB RAM, Ubuntu 22.04**.

| Provider | Perkiraan harga | Catatan |
|---|---|---|
| Contabo | ~Rp60–90rb/bln | Murah, RAM besar |
| DigitalOcean / Vultr | ~$5–6/bln | Mudah, banyak tutorial |
| Hetzner | ~€4/bln | Murah & cepat (Eropa) |
| IdCloudHost / Biznet Gio / Niagahoster (VPS) | bervariasi | Lokal Indonesia, support Bahasa |

Saat membuat VPS pilih **Ubuntu 22.04 (atau 24.04)**. Anda akan dapat **IP address** dan
**password root** (atau SSH key). *(Pembuatan akun & pembayaran VPS Anda lakukan sendiri.)*

---

## 2. Masuk ke VPS (SSH)

Dari PowerShell di PC Anda:
```powershell
ssh root@IP_VPS_ANDA
```
Ketik `yes` saat ditanya fingerprint, lalu masukkan password VPS.

---

## 3. Pindahkan project ke VPS

### Cara A — lewat GitHub (disarankan; Anda sudah punya akun GitHub)
Di **PC Anda** (sekali saja), buat repo **PRIVATE** lalu push. `.env` tidak ikut ter-upload
(sudah di-`.gitignore`), jadi token Anda aman. Saya bisa bantu langkah push ini.

Lalu di **VPS**:
```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/USERNAME/market-signal-assistant.git
cd market-signal-assistant
```

### Cara B — upload langsung (scp dari PC)
Di **PowerShell PC Anda** (tanpa folder .venv):
```powershell
cd "D:\my project"
scp -r "market-signal-assistant" root@IP_VPS_ANDA:/root/
```
Lalu di VPS: `cd /root/market-signal-assistant`

---

## 4. Jalankan setup otomatis

Di VPS, dari dalam folder project:
```bash
bash deploy/setup_vps.sh
```
Script ini: install Python, set timezone WIB, buat venv + install dependencies,
set `data_backend: direct`, dan pasang **cron tiap 30 menit (14:00–23:00 WIB, Sen–Jum)**.

---

## 5. Isi kredensial & tes

```bash
nano .env
```
Isi `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (boleh ambil otomatis di bawah), dan
`ANTHROPIC_API_KEY` (opsional). Simpan: `Ctrl+O`, `Enter`, lalu keluar `Ctrl+X`.

Ambil chat_id otomatis (kirim "halo" ke bot dulu):
```bash
.venv/bin/python setup_telegram.py
```

Tes:
```bash
.venv/bin/python -m src.main --dry-run --backend direct   # cek analisa
.venv/bin/python -m src.main                              # kirim ke Telegram bila ada sinyal
```

---

## 6. Selesai — bot jalan 24/7

- Lihat jadwal:  `crontab -l`
- Lihat log:     `tail -f logs/run.log`
- Ubah jam/strategi: edit `config.yaml`, lalu `crontab -e` bila ingin ubah jadwal.
- Matikan sementara: `crontab -r` (hapus semua cron) atau comment baris di `crontab -e`.

> Setelah ini PC Anda boleh mati — bot tetap berjalan di VPS. Matikan dulu Task Scheduler
> di PC (`schtasks /Delete /TN MarketSignal /F`) agar tidak dobel kirim.
