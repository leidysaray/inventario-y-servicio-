@echo off
title PiShop Cloud - Microservicio de Inventario
chcp 65001 > nul
echo ========================================================
echo  Iniciando Aplicacion de Inventario (Puerto 8002)...
echo ========================================================
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" ejecutar_inventario.py
) else (
    python ejecutar_inventario.py
)
pause
