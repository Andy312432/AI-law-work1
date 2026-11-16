@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. See README.md for setup.
    exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean main.spec
if errorlevel 1 exit /b 1
echo Build ready: dist\LexiArbiter\LexiArbiter.exe
