@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS - diagnostico
"%LOCALAPPDATA%\Jarvis\venv\Scripts\python.exe" -m jarvis --probar
pause
