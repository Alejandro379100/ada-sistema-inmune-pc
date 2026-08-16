# ==========================================
#   test_auto_reparador_condiciones.py
#   Prueba condiciones_desfavorables_para_reparacion_pesada():
#   el chequeo de "buen momento" antes de correr SFC/DISM,
#   agregado tras diagnosticar con log real que los fallos de
#   reparar_archivos_sistema no eran corrupción, eran RAM crítica
#   o TiWorker.exe compitiendo por el mismo almacén WinSxS.
# ==========================================

import types
import psutil
import pytest

import auto_reparador
from config import RAM_CRITICA_GB


def _mem_falsa(gb_libres: float):
    """Fabrica un objeto con el mismo shape que psutil.virtual_memory()
    -- namedtuple real tiene más campos, pero .available es el único
    que lee condiciones_desfavorables_para_reparacion_pesada()."""
    return types.SimpleNamespace(available=gb_libres * (1024 ** 3))


def _proceso_falso(nombre: str):
    """Fabrica un objeto con el mismo shape que un psutil.Process
    devuelto por process_iter(['name']) -- .info es un dict, no un
    método, cuando se piden attrs específicos."""
    return types.SimpleNamespace(info={"name": nombre})


def test_ram_critica_bloquea(monkeypatch):
    """RAM por debajo del umbral crítico -- motivo no vacío, sin
    necesidad de mirar procesos (ni siquiera debería llegar a
    chequear TiWorker, pero si lo hace tampoco debe romper nada)."""
    monkeypatch.setattr(psutil, "virtual_memory",
                         lambda: _mem_falsa(RAM_CRITICA_GB - 0.5))
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([]))

    motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()

    assert motivo != ""
    assert "RAM crítica" in motivo


def test_tiworker_corriendo_bloquea(monkeypatch):
    """RAM sobrada, pero TiWorker.exe está en la lista de procesos --
    motivo no vacío, y menciona TiWorker para que quede claro en el
    log/notificación por qué se difirió."""
    monkeypatch.setattr(psutil, "virtual_memory",
                         lambda: _mem_falsa(RAM_CRITICA_GB + 4.0))
    monkeypatch.setattr(psutil, "process_iter",
                         lambda attrs=None: iter([
                             _proceso_falso("explorer.exe"),
                             _proceso_falso("TiWorker.exe"),  # mayúsculas a propósito -- el chequeo es case-insensitive
                             _proceso_falso("python.exe"),
                         ]))

    motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()

    assert motivo != ""
    assert "TiWorker" in motivo


def test_todo_bien_no_bloquea(monkeypatch):
    """RAM sobrada y sin TiWorker corriendo -- "" (buen momento para
    intentar la reparación)."""
    monkeypatch.setattr(psutil, "virtual_memory",
                         lambda: _mem_falsa(RAM_CRITICA_GB + 4.0))
    monkeypatch.setattr(psutil, "process_iter",
                         lambda attrs=None: iter([
                             _proceso_falso("explorer.exe"),
                             _proceso_falso("python.exe"),
                         ]))

    motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()

    assert motivo == ""


def test_ram_justo_en_el_umbral_no_bloquea(monkeypatch):
    """Caso límite: exactamente en el umbral no cuenta como crítico
    -- la condición real es '<', no '<='. Mismo criterio que
    RAM_CRITICA_GB ya usa en el resto de Ada (sistema.py)."""
    monkeypatch.setattr(psutil, "virtual_memory",
                         lambda: _mem_falsa(RAM_CRITICA_GB))
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([]))

    motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()

    assert motivo == ""


def test_falla_al_medir_ram_no_rompe_y_sigue_al_siguiente_chequeo(monkeypatch):
    """Si psutil.virtual_memory() explota (no debería, pero el
    código está escrito para no confiar en eso), no debe propagar la
    excepción -- debe seguir al chequeo de TiWorker con normalidad."""
    def _explota():
        raise OSError("medición no disponible en este entorno")

    monkeypatch.setattr(psutil, "virtual_memory", _explota)
    monkeypatch.setattr(psutil, "process_iter",
                         lambda attrs=None: iter([_proceso_falso("TiWorker.exe")]))

    motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()

    assert "TiWorker" in motivo  # llegó al segundo chequeo pese al fallo del primero


def test_falla_al_listar_procesos_no_rompe(monkeypatch):
    """Si process_iter() explota, tampoco debe propagar -- con RAM
    ya descartada como problema, el resultado final es 'todo bien'
    (no se puede afirmar que hay mal momento sin poder comprobarlo)."""
    def _explota(attrs=None):
        raise OSError("no se pudo listar procesos en este entorno")

    monkeypatch.setattr(psutil, "virtual_memory",
                         lambda: _mem_falsa(RAM_CRITICA_GB + 4.0))
    monkeypatch.setattr(psutil, "process_iter", _explota)

    motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()

    assert motivo == ""


def test_reparar_archivos_sistema_y_limpiar_winsxs_estan_en_la_lista():
    """Chequeo de que la lista de acciones sensibles a recursos
    sigue incluyendo las dos acciones basadas en DISM -- si alguien
    agrega una tercera acción con DISM más adelante y se olvida de
    sumarla acá, este test no lo detecta (no puede saber sobre
    acciones futuras), pero sí protege contra que alguien saque una
    de las dos actuales sin querer."""
    assert "reparar_archivos_sistema" in auto_reparador.ACCIONES_SENSIBLES_A_RECURSOS
    assert "limpiar_winsxs" in auto_reparador.ACCIONES_SENSIBLES_A_RECURSOS
