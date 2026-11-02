@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS - arranque automatico
set "PY=%LOCALAPPDATA%\Jarvis\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Primero ejecuta instalar.bat
  pause
  exit /b 1
)
echo.
"%PY%" -m jarvis.servicio --estado
echo.
echo   A = Activar: Jarvis se enciende solo cada vez que inicias sesion en Windows
echo   D = Desactivar
echo   S = Salir sin cambios
echo.
choice /c ADS /n /m "Elige A, D o S: "
if errorlevel 3 exit /b
if errorlevel 2 (
  "%PY%" -m jarvis.servicio --desactivar
) else (
  "%PY%" -m jarvis.servicio --activar
)
echo.
pause
