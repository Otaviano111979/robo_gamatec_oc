@echo off
title Status rapido - robo_gamatec_oc
cd /d "%~dp0"

echo.
echo ==========================================
echo   STATUS DO PROJETO
echo ==========================================
git status

echo.
echo ==========================================
echo   ULTIMOS COMMITS
echo ==========================================
git log --oneline -5

echo.
echo ==========================================
echo   DIFERENCAS (RESUMO)
echo ==========================================
git diff --stat

echo.
echo ==========================================
echo   ARQUIVOS MODIFICADOS
echo ==========================================
git diff --name-only

echo.
pause