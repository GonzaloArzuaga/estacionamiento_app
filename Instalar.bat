@echo off
title Instalacion - Estacionamiento Inteligente
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
    echo No se encontro Python.
    echo Instala Python 3.12 desde https://www.python.org/downloads/
    echo IMPORTANTE: marcar "Add Python to PATH" en la primera pantalla.
    pause
    exit /b
)
echo Instalando librerias (puede tardar varios minutos)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip uninstall -y opencv-python-headless opencv-python opencv-contrib-python
python -m pip install opencv-python
rem Evita que Streamlit pida un email la primera vez que se abre el panel
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
)
echo.
echo Instalacion terminada. Ahora abri "Iniciar estacionamiento.bat".
pause