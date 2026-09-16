@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 goto fail
exit /b 0
:fail
echo Installation or startup failed. Check Python and your internet connection.
pause
exit /b 1

