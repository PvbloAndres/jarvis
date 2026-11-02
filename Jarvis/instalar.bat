@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalando JARVIS
rem El entorno de Python vive fuera de OneDrive para no sincronizar mas de 1 GB de librerias.
set "VENV=%LOCALAPPDATA%\Jarvis\venv"
set "PY=%VENV%\Scripts\python.exe"
echo.
echo  ==============================================
echo     Instalacion de J.A.R.V.I.S.
echo  ==============================================
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo  No encuentro Python. Instalalo con este comando y vuelve a ejecutar instalar.bat:
  echo     winget install Python.Python.3.13
  echo  o descargalo de https://www.python.org/downloads/  ^(marca "Add python.exe to PATH"^)
  pause
  exit /b 1
)
if not exist "%PY%" (
  echo  Creando entorno de Python en %VENV% ...
  if not exist "%LOCALAPPDATA%\Jarvis" mkdir "%LOCALAPPDATA%\Jarvis"
  py -3 -m venv "%VENV%"
)
if not exist "%PY%" (
  echo  No pude crear el entorno de Python.
  pause
  exit /b 1
)
echo  Instalando dependencias ^(puede tardar varios minutos^)...
"%PY%" -m pip install --upgrade pip -q
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Hubo un error instalando dependencias. Revisa el mensaje de arriba.
  pause
  exit /b 1
)
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
  echo.
  echo  Tarjeta NVIDIA detectada: instalando aceleracion para entender tu voz mas rapido ^(~1 GB^)...
  "%PY%" -m pip install -r requirements-gpu.txt
)
if not exist config.yaml copy config.example.yaml config.yaml >nul
if not exist rutinas.yaml copy rutinas.example.yaml rutinas.yaml >nul

rem Comandos de TRIGGERcmd con la ruta real de esta carpeta.
powershell -NoProfile -Command "$r=(Get-Location).Path -replace '\\','\\'; $t=(Get-Content -Raw -Encoding UTF8 'triggercmd\commands.example.json') -replace 'RUTA_JARVIS',$r; [IO.File]::WriteAllText((Join-Path (Get-Location) 'triggercmd\commands.json'), $t, (New-Object Text.UTF8Encoding $false))"

rem Mantiene esta carpeta siempre descargada en el PC (OneDrive), para que arranque sin internet.
attrib +P "%~dp0*" /S /D >nul 2>nul

echo.
echo  Descargando los modelos de voz ^(la primera vez tarda unos minutos^)...
"%PY%" -m jarvis --preparar

echo.
echo  Activando el arranque automatico con Windows...
"%PY%" -m jarvis.servicio --activar

echo.
echo  Listo. Ahora:
echo    1. Abre config.yaml con el Bloc de notas y pega tu clave de IA.
echo    2. Ejecuta probar.bat para revisar cada pieza.
echo    3. Ejecuta iniciar.bat. Desde ahora Jarvis tambien se enciende solo con Windows.
echo.
pause
