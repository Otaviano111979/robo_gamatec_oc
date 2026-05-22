@echo off
echo Compilando instalador Vortex Sync...
cd /d %~dp0

pip install pyinstaller --quiet

REM Se vortex.ico nao existir, remove as flags de icone para nao falhar
if exist vortex.ico (
    pyinstaller ^
      --onefile ^
      --windowed ^
      --name "VortexSync_Instalador" ^
      --icon "vortex.ico" ^
      --add-data "vortex.ico;." ^
      instalar_vortex.py
) else (
    echo [AVISO] vortex.ico nao encontrado. Compilando sem icone personalizado.
    pyinstaller ^
      --onefile ^
      --windowed ^
      --name "VortexSync_Instalador" ^
      instalar_vortex.py
)

echo.
echo Instalador gerado em: dist\VortexSync_Instalador.exe
pause
