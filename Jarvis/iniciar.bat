@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS
set "PY=%LOCALAPPDATA%\Jarvis\venv\Scripts\python.exe"
set "PYW=%LOCALAPPDATA%\Jarvis\venv\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo Primero ejecuta instalar.bat
  pause
  exit /b 1
)
rem "iniciar.bat ventana" = modo antiguo, con esta ventana abierta mostrando todo (para revisar errores).
if /i "%~1"=="ventana" (
  "%PY%" -m jarvis
  pause
  exit /b
)
rem Normal: Jarvis corre en segundo plano, vigilado (se reinicia solo si falla). Icono junto al reloj.
start "" "%PYW%" -m jarvis.servicio --abrir-panel
echo Jarvis encendido en segundo plano. Busca su icono junto al reloj de Windows.
timeout /t 3 >nul
