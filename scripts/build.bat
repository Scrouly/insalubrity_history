@echo off
rem Build InsalubrityHistory (Python 3.8 + PyInstaller). Run on the build machine.
setlocal EnableExtensions
cd /d "%~dp0.."

set "VENV="
if exist "venv\Scripts\python.exe" set "VENV=venv"
if not defined VENV if exist ".venv\Scripts\python.exe" set "VENV=.venv"
if not defined VENV (
  echo [ERROR] No venv in the project root. Create it first:
  echo     py -3.8 -m venv venv
  echo     venv\Scripts\activate ^&^& pip install -r requirements-win7.txt
  exit /b 1
)
call "%VENV%\Scripts\activate.bat"

python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] tkinter is missing in this Python - the launcher needs it.
  echo Reinstall Python 3.8 and keep the option "tcl/tk and IDLE" enabled.
  exit /b 1
)

echo === Running tests ===
python -m pytest -q
if errorlevel 1 (
  echo [ERROR] Tests failed - build stopped.
  exit /b 1
)

for /f %%v in ('python -c "import sys; sys.path.insert(0, 'src'); from version import __version__; print(__version__)"') do set "VER=%%v"
echo === Building version %VER% ===
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\InsalubrityHistory.spec
if errorlevel 1 (
  echo [ERROR] PyInstaller failed.
  exit /b 1
)

>"dist\InsalubrityHistory\version.txt" echo %VER%

echo === Building launcher ===
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\Launcher.spec
if errorlevel 1 (
  echo [ERROR] Launcher build failed.
  exit /b 1
)

echo.
echo Build ready: dist\InsalubrityHistory  (version %VER%)
echo Launcher:    dist\InsalubrityHistoryLauncher.exe
echo Next: publish.bat
exit /b 0
