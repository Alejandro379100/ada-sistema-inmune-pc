@echo off
REM ==========================================
REM   ada.bat - Acceso rapido a Ada v5.0
REM
REM   Un solo archivo con menu:
REM     1) Iniciar Ada (modo terminal)
REM     2) Salir
REM
REM   El arranque automatico en modo invisible ya
REM   esta resuelto por la tarea programada "Ada"
REM   de Windows (Programador de tareas) -- este
REM   .bat es solo para cuando quieras abrir Ada
REM   por terminal y pedirle informacion a mano.
REM
REM   PARA EL ICONO DE ESCRITORIO:
REM   Click derecho sobre este archivo > "Mostrar mas
REM   opciones" > "Enviar a" > "Escritorio (crear acceso
REM   directo)". No muevas este .bat de la carpeta de Ada.
REM ==========================================

title Ada v5.0 - Sistema Inmune Personal
cd /d "%~dp0"

REM Si se llama con un argumento (ej: ada.bat iniciar), saltea el
REM menu -- asi se puede llamar directo sin que aparezca un menu
REM esperando que elijas algo.
if "%~1"=="iniciar" goto :iniciar

:menu
cls
echo.
echo   ============================================
echo     Ada v5.0 - Sistema Inmune Personal
echo   ============================================
echo.
echo     1. Iniciar Ada
echo     2. Salir
echo.
set /p opcion="  Elegi una opcion (1-2): "

if "%opcion%"=="1" goto :iniciar
if "%opcion%"=="2" exit /b
echo   Opcion invalida.
pause
goto :menu

REM ==========================================
REM   1) INICIAR ADA (modo terminal)
REM ==========================================
:iniciar
net session >nul 2>&1
if %errorlevel% == 0 goto :admin_iniciar

echo.
echo   Ada necesita permisos de administrador para leer temperatura,
echo   drivers y algunos diagnosticos del sistema. Va a pedirte el
echo   permiso de Windows ahora...
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

.venv\Scripts\python.exe app.py

if %errorlevel% neq 0 (
    echo.
    echo   Ada se cerro con un error. Revisa ada_log.txt en esta carpeta.
    pause
)
exit /b
