@echo off
rem Envia una orden de texto a Jarvis. Uso: orden.bat activa la rutina modo trabajo
"%LOCALAPPDATA%\Jarvis\venv\Scripts\python.exe" "%~dp0orden.py" %*
