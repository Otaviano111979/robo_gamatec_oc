@echo off
title Subir atualizacoes - robo_gamatec_oc
setlocal

cd /d C:\robo_gamatec_oc

echo.
echo ==========================================
echo   STATUS ATUAL DO REPOSITORIO
echo ==========================================
git status
if errorlevel 1 (
    echo.
    echo Erro ao executar git status.
    pause
    exit /b
)

echo.
set /p msg=Digite a mensagem do commit: 

if "%msg%"=="" (
    echo.
    echo Nenhuma mensagem informada. Processo cancelado.
    pause
    exit /b
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm\""') do set DATAHORA=%%i

set COMMIT_MSG=%msg% - %DATAHORA%

echo.
echo ==========================================
echo   ADICIONANDO ARQUIVOS
echo ==========================================
git add .
if errorlevel 1 (
    echo.
    echo Erro no git add.
    pause
    exit /b
)

echo.
echo ==========================================
echo   REMOVENDO ARQUIVOS SENSIVEIS DO STAGE
echo ==========================================
git restore --staged agente_email\token.pickle 2>nul
git restore --staged agente_email\estado_emails.json 2>nul

echo.
echo ==========================================
echo   CRIANDO COMMIT
echo ==========================================
git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
    echo.
    echo Nada para commitar ou houve erro no commit.
    pause
    exit /b
)

echo.
choice /m "Deseja continuar com git pull --rebase e git push"
if errorlevel 2 (
    echo.
    echo Processo interrompido apos o commit.
    pause
    exit /b
)

echo.
echo ==========================================
echo   ATUALIZANDO REPOSITORIO LOCAL
echo ==========================================
git pull --rebase
if errorlevel 1 (
    echo.
    echo Erro no git pull --rebase. Verifique conflitos.
    pause
    exit /b
)

echo.
echo ==========================================
echo   ENVIANDO PARA O GITHUB
echo ==========================================
git push
if errorlevel 1 (
    echo.
    echo Erro no git push.
    pause
    exit /b
)

echo.
echo ==========================================
echo   PROCESSO FINALIZADO COM SUCESSO
echo ==========================================
git status

echo.
pause
endlocal