# ==========================================
#   test_auto_reparador.py
#   Prueba la red de seguridad del punto de
#   restauración: que se cree antes de reparar,
#   y que nunca bloquee la reparación aunque
#   Windows lo rechace.
# ==========================================

import subprocess


class _ResultadoFalso:
    def __init__(self, codigo=0, stdout="", stderr=""):
        self.returncode = codigo
        self.stdout = stdout
        self.stderr = stderr


def test_reparar_archivos_sistema_crea_punto_de_restauracion(monkeypatch):
    import auto_reparador

    llamadas = []

    def run_falso(cmd, **kwargs):
        llamadas.append(cmd)
        if "Checkpoint-Computer" in str(cmd):
            return _ResultadoFalso(0)
        if "DISM" in cmd:
            return _ResultadoFalso(0)
        if "sfc" in cmd:
            return _ResultadoFalso(0, stdout="no se encontraron infracciones de integridad")
        return _ResultadoFalso(0)

    monkeypatch.setattr(auto_reparador.subprocess, "run", run_falso)

    resultado = auto_reparador.reparar_archivos_sistema()

    assert any("Checkpoint-Computer" in str(c) for c in llamadas), \
        "Debería intentar crear un punto de restauración antes de reparar"
    assert "punto de restauración" in resultado.lower()


def test_reparacion_sigue_funcionando_si_windows_rechaza_el_punto(monkeypatch):
    """
    Windows limita cuántos puntos de restauración se pueden crear
    seguidos. Si lo rechaza, NO debe bloquear la reparación real —
    solo se deja de mencionar que se creó uno.
    """
    import auto_reparador

    def run_rechazo(cmd, **kwargs):
        if "Checkpoint-Computer" in str(cmd):
            return _ResultadoFalso(1, stderr="ya existe un punto de restauración reciente")
        if "DISM" in cmd:
            return _ResultadoFalso(0)
        if "sfc" in cmd:
            return _ResultadoFalso(0, stdout="no se encontraron infracciones de integridad")
        return _ResultadoFalso(0)

    monkeypatch.setattr(auto_reparador.subprocess, "run", run_rechazo)

    resultado = auto_reparador.reparar_archivos_sistema()

    assert "Sistema de archivos intacto" in resultado, \
        "La reparación debe seguir funcionando aunque el punto de restauración falle"


def test_desactivar_servicios_tambien_crea_punto_de_restauracion(monkeypatch):
    import auto_reparador

    llamadas = []

    def run_falso(cmd, **kwargs):
        llamadas.append(cmd)
        if "Checkpoint-Computer" in str(cmd):
            return _ResultadoFalso(0)
        return _ResultadoFalso(1)  # servicios ya desactivados, simplifica la prueba

    monkeypatch.setattr(auto_reparador.subprocess, "run", run_falso)
    auto_reparador.desactivar_servicios_basura()

    assert any("Checkpoint-Computer" in str(c) for c in llamadas)


def test_reparar_red_tambien_crea_punto_de_restauracion(monkeypatch):
    import auto_reparador

    llamadas = []

    def run_falso(cmd, **kwargs):
        llamadas.append(cmd)
        return _ResultadoFalso(0)

    monkeypatch.setattr(auto_reparador.subprocess, "run", run_falso)
    resultado = auto_reparador.reparar_red()

    assert any("Checkpoint-Computer" in str(c) for c in llamadas)
    assert "punto de restauración" in resultado.lower()


# ------------------------------------------
#   VERIFICACIÓN POST-REPARACIÓN
#   Que Ada mida de verdad si funcionó, en vez
#   de repetir el mensaje de éxito de Windows.
# ------------------------------------------

def test_reparacion_verificada_cuando_la_segunda_pasada_confirma(monkeypatch):
    import auto_reparador

    def run_ok(cmd, **kwargs):
        if "Checkpoint-Computer" in str(cmd):
            return _ResultadoFalso(0)
        if "DISM" in cmd:
            return _ResultadoFalso(0)
        if cmd == ["sfc", "/scannow"]:
            return _ResultadoFalso(0, stdout="windows encontró archivos corruptos y los reparó")
        if cmd == ["sfc", "/verifyonly"]:
            return _ResultadoFalso(0, stdout="no se encontraron infracciones de integridad")
        return _ResultadoFalso(0)

    monkeypatch.setattr(auto_reparador.subprocess, "run", run_ok)
    resultado = auto_reparador.reparar_archivos_sistema()

    assert "VERIFICADA" in resultado


