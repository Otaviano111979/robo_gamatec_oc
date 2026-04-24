@echo off
title Rodar Sistema GAMATEC

cd /d C:\robo_gamatec_oc\web

echo.
echo ==========================================
echo   INICIANDO SISTEMA GAMATEC
echo ==========================================

echo.
echo Abrindo navegador em 3 segundos...
start cmd /c "timeout /t 3 >nul && start http://127.0.0.1:5000"

echo.
echo Iniciando servidor...

python app_web.py
if errorlevel 1 (
    echo.
    echo Tentando iniciar com 'py'...
    py app_web.py
)

echo.
echo ==========================================
echo   SISTEMA ENCERRADO
echo ==========================================
pause