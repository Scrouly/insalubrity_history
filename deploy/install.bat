@echo off
rem Run ONCE on each HR computer, from the server: \\server\share\InsalubrityHistory\install\install.bat
rem Installs the launcher into %LOCALAPPDATA%\InsalubrityHistory, creates a desktop shortcut, first start downloads the program.
setlocal EnableExtensions

set "SELF=%~dp0"
if /I not "%SELF:~-9%"=="\install\" (
  echo [ERROR] Run this file from the "install" folder on the server.
  pause
  exit /b 1
)
set "SERVER=%SELF:~0,-9%"
if not exist "%SERVER%\current\version.txt" (
  echo [ERROR] No published build at %SERVER%\current
  pause
  exit /b 1
)

set "BASE=%LOCALAPPDATA%\InsalubrityHistory"
if not exist "%BASE%" mkdir "%BASE%"
copy /Y "%SELF%InsalubrityHistory.cmd" "%BASE%\InsalubrityHistory.cmd" >nul
>"%BASE%\server.txt" echo %SERVER%

set "VBS=%TEMP%\mk_insalubrity_lnk.vbs"
>"%VBS%"  echo Set s = CreateObject("WScript.Shell")
>>"%VBS%" echo Set l = s.CreateShortcut(s.SpecialFolders("Desktop") ^& "\Insalubrity History.lnk")
>>"%VBS%" echo l.TargetPath = "%BASE%\InsalubrityHistory.cmd"
>>"%VBS%" echo l.WorkingDirectory = "%BASE%"
>>"%VBS%" echo l.WindowStyle = 7
>>"%VBS%" echo l.IconLocation = "%BASE%\app\InsalubrityHistory.exe,0"
>>"%VBS%" echo l.Save
cscript //nologo "%VBS%"
del "%VBS%" >nul 2>&1

echo.
echo Installed. Shortcut "Insalubrity History" is on the desktop.
echo Starting the program (first start copies it from the server)...
start "" "%BASE%\InsalubrityHistory.cmd"
exit /b 0
