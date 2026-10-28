@echo off
setlocal
title Rodar Sistema GAMATEC

rem Roda a partir da pasta onde este .bat esta, seja qual for o caminho
cd /d "%~dp0"

set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
    py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    echo.
    echo ERRO: Python nao encontrado nesta maquina.
    echo Instale o Python 3 marcando "Add Python to PATH":
    echo   https://www.python.org/downloads/windows/
    echo.
    pause
    exit /b 1
)

echo.
%PY% "%~dp0iniciar_sistema.py" --preflight --abrir-navegador
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   INICIANDO SISTEMA GAMATEC
echo ==========================================
echo.
%PY% "%~dp0iniciar_sistema.py" --atualizar --abrir-navegador
set "RESULTADO=%ERRORLEVEL%"

echo.
echo ==========================================
echo   SISTEMA ENCERRADO
echo ==========================================
pause
exit /b %RESULTADO%
