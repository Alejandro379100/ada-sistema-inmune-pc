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
echo     1. Ada Terminal
echo     2. Activar Ada Invisible
echo     3. Desactivar Ada Invisible
echo     4. Salir de la Terminal
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
REM
REM   Antes esto disparaba una tarea programada
REM   de Windows ("Ada - Modo Terminal") para
REM   evitar pedir permiso de administrador cada
REM   vez -- pero esa tarea no abria una ventana
REM   visible al ejecutarse, entonces la opcion 1
REM   "desaparecia" sin dejar escribirle a Ada.
REM   Ahora va siempre directo: pide permiso cada
REM   vez, pero SIEMPRE abre la ventana donde
REM   podes escribirle.
REM ==========================================
:iniciar
net session >nul 2>&1
if %errorlevel% == 0 goto :admin_iniciar

echo.
echo   Pidiendo permisos de administrador...
echo   Esta ventana se va a cerrar sola y va a abrir OTRA en su lugar --
echo   es normal, no es un error. Es la unica forma en que Windows deja
echo   pedir permisos de administrador para un script.
echo.
timeout /t 3 >nul

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

REM Revisa si Ada ya esta corriendo invisible antes de abrir el modo
REM terminal -- evita que queden dos copias compitiendo por la misma
REM base de datos al mismo tiempo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gestionar_inicio.ps1"

if %errorlevel% neq 0 (
    echo.
    echo   Ada se cerro con un error. Revisa ada_log.txt en esta carpeta.
    pause
)
exit /b

REM ==========================================
REM   2) INSTALAR ARRANQUE AUTOMATICO
REM   Solo crea la tarea que arranca a Ada sola,
REM   invisible, al iniciar sesion. Ya no crea la
REM   tarea de "Modo Terminal" -- la opcion 1 de
REM   este menu ahora siempre abre directo.
REM ==========================================
:instalar
net session >nul 2>&1
if %errorlevel% == 0 goto :admin_instalar

echo.
echo   Necesito permisos de administrador para instalar la tarea
echo   programada. Va a pedirte el permiso de Windows ahora --
echo   esta es la UNICA vez que te lo va a pedir para esto.
echo.
powershell -Command "Start-Process '%~f0' -ArgumentList 'instalar' -Verb RunAs"
exit /b

:admin_instalar
schtasks /Create /TN "Ada - Sistema Inmune Personal" ^
    /TR "\"%~dp0.venv\Scripts\python.exe\" \"%~dp0app.py\" --invisible" ^
    /SC ONLOGON ^
    /RL HIGHEST ^
    /F

REM Limpieza: si de una instalacion vieja quedo la tarea de "Modo
REM Terminal" (ya no se usa), la borramos para no dejar basura.
schtasks /Delete /TN "Ada - Modo Terminal" /F >nul 2>&1

if %errorlevel% == 0 (
    echo.
    echo   Listo. Desde ahora Ada arranca sola, invisible y con
    echo   permisos, al iniciar sesion. La opcion 1 de este menu
    echo   te va a pedir permiso de administrador cada vez que la
    echo   uses -- es normal, asi queda mas confiable.
    echo.
) else (
    echo.
    echo   Algo fallo creando la tarea. Revisa el mensaje de arriba.
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
schtasks /Delete /TN "Ada - Modo Terminal" /F >nul 2>&1
echo.
echo   Listo, la tarea programada se elimino. Ada ya no arranca sola.
echo.
pause
exit /b
