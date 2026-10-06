@echo off
rem Launcher: updates the local copy from the server (if newer) and starts the program.
rem User data (settings, overrides) lives in %APPDATA%\InsalubrityHistory and is never touched here.
setlocal EnableExtensions

set "BASE=%~dp0"
set "BASE=%BASE:~0,-1%"
set "APPDIR=%BASE%\app"

set "SERVER="
if exist "%BASE%\server.txt" set /p SERVER=<"%BASE%\server.txt"
if not defined SERVER goto run

set "SRC=%SERVER%\current"
if not exist "%SRC%\version.txt" goto run

rem Do not update while the program is running (its files are locked).
tasklist /FI "IMAGENAME eq InsalubrityHistory.exe" 2>nul | find /I "InsalubrityHistory.exe" >nul
if not errorlevel 1 goto run

rem Same version as on the server - nothing to do.
fc /b "%SRC%\version.txt" "%APPDIR%\version.txt" >nul 2>&1
if not errorlevel 1 goto run

rem Copy to a staging folder first; swap only after a complete copy.
if exist "%BASE%\app.new" rd /s /q "%BASE%\app.new"
robocopy "%SRC%" "%BASE%\app.new" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto run

if exist "%BASE%\app.old" rd /s /q "%BASE%\app.old"
if exist "%APPDIR%" ren "%APPDIR%" app.old
ren "%BASE%\app.new" app
if not exist "%APPDIR%\version.txt" if exist "%BASE%\app.old" ren "%BASE%\app.old" app
if exist "%BASE%\app.old" rd /s /q "%BASE%\app.old"

:run
if not exist "%APPDIR%\InsalubrityHistory.exe" (
  echo Program is not installed and the server is not reachable.
  echo Server: %SERVER%
  pause
  exit /b 1
)
start "" "%APPDIR%\InsalubrityHistory.exe"
exit /b 0
