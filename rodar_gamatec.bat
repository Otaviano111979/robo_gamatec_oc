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
echo Verificando atualizacoes...
%PY% "%~dp0instalador\atualizador.py"

echo.
echo ==========================================
echo   INICIANDO SISTEMA GAMATEC
echo ==========================================
echo.
echo Abrindo navegador em 5 segundos...
start "" cmd /c "timeout /t 5 >nul && start http://127.0.0.1:5000/ocs"

echo.
echo Iniciando servidor...
%PY% "%~dp0iniciar_sistema.py"

echo.
echo ==========================================
echo   SISTEMA ENCERRADO
echo ==========================================
pause
