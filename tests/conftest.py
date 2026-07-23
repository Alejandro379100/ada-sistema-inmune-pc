# ==========================================
#   conftest.py — configuración compartida de pytest
#
#   Ada usa varias cosas que solo existen en Windows
#   (winreg, wmi). Aquí se instalan versiones falsas
#   ANTES de que cualquier módulo de Ada se importe,
#   para poder correr las pruebas en cualquier
#   sistema operativo, no solo en Windows.
# ==========================================

import sys
import os
import types
import sqlite3
import tempfile
import importlib
import importlib.util

# Ada vive un nivel arriba de tests/
ADA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ADA_DIR)


def _instalar_winreg_falso():
    """
    monitor_arranque.py y app.py hacen 'import winreg' directo, que
    solo existe en Windows. Sin esto, ni siquiera se pueden importar
    esos módulos en Linux/Mac para probarlos.
    """
    if "winreg" in sys.modules:
        return
    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 1
    fake.HKEY_LOCAL_MACHINE = 2
    fake.KEY_READ = 1
    fake.KEY_SET_VALUE = 2
    fake.REG_SZ = 1

    def _open_key(*a, **k):
        raise FileNotFoundError("clave de registro no encontrada (entorno de prueba)")

    fake.OpenKey = _open_key
    fake.EnumValue = lambda *a, **k: (_ for _ in ()).throw(OSError("sin más valores"))
    fake.CloseKey = lambda *a, **k: None
    fake.SetValueEx = lambda *a, **k: None
    sys.modules["winreg"] = fake


def _instalar_wmi_falso():
    """wmi solo existe en Windows; sistema.py lo importa de forma
    perezosa (dentro de la función), pero lo dejamos disponible por
    si alguna prueba necesita importarlo explícitamente."""
    if "wmi" in sys.modules:
        return
    fake = types.ModuleType("wmi")
    fake.WMI = lambda *a, **k: types.SimpleNamespace(
        MSAcpi_ThermalZoneTemperature=lambda: []
    )
    sys.modules["wmi"] = fake


def _instalar_create_no_window_falso():
    """
    subprocess.CREATE_NO_WINDOW solo existe en Windows. auto_reparador.py
    lo usa como argumento en cada llamada a subprocess.run — sin esto,
    ni siquiera se puede importar/probar ese módulo en Linux/Mac.
    """
    import subprocess
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        subprocess.CREATE_NO_WINDOW = 0x08000000


_instalar_winreg_falso()
_instalar_wmi_falso()
_instalar_create_no_window_falso()

import pytest


@pytest.fixture
def db_temporal(monkeypatch):
    """
    Crea una base de datos SQLite temporal y aislada para cada
    prueba, usando memoria.py real (no un simulacro) — así las
    pruebas validan el código de verdad, pero nunca tocan
    ada_cerebro.db de una instalación real.
    """
    import memoria
    tmp_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setattr(memoria, "DB_PATH", tmp_path)
    memoria.inicializar_db()
    yield memoria
    if os.path.exists(tmp_path):
        os.remove(tmp_path)


@pytest.fixture
def sin_subprocess_real(monkeypatch):
    """
    Evita que cualquier prueba ejecute de verdad comandos del
    sistema (DISM, SFC, taskkill, netsh, etc.) — todas las llamadas a
    subprocess.run quedan interceptadas y devuelven un resultado
    controlado y seguro.
    """
    import subprocess

    class ResultadoFalso:
        def __init__(self):
            self.stdout = ""
            self.stderr = ""
            self.returncode = 0

    def run_falso(*args, **kwargs):
        return ResultadoFalso()

    monkeypatch.setattr(subprocess, "run", run_falso)
    return run_falso


@pytest.fixture
def estado_limpio_comandos():
    """Resetea el estado en memoria de comandos.py antes de cada
    prueba, para que una prueba no contamine a la siguiente."""
    import comandos
    original = dict(comandos._estado)
    comandos._estado.update({
        "esperando_password": False,
        "accion_pendiente": None,
        "accion_pendiente_data": None,
        "lista_apps": [],
        "ultimo_software_url": None,
        "edge_preguntado": False,
    })
    yield comandos
    comandos._estado.clear()
    comandos._estado.update(original)
