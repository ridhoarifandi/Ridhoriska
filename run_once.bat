@echo off
REM ===== Market Signal Assistant - dipanggil oleh Task Scheduler =====
cd /d "%~dp0"
if not exist logs mkdir logs

echo. >> "logs\run.log"
echo [%date% %time%] === run start === >> "logs\run.log"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m src.main %* >> "logs\run.log" 2>&1
) else (
    python -m src.main %* >> "logs\run.log" 2>&1
)
