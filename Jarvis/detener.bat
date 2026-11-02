@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS - detener
"%LOCALAPPDATA%\Jarvis\venv\Scripts\python.exe" -m jarvis.servicio --detener
timeout /t 3 >nul
