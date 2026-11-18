@echo off
rem Drama Recap Studio launcher: starts Ollama (if needed) + local server, opens as an app window.
cd /d "%~dp0"
tasklist /FI "IMAGENAME eq ollama.exe" | find /I "ollama.exe" >nul || start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
start "" /min ".venv-recap\Scripts\python.exe" -m recap_engine.server --no-browser
timeout /t 4 /nobreak >nul
set EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
if exist "%EDGE%" (start "" "%EDGE%" --app=http://127.0.0.1:8765) else (start "" http://127.0.0.1:8765)
