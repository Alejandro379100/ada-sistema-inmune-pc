# ==========================================
#   Tests de vigilante_tecnologico.py
#   Detección de actualizaciones de Windows y
#   registro de qué módulos de Ada revisar.
# ==========================================

import os
import json
import tempfile

import pytest


@pytest.fixture
def snapshot_temporal(monkeypatch):
    """Redirige el snapshot de versión a un archivo temporal, aislado
    de cualquier snapshot real que pudiera existir en /privado/."""
    import vigilante_tecnologico
    tmp_path = tempfile.mktemp(suffix=".json")
    monkeypatch.setattr(vigilante_tecnologico, "SNAPSHOT", tmp_path)
    yield tmp_path
    if os.path.exists(tmp_path):
        os.remove(tmp_path)


def test_inicializar_guarda_linea_base_sin_generar_alerta(snapshot_temporal, monkeypatch):
    """La primera vez que corre, solo debe guardar la versión actual
    como línea base -- nunca debe registrar un 'cambio'."""
    import vigilante_tecnologico as vt

    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "22631", "ubr": "3527", "build_completo": "22631.3527",
        "version_nombre": "23H2", "product_name": "Windows 11 Pro",
    })

    vt.inicializar()

    guardado = vt._cargar_snapshot()
    assert guardado["build_completo"] == "22631.3527"


def test_primera_llamada_a_verificar_no_reporta_cambio(snapshot_temporal, monkeypatch):
    """Si todavía no hay snapshot guardado, verificar_actualizacion_os
    debe guardar la línea base y no reportar nada -- no hay 'anterior'
    con qué comparar todavía."""
    import vigilante_tecnologico as vt

    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "22631", "ubr": "3527", "build_completo": "22631.3527",
    })

    resultado = vt.verificar_actualizacion_os()

    assert resultado == ""
    assert vt._cargar_snapshot()["build_completo"] == "22631.3527"


def test_sin_cambio_de_version_no_reporta_nada(snapshot_temporal, monkeypatch):
    """Si la versión es exactamente la misma que la guardada, no debe
    generarse ninguna alerta -- no hay nada que revisar."""
    import vigilante_tecnologico as vt

    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "22631", "ubr": "3527", "build_completo": "22631.3527",
    })
    vt._guardar_snapshot({"build": "22631", "ubr": "3527", "build_completo": "22631.3527"})

    assert vt.verificar_actualizacion_os() == ""


def test_cambio_de_ubr_se_detecta_como_prioridad_media(db_temporal, snapshot_temporal, monkeypatch):
    """Un cambio SOLO en el UBR (parche acumulativo, sin cambiar el
    número de build) debe reportarse con prioridad media, no alta."""
    import vigilante_tecnologico as vt

    vt._guardar_snapshot({"build": "22631", "ubr": "3527", "build_completo": "22631.3527"})
    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "22631", "ubr": "3800", "build_completo": "22631.3800",
    })

    resultado = vt.verificar_actualizacion_os()

    assert "22631.3527" in resultado
    assert "22631.3800" in resultado
    assert "Prioridad: media" in resultado
    assert "[VIGILANTE TECNOLÓGICO]" in resultado


def test_cambio_de_build_se_detecta_como_prioridad_alta(db_temporal, snapshot_temporal, monkeypatch):
    """Un cambio en el número de BUILD (actualización de función, más
    propensa a romper formatos de comandos) debe ser prioridad alta."""
    import vigilante_tecnologico as vt

    vt._guardar_snapshot({"build": "22631", "ubr": "3527", "build_completo": "22631.3527"})
    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "26100", "ubr": "1000", "build_completo": "26100.1000",
    })

    resultado = vt.verificar_actualizacion_os()

    assert "Prioridad: alta" in resultado


def test_cambio_detectado_queda_registrado_en_memoria(db_temporal, snapshot_temporal, monkeypatch):
    """El cambio debe quedar guardado en memoria.cambios_tecnologicos
    para poder revisarlo después, no solo mencionarse una vez en el log."""
    import vigilante_tecnologico as vt

    vt._guardar_snapshot({"build": "22631", "ubr": "3527", "build_completo": "22631.3527"})
    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "26100", "ubr": "1000", "build_completo": "26100.1000",
    })

    vt.verificar_actualizacion_os()

    historial = db_temporal.historial_cambios_tecnologicos()
    assert len(historial) == 1
    entrada = historial[0]
    assert entrada["version_anterior"] == "22631.3527"
    assert entrada["version_nueva"] == "26100.1000"
    assert entrada["prioridad"] == "alta"
    assert entrada["revisado"] is False
    assert "auto_reparador.py" in entrada["modulos_afectados"]
    assert "medico.py" in entrada["modulos_afectados"]


def test_marcar_revisado_evita_que_se_repita(db_temporal, snapshot_temporal, monkeypatch):
    """Una vez marcado como revisado, no debe seguir apareciendo en
    la lista de pendientes."""
    import vigilante_tecnologico as vt

    vt._guardar_snapshot({"build": "22631", "ubr": "3527", "build_completo": "22631.3527"})
    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "26100", "ubr": "1000", "build_completo": "26100.1000",
    })
    vt.verificar_actualizacion_os()

    pendientes_antes = db_temporal.historial_cambios_tecnologicos(solo_pendientes=True)
    assert len(pendientes_antes) == 1

    db_temporal.marcar_cambio_tecnologico_revisado(pendientes_antes[0]["id"])

    pendientes_despues = db_temporal.historial_cambios_tecnologicos(solo_pendientes=True)
    assert pendientes_despues == []
    # pero sigue existiendo en el historial completo
    assert len(db_temporal.historial_cambios_tecnologicos()) == 1


def test_estimacion_de_groq_se_agrega_pero_se_aclara_que_es_general(db_temporal, snapshot_temporal, monkeypatch):
    """Si se pasa preguntar_groq_fn, su respuesta se agrega al
    mensaje -- pero el mensaje ya deja explícito que no son notas
    oficiales del parche, con o sin Groq."""
    import vigilante_tecnologico as vt

    vt._guardar_snapshot({"build": "22631", "ubr": "3527", "build_completo": "22631.3527"})
    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "26100", "ubr": "1000", "build_completo": "26100.1000",
    })

    respuesta_groq = "Suelen cambiar cmdlets de PowerShell y formatos de WMI."
    resultado = vt.verificar_actualizacion_os(preguntar_groq_fn=lambda prompt: respuesta_groq)

    assert respuesta_groq in resultado
    assert "no tengo acceso a las notas oficiales del parche" in resultado.lower()


def test_falla_de_groq_no_rompe_la_deteccion(db_temporal, snapshot_temporal, monkeypatch):
    """Si preguntar_groq_fn tira una excepción, igual debe reportarse
    el cambio de versión -- Groq es un extra, no una dependencia dura."""
    import vigilante_tecnologico as vt

    vt._guardar_snapshot({"build": "22631", "ubr": "3527", "build_completo": "22631.3527"})
    monkeypatch.setattr(vt, "_leer_version_windows", lambda: {
        "build": "26100", "ubr": "1000", "build_completo": "26100.1000",
    })

    def groq_roto(prompt):
        raise RuntimeError("sin conexión")

    resultado = vt.verificar_actualizacion_os(preguntar_groq_fn=groq_roto)

    assert "[VIGILANTE TECNOLÓGICO]" in resultado
    assert "26100.1000" in resultado
