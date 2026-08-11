@echo off
REM ==========================================
REM   ada.bat - Todo-en-uno para Ada v5.0
REM
REM   Un solo archivo con menu:
REM     1) Iniciar Ada (modo terminal)
REM     2) Instalar arranque automatico (una vez)
REM     3) Desinstalar arranque automatico
REM     4) Salir
REM
REM   PARA EL ICONO DE ESCRITORIO:
REM   Click derecho sobre este archivo > "Mostrar mas
REM   opciones" > "Enviar a" > "Escritorio (crear acceso
REM   directo)". No muevas este .bat de la carpeta de Ada.
REM ==========================================

title Ada v5.0 - Sistema Inmune Personal
cd /d "%~dp0"

REM Si se llama con un argumento (ej: ada.bat iniciar), saltea el
REM menu -- asi la tarea programada de modo terminal puede llamarlo
REM directo sin que aparezca un menu esperando que elijas algo.
if "%~1"=="iniciar" goto :iniciar
if "%~1"=="instalar" goto :instalar
if "%~1"=="desinstalar" goto :desinstalar

:menu
cls
echo.
echo   ============================================
echo     Ada v5.0 - Sistema Inmune Personal
echo   ============================================
echo.
echo     1. Iniciar Ada
echo     2. Instalar arranque automatico (una sola vez)
echo     3. Desinstalar arranque automatico
echo     4. Salir
echo.
set /p opcion="  Elegi una opcion (1-4): "

if "%opcion%"=="1" goto :iniciar
if "%opcion%"=="2" goto :instalar
if "%opcion%"=="3" goto :desinstalar
if "%opcion%"=="4" exit /b
echo   Opcion invalida.
pause
goto :menu

REM ==========================================
REM   1) INICIAR ADA
REM ==========================================
:iniciar
REM Si ya instalaste el arranque automatico, la tarea "Ada - Modo
REM Terminal" ya tiene permiso de administrador dado de una vez --
REM asi que no vuelve a pedir el cuadro de permiso de Windows.
schtasks /Query /TN "Ada - Modo Terminal" >nul 2>&1
if %errorlevel% == 0 (
    schtasks /Run /TN "Ada - Modo Terminal"
    exit /b
)

REM Si todavia no la instalaste, se auto-eleva pidiendo permiso esta vez.
net session >nul 2>&1
if %errorlevel% == 0 goto :admin_iniciar

echo.
echo   Ada necesita permisos de administrador para leer temperatura,
echo   drivers y algunos diagnosticos del sistema. Va a pedirte el
echo   permiso de Windows ahora...
echo.
echo   (Tip: elegi la opcion 2 del menu una vez y esto no te lo va
echo   a volver a pedir.)
echo.
powershell -Command "Start-Process '%~f0' -ArgumentList 'iniciar' -Verb RunAs"
exit /b

:admin_iniciar
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   No encuentro el entorno virtual ^(.venv^) en esta carpeta.
    echo   Corre primero: python -m venv .venv
    echo   y luego:       .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Antes esto corria ".venv\Scripts\python.exe app.py" directo, sin
REM revisar nada -- si Ada ya estaba corriendo invisible (arranque
REM automatico al iniciar sesion), esto abria una SEGUNDA copia al
REM mismo tiempo, compitiendo por el mismo ada_cerebro.db. Ahora se
REM delega a gestionar_inicio.ps1, que revisa primero y pregunta.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gestionar_inicio.ps1"

if %errorlevel% neq 0 (
    echo.
    echo   Ada se cerro con un error. Revisa ada_log.txt en esta carpeta.
    pause
)
exit /b

REM ==========================================
REM   2) INSTALAR ARRANQUE AUTOMATICO
REM   Crea 2 tareas programadas, ambas con
REM   permiso de administrador dado de una vez:
REM   - "Ada - Sistema Inmune Personal": arranca
REM     sola en modo invisible al iniciar sesion.
REM   - "Ada - Modo Terminal": queda lista para
REM     que la opcion 1 de este menu la dispare
REM     sin pedir permiso nunca mas.
REM ==========================================
:instalar
net session >nul 2>&1
if %errorlevel% == 0 goto :admin_instalar

echo.
echo   Necesito permisos de administrador para instalar las tareas
echo   programadas. Va a pedirte el permiso de Windows ahora --
echo   esta es la UNICA vez que te lo va a pedir.
echo.
powershell -Command "Start-Process '%~f0' -ArgumentList 'instalar' -Verb RunAs"
exit /b

:admin_instalar
schtasks /Create /TN "Ada - Sistema Inmune Personal" ^
    /TR "\"%~dp0.venv\Scripts\python.exe\" \"%~dp0app.py\" --invisible" ^
    /SC ONLOGON ^
    /RL HIGHEST ^
    /F

schtasks /Create /TN "Ada - Modo Terminal" ^
    /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0gestionar_inicio.ps1\"" ^
    /SC ONCE /ST 00:00 /RL HIGHEST /F

if %errorlevel% == 0 (
    echo.
    echo   Listo. Desde ahora:
    echo   - Ada arranca sola, invisible y con permisos, al iniciar sesion.
    echo   - La opcion 1 de este menu ya no te va a pedir permiso nunca mas.
    echo.
) else (
    echo.
    echo   Algo fallo creando las tareas. Revisa el mensaje de arriba.
    echo.
)
pause
exit /b

REM ==========================================
REM   3) DESINSTALAR ARRANQUE AUTOMATICO
REM ==========================================
:desinstalar
net session >nul 2>&1
if %errorlevel% == 0 goto :admin_desinstalar

powershell -Command "Start-Process '%~f0' -ArgumentList 'desinstalar' -Verb RunAs"
exit /b

:admin_desinstalar
schtasks /Delete /TN "Ada - Sistema Inmune Personal" /F
schtasks /Delete /TN "Ada - Modo Terminal" /F
echo.
echo   Listo, las tareas programadas se eliminaron. Ada ya no arranca
echo   sola, y la opcion 1 va a volver a pedir permiso cada vez.
echo.
pause
exit /b
