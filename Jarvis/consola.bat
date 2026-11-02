@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS - consola
"%LOCALAPPDATA%\Jarvis\venv\Scripts\python.exe" -m jarvis --consola
pause
