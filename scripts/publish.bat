@echo off
rem Publish the built version to the server. Clients update themselves on next start.
rem Usage: publish.bat [\\server\share\InsalubrityHistory]
rem        (or put that path on one line into publish_target.txt in the project root)
setlocal EnableExtensions
cd /d "%~dp0.."

set "TARGET=%~1"
if not defined TARGET if exist "publish_target.txt" set /p TARGET=<"publish_target.txt"
if not defined TARGET (
  echo [ERROR] Server folder not set.
  echo Usage: publish.bat \\server\share\InsalubrityHistory
  echo or write the path into publish_target.txt
  exit /b 1
)

if not exist "dist\InsalubrityHistory\version.txt" (
  echo [ERROR] Nothing to publish - run build.bat first.
  exit /b 1
)
if not exist "dist\InsalubrityHistoryLauncher.exe" (
  echo [ERROR] Launcher not built - run build.bat first.
  exit /b 1
)
set /p NEWVER=<"dist\InsalubrityHistory\version.txt"

set "OLDVER="
if exist "%TARGET%\current\version.txt" set /p OLDVER=<"%TARGET%\current\version.txt"
if "%NEWVER%"=="%OLDVER%" (
  echo [ERROR] Version %NEWVER% is already on the server.
  echo Clients update only when the version changes: edit version.py, run build.bat, then publish.bat.
  exit /b 1
)

if not exist "%TARGET%" mkdir "%TARGET%"
if not exist "%TARGET%" (
  echo [ERROR] Cannot create or reach %TARGET%
  exit /b 1
)

echo Publishing %NEWVER% (server now has: %OLDVER%) to %TARGET% ...

rem 1. Copy to a staging folder so clients never see a half-copied build.
if exist "%TARGET%\current.new" rd /s /q "%TARGET%\current.new"
robocopy "dist\InsalubrityHistory" "%TARGET%\current.new" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [ERROR] Copy to server failed - nothing was changed.
  exit /b 1
)

rem 2. Swap: current -> current.old (kept for quick rollback), staging -> current.
if exist "%TARGET%\current.old" rd /s /q "%TARGET%\current.old"
if exist "%TARGET%\current" ren "%TARGET%\current" current.old
ren "%TARGET%\current.new" current
if not exist "%TARGET%\current\version.txt" (
  echo [ERROR] Swap failed. Restoring previous version...
  if exist "%TARGET%\current.old" ren "%TARGET%\current.old" current
  exit /b 1
)

rem 3. Installer + launcher for new PCs.
robocopy "deploy" "%TARGET%\install" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
copy /Y "dist\InsalubrityHistoryLauncher.exe" "%TARGET%\install\InsalubrityHistoryLauncher.exe" >nul
if errorlevel 1 echo [WARNING] Could not copy the launcher to %TARGET%\install

echo.
echo Done. Server has version %NEWVER%.
echo Rollback: delete "current", rename "current.old" to "current" (then bump version differently if clients already updated).
exit /b 0