def test_reparacion_no_verificada_si_la_segunda_pasada_sigue_encontrando_problemas(monkeypatch):
    """
    Antes Ada confiaba ciegamente en el mensaje de sfc de que reparó
    algo. Ahora, si una segunda pasada de verificación todavía
    encuentra problemas, NO debe decir que quedó "VERIFICADA" —
    debe admitir honestamente que no pudo confirmarlo.
    """
    import auto_reparador

    def run_sigue_mal(cmd, **kwargs):
        if "Checkpoint-Computer" in str(cmd):
            return _ResultadoFalso(0)
        if "DISM" in cmd:
            return _ResultadoFalso(0)
        if cmd == ["sfc", "/scannow"]:
            return _ResultadoFalso(0, stdout="windows encontró archivos corruptos y los reparó")
        if cmd == ["sfc", "/verifyonly"]:
            return _ResultadoFalso(0, stdout="windows resource protection found corrupt files")
        return _ResultadoFalso(0)

    monkeypatch.setattr(auto_reparador.subprocess, "run", run_sigue_mal)
    resultado = auto_reparador.reparar_archivos_sistema()

    assert "VERIFICADA" not in resultado
    assert "no pude confirmar" in resultado.lower()


def test_limpiar_winsxs_mide_espacio_real_no_estimado(monkeypatch):
    import auto_reparador

    llamadas = {"veces": 0}

    def disk_usage_falso(path):
        llamadas["veces"] += 1
        libre = 50 * 1024 ** 3 if llamadas["veces"] == 1 else 52.5 * 1024 ** 3
        return type("D", (), {"free": libre, "total": 500 * 1024 ** 3, "percent": 50})()

    monkeypatch.setattr(auto_reparador.psutil, "disk_usage", disk_usage_falso)
    monkeypatch.setattr(auto_reparador.subprocess, "run", lambda cmd, **kw: _ResultadoFalso(0))

    resultado = auto_reparador.limpiar_winsxs()
    assert "2.50 gigabytes" in resultado, "Debería reportar el espacio real medido, no un estimado genérico"


def test_servicio_que_dice_desactivado_pero_sigue_corriendo_no_cuenta(monkeypatch):
    """
    Antes, si 'sc config' devolvía código 0, Ada asumía que el
    servicio quedó desactivado. Ahora verifica con 'sc query' que de
    verdad quedó detenido — un servicio que sigue RUNNING no debe
    contarse como desactivado aunque el comando haya "funcionado".
    """
    import auto_reparador

    def run_falso(cmd, **kwargs):
        if "Checkpoint-Computer" in str(cmd):
            return _ResultadoFalso(0)
        if cmd[:2] == ["sc", "config"]:
            return _ResultadoFalso(0)
        if cmd[:2] == ["sc", "stop"]:
            return _ResultadoFalso(0)
        if cmd[:2] == ["sc", "query"]:
            nombre = cmd[2]
            if nombre == "DiagTrack":
                return _ResultadoFalso(0, stdout="STATE : 1  STOPPED")
            return _ResultadoFalso(0, stdout="STATE : 4  RUNNING")
        return _ResultadoFalso(0)

    monkeypatch.setattr(auto_reparador.subprocess, "run", run_falso)
    resultado = auto_reparador.desactivar_servicios_basura()

    assert "Telemetría" in resultado
    assert "WAP Push" not in resultado, \
        "No debería contar como desactivado un servicio que sigue corriendo de verdad"


def test_reparar_red_verifica_conectividad_real(monkeypatch):
    import auto_reparador
    import socket

    monkeypatch.setattr(auto_reparador.subprocess, "run", lambda cmd, **kw: _ResultadoFalso(0))
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "142.250.0.100")

    resultado = auto_reparador.reparar_red()
    assert "VERIFICADA" in resultado


def test_reparar_red_no_miente_si_sigue_sin_conectividad(monkeypatch):
    import auto_reparador
    import socket

    monkeypatch.setattr(auto_reparador.subprocess, "run", lambda cmd, **kw: _ResultadoFalso(0))

    def falla(host):
        raise OSError("no se pudo resolver")

    monkeypatch.setattr(socket, "gethostbyname", falla)

    resultado = auto_reparador.reparar_red()
    assert "VERIFICADA" not in resultado
    assert "todavía no detecto conectividad" in resultado


def test_diagnostico_drivers_devuelve_dict_estructurado(monkeypatch):
    """
    diagnostico_drivers() antes devolvía solo texto; ahora devuelve un
    dict (para poder alimentar la severidad, mismo tratamiento que
    CPU), pero 'voz' se mantiene con el mismo texto de siempre para
    no romper a quien ya lo usaba (comandos.py).
    """
    import auto_reparador
    import json

    drivers_json = json.dumps([
        {"DeviceName": "Intel HD Graphics", "IsSigned": True},
        {"DeviceName": "Dispositivo raro", "IsSigned": False},
    ])

    monkeypatch.setattr(
        auto_reparador.subprocess, "run",
        lambda cmd, **kw: _ResultadoFalso(0, stdout=drivers_json)
    )

    resultado = auto_reparador.diagnostico_drivers()

    assert isinstance(resultado, dict)
    assert resultado["total"] == 2
    assert resultado["no_firmados"] == 1
    assert resultado["estado"] == "riesgo"
    assert "sin firma digital" in resultado["voz"]


