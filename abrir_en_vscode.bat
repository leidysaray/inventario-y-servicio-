@echo off
title Abriendo PiShop Cloud en Visual Studio Code...
chcp 65001 > nul
cd /d "%~dp0"
echo ========================================================
echo  Abriendo PiShop Cloud en Visual Studio Code...
echo ========================================================
code .
echo.
echo Listo. Visual Studio Code se esta abriendo.
timeout /t 3 > nul
