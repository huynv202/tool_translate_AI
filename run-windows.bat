@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Chua tim thay .venv. Hay chay setup-windows.ps1 truoc.
  pause
  exit /b 1
)

if not exist "work" mkdir "work"
if not exist "music" mkdir "music"
if not exist "output" mkdir "output"

echo Viet Transform Studio dang khoi dong...
echo Mo trinh duyet tai http://127.0.0.1:8000
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000'"
".venv\Scripts\python.exe" -m viet_transform.web

if errorlevel 1 (
  echo.
  echo Server da dung do co loi. Xem thong bao ben tren.
  pause
)
