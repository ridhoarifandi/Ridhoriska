# ============================================================
#  Pindahkan kredensial dari .env lokal ke GitHub Secrets.
#  Jalankan dari folder project:  .\deploy\push_secrets.ps1
#
#  Token Anda dibaca langsung dari .env -> dikirim ke GitHub Secrets
#  repo ini. Nilainya TIDAK ditampilkan di layar.
#  Syarat: sudah 'gh auth login' dan berada di dalam repo git.
# ============================================================

if (-not (Test-Path ".env")) {
    Write-Output "ERROR: file .env tidak ditemukan. Jalankan dari folder project."
    exit 1
}

$keys = @("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY")

foreach ($line in Get-Content ".env") {
    if ($line -match '^\s*([A-Za-z_]+)\s*=\s*(.+?)\s*$') {
        $k = $matches[1]
        $v = $matches[2].Trim()
        if (($keys -contains $k) -and ($v -ne "")) {
            $v | gh secret set $k
            if ($?) { Write-Output ("OK  -> secret '{0}' terpasang" -f $k) }
            else    { Write-Output ("GAGAL -> '{0}' (cek gh auth login)" -f $k) }
        }
    }
}

Write-Output ""
Write-Output "Selesai. Cek di GitHub: Settings > Secrets and variables > Actions."
Write-Output "Daftar nama secret (tanpa nilai):"
gh secret list
