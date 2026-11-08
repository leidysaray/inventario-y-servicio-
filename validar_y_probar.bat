@echo off
title PiShop Cloud - Pruebas y Validacion Oficial
chcp 65001 > nul
echo ========================================================
echo  1. Ejecutando Validador Oficial de Entrega...
echo ========================================================
.venv\Scripts\python.exe herramientas\validar_entrega.py inventario-service

echo.
echo ========================================================
echo  2. Ejecutando Pruebas Unitarias Pytest...
echo ========================================================
.venv\Scripts\pytest.exe services\inventario-service\tests -v

echo.
echo ========================================================
echo  Proceso finalizado.
echo ========================================================
pause
