@echo off
REM Arma dist\PanelQA.exe. Ver panel.spec para el que y el por que.
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Instalando PyInstaller...
    python -m pip install "pyinstaller>=6.0" || exit /b 1
)

echo Construyendo...
python -m PyInstaller --noconfirm --clean panel.spec || exit /b 1

REM El baseline de esquemas se ESCRIBE (--generar-esquemas), asi que no puede
REM vivir dentro del .exe: se deja al lado, que es donde el panel lo busca.
if exist esquemas_servicios.json copy /y esquemas_servicios.json dist\ >nul

echo.
echo Listo: dist\PanelQA.exe
echo Se reparte la carpeta dist\ completa.