def test_diagnostico_drivers_todos_firmados_es_saludable(monkeypatch):
    import auto_reparador
    import json

    drivers_json = json.dumps([{"DeviceName": "Intel HD Graphics", "IsSigned": True}])
    monkeypatch.setattr(
        auto_reparador.subprocess, "run",
        lambda cmd, **kw: _ResultadoFalso(0, stdout=drivers_json)
    )

    resultado = auto_reparador.diagnostico_drivers()
    assert resultado["estado"] == "saludable"
    assert resultado["no_firmados"] == 0


# ==========================================
#   actualizar_con_winget() -- antes solo
#   listaba en loop, ahora actualiza de verdad
# ==========================================

_SALIDA_WINGET_EJEMPLO = (
    "Name                    Id                          Version      Available    Source\n"
    "-----------------------------------------------------------------------------------\n"
    "Google Chrome           Google.Chrome               121.0.6167   121.0.6222   winget\n"
    "Microsoft Edge          Microsoft.Edge              121.0.1      121.0.5      winget\n"
    "7-Zip                   7zip.7zip                   23.01        24.05        winget\n"
    "2 upgrades available.\n"
)


def test_parsear_ids_saca_los_ids_reales_no_el_texto_de_la_linea():
    import auto_reparador
    ids = auto_reparador._parsear_ids_actualizables(_SALIDA_WINGET_EJEMPLO, excluidos=[])
    assert "Google.Chrome" in ids
    assert "Microsoft.Edge" in ids
    assert "7zip.7zip" in ids
    assert len(ids) == 3


def test_parsear_ids_respeta_la_lista_de_excluidos():
    import auto_reparador
    ids = auto_reparador._parsear_ids_actualizables(
        _SALIDA_WINGET_EJEMPLO, excluidos=["Microsoft.Edge"]
    )
    assert "Microsoft.Edge" not in ids
    assert "Google.Chrome" in ids
    assert len(ids) == 2


def test_actualizar_con_winget_ejecuta_de_verdad_no_solo_lista(monkeypatch):
    """
    El bug real: antes esto solo listaba y pedía 'actualiza todo' de
    nuevo, sin ejecutar nada jamás. Ahora debe llamar a winget upgrade
    por cada paquete detectado.
    """
    import auto_reparador

    llamadas = []

    def fake_run(cmd, **kwargs):
        llamadas.append(cmd)
        if cmd[:2] == ["winget", "upgrade"] and "--id" not in cmd:
            return _ResultadoFalso(0, stdout=_SALIDA_WINGET_EJEMPLO)
        return _ResultadoFalso(0)  # cada actualización individual "exitosa"

    monkeypatch.setattr(auto_reparador.subprocess, "run", fake_run)

    resultado = auto_reparador.actualizar_con_winget(seguro=True)

    comandos_de_actualizacion = [c for c in llamadas if "--id" in c]
    ids_actualizados = [c[c.index("--id") + 1] for c in comandos_de_actualizacion]

    assert "Google.Chrome" in ids_actualizados
    assert "7zip.7zip" in ids_actualizados
    assert "Microsoft.Edge" not in ids_actualizados, "seguro=True debe excluir Edge"
    assert "Actualicé" in resultado


def test_actualizar_con_winget_reporta_fallos_reales(monkeypatch):
    import auto_reparador

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["winget", "upgrade"] and "--id" not in cmd:
            return _ResultadoFalso(0, stdout=_SALIDA_WINGET_EJEMPLO)
        if "Google.Chrome" in cmd:
            return _ResultadoFalso(1)  # este falla de verdad
        return _ResultadoFalso(0)

    monkeypatch.setattr(auto_reparador.subprocess, "run", fake_run)

    resultado = auto_reparador.actualizar_con_winget(seguro=True)

    assert "no se pudieron actualizar" in resultado
    assert "Google.Chrome" in resultado


def test_actualizar_con_winget_todo_al_dia_no_intenta_actualizar_nada(monkeypatch):
    import auto_reparador

    # Así responde winget de verdad cuando no hay nada pendiente: sin
    # tabla de encabezado, solo un mensaje -- no una tabla vacía con
    # texto suelto adentro.
    salida_sin_pendientes = "No installed package found matching input criteria.\n"

    def fake_run(cmd, **kwargs):
        return _ResultadoFalso(0, stdout=salida_sin_pendientes)

    monkeypatch.setattr(auto_reparador.subprocess, "run", fake_run)

    resultado = auto_reparador.actualizar_con_winget()
    assert "actualizado" in resultado.lower()
