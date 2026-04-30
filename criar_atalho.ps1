# ==========================================
#   CRIAR ATALHO - SISTEMA GAMATEC
# ==========================================

$BatPath  = "C:\robo_gamatec_oc\rodar_gamatec.bat"
$IcoPath  = "C:\robo_gamatec_oc\gamatec.ico"

# Detecta o caminho real da area de trabalho (funciona com OneDrive/PT-BR)
$Desktop  = [Environment]::GetFolderPath("Desktop")
$Shortcut = "$Desktop\GAMATEC.lnk"

Write-Host ""
Write-Host "  Desktop detectado: $Desktop" -ForegroundColor Cyan

$WshShell = New-Object -ComObject WScript.Shell
$Lnk = $WshShell.CreateShortcut($Shortcut)

$Lnk.TargetPath       = $BatPath
$Lnk.WorkingDirectory = "C:\robo_gamatec_oc"
$Lnk.WindowStyle      = 7
$Lnk.Description      = "Iniciar Sistema GAMATEC"
$Lnk.IconLocation     = "$IcoPath, 0"

$Lnk.Save()

Write-Host ""
Write-Host "=========================================="  -ForegroundColor Cyan
Write-Host "   ATALHO GAMATEC CRIADO COM SUCESSO"       -ForegroundColor Green
Write-Host "=========================================="  -ForegroundColor Cyan
Write-Host ""
Write-Host "  Local : $Shortcut"   -ForegroundColor White
Write-Host "  Icone : $IcoPath"    -ForegroundColor White
Write-Host "  Alvo  : $BatPath"    -ForegroundColor White
Write-Host ""

if (-Not (Test-Path $BatPath)) {
    Write-Warning "ATENCAO: o arquivo .bat nao foi encontrado em $BatPath"
    Write-Host "  -> Coloque o rodar_gamatec.bat em C:\robo_gamatec_oc\" -ForegroundColor Yellow
}
if (-Not (Test-Path $IcoPath)) {
    Write-Warning "ATENCAO: o arquivo .ico nao foi encontrado em $IcoPath"
    Write-Host "  -> Coloque o gamatec.ico em C:\robo_gamatec_oc\" -ForegroundColor Yellow
}

pause
