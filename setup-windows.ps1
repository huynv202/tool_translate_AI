param(
    [switch]$WithXTTS
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Khong tim thay Python launcher 'py'. Hay cai Python 3.11 truoc."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "Khong tim thay FFmpeg trong PATH. Chay: winget install --id Gyan.FFmpeg -e"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip setuptools wheel

if ($WithXTTS) {
    & $Python -m pip install -e ".[dev,xtts]"
} else {
    & $Python -m pip install -e ".[dev]"
}

New-Item -ItemType Directory -Force music, output, work | Out-Null

Write-Host ""
Write-Host "Cai dat hoan tat." -ForegroundColor Green
Write-Host "Chay run-windows.bat va mo http://127.0.0.1:8000"

