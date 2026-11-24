@echo off
rem Starts Forkcast on this computer: the backend on port 8343 and the website on port 6001.
setlocal EnableExtensions
cd /d "%~dp0"

set "BACKEND_PORT=8343"
set "FRONTEND_PORT=6001"
rem Without UTF-8 mode Python can crash printing the rupee sign to a Windows console.
set "PYTHONUTF8=1"
set "NEXT_PUBLIC_API_URL=http://localhost:%BACKEND_PORT%"
set "VENV_PY=%CD%\backend\.venv\Scripts\python.exe"

rem Each candidate is run, not just looked up: "python" can be a Microsoft Store stub that does nothing.
set "PY="
set "PY_CHECK=import sys; assert sys.version_info >= (3, 11); print(sys.executable)"
if exist "%VENV_PY%" "%VENV_PY%" -c "%PY_CHECK%" >nul 2>&1 && set "PY=%VENV_PY%"
if not defined PY for /f "delims=" %%i in ('python -c "%PY_CHECK%" 2^>nul') do set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('py -3 -c "%PY_CHECK%" 2^>nul') do set "PY=%%i"
if not defined PY goto :no_python
echo Python: %PY%

"%PY%" -c "import fastapi, uvicorn, pywebpush" >nul 2>&1 && goto :backend_packages_ok
echo Installing the backend's Python packages into backend\.venv (one-time step)...
if not exist "%VENV_PY%" "%PY%" -m venv backend\.venv
"%VENV_PY%" -m pip install -r backend\requirements.txt || goto :backend_install_failed
set "PY=%VENV_PY%"
:backend_packages_ok

where node >nul 2>&1 || goto :no_node
if exist "web\node_modules\next\dist\bin\next" goto :website_packages_ok
echo Installing the website's packages (one-time step, takes a few minutes)...
pushd web
call npx --yes pnpm@12 install
popd
if not exist "web\node_modules\next\dist\bin\next" goto :website_install_failed
:website_packages_ok

rem A port that is already listening means that server is already up: reuse it, don't start a second copy.
rem "cmd /k" keeps each server window open if the server crashes, so its error stays readable.
netstat -ano | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >nul
if %errorlevel%==0 (
  echo The backend is already running on port %BACKEND_PORT%. Using it.
  goto :start_website
)
start "Forkcast backend" /D "%CD%\backend" cmd /k ""%PY%" -m uvicorn app:app --port %BACKEND_PORT%"
echo Started the backend in the "Forkcast backend" window.

:start_website
netstat -ano | findstr /R /C:":%FRONTEND_PORT% .*LISTENING" >nul
if %errorlevel%==0 (
  echo The website is already running on port %FRONTEND_PORT%. Using it.
  goto :wait_for_servers
)
start "Forkcast website" /D "%CD%\web" cmd /k "node node_modules\next\dist\bin\next dev --port %FRONTEND_PORT%"
echo Started the website in the "Forkcast website" window.

:wait_for_servers
echo.
<nul set /p "=Waiting for the backend"
call :wait_for http://127.0.0.1:%BACKEND_PORT%/ping 15
if errorlevel 1 goto :backend_down
<nul set /p "=Waiting for the website (the first start can take a couple of minutes)"
call :wait_for http://localhost:%FRONTEND_PORT% 30
if errorlevel 1 echo The website has not answered yet. If the page stays blank, look at the "Forkcast website" window.
start "" http://localhost:%FRONTEND_PORT%

echo.
echo Forkcast is running:
echo   Website: http://localhost:%FRONTEND_PORT%
echo   Backend: http://localhost:%BACKEND_PORT%
echo.
echo To stop Forkcast, close the 'Forkcast backend' and 'Forkcast website' windows.
rem The error is hidden because timeout cannot count down when run from Git Bash or with redirected input.
timeout /t 10 2>nul
exit /b 0


rem Tries URL %1 up to %2 times, about 4 seconds per try, printing a dot per miss.
rem "set /p" with empty input prints without a line break. ping is the 2-second pause
rem because timeout quits at once when the script's input is redirected.
:wait_for
set /a TRIES=0
:wait_for_next
curl.exe -sf -m 2 %1 >nul && goto :wait_for_done
set /a TRIES+=1
if %TRIES% geq %2 (
  echo.
  exit /b 1
)
<nul set /p "=."
ping -n 3 127.0.0.1 >nul
goto :wait_for_next
:wait_for_done
echo  ready.
exit /b 0

:no_python
echo.
echo Forkcast needs Python 3.11 or newer, and none was found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then run start.bat again.
pause
exit /b 1

:backend_install_failed
echo.
echo Could not install the backend's Python packages. The error is above.
echo If backend\.venv is broken, delete that folder and run start.bat again.
pause
exit /b 1

:no_node
echo.
echo Forkcast needs Node.js 20 or newer, and it was not found.
echo Install the LTS version from https://nodejs.org/ and run start.bat again.
pause
exit /b 1

:website_install_failed
echo.
echo Could not install the website's packages. The error is above.
pause
exit /b 1

:backend_down
echo.
echo The backend did not answer at http://127.0.0.1:%BACKEND_PORT%/ping.
echo Look at the "Forkcast backend" window for the error. If another program
echo is using port %BACKEND_PORT%, close it and run start.bat again.
pause
exit /b 1
