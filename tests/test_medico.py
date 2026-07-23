# ==========================================
#   test_medico.py
#   Prueba el médico autónomo: que Groq solo
#   pueda elegir de la lista blanca, que respete
#   el riesgo, y que no repita reparaciones.
# ==========================================

import pytest


def test_riesgo_bajo_se_ejecuta_solo(db_temporal, monkeypatch):
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "cache corrupta"}]
    })

    import auto_reparador
    ejecutado = {"veces": 0}

    def limpiar_fake():
        ejecutado["veces"] += 1
        return "Caché reconstruida."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"limpiar_cache_iconos": limpiar_fake})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutado["veces"] == 1
    assert "Caché reconstruida" in resultado


def test_mal_historial_baja_la_reparacion_a_solo_recomendar(db_temporal, monkeypatch):
    """
    Aprendizaje de reparaciones: si una acción ya falló la mayoría de
    las últimas veces en este equipo, el médico no debería ejecutarla
    sola de nuevo aunque Groq la recomiende como riesgo bajo/medio —
    debe bajarla a "solo recomendar", igual que hace con riesgo alto.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import auto_reparador
    ejecutado = {"veces": 0}

    def limpiar_fake():
        ejecutado["veces"] += 1
        return "Caché reconstruida."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"limpiar_cache_iconos": limpiar_fake})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    memoria = db_temporal
    # 3 intentos previos, todos fracasados -> tasa de éxito 0%
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_cache_iconos", "bajo", "razon", ejecutada=True,
            resultado="Error limpiando caché de íconos: acceso denegado."
        )
    # El historial de prueba de arriba también activaría el cooldown
    # de 24h (registrar_decision_medico_ia usa la hora actual) — para
    # esta prueba nos interesa aislar la lógica de aprendizaje, no el
    # cooldown, que ya tiene su propio test.
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente", lambda accion, horas=24: False)

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "cache corrupta"}]
    })

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutado["veces"] == 0, "No debería ejecutarla sola con historial malo"
    assert "no la ejecuto sola" in resultado.lower()


def test_buen_historial_no_bloquea_la_reparacion(db_temporal, monkeypatch):
    """Contraparte: con historial mayormente exitoso, la reparación
    de riesgo bajo/medio se sigue ejecutando sola como siempre."""
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import auto_reparador
    ejecutado = {"veces": 0}

    def limpiar_fake():
        ejecutado["veces"] += 1
        return "Caché reconstruida."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"limpiar_cache_iconos": limpiar_fake})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    memoria = db_temporal
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_cache_iconos", "bajo", "razon", ejecutada=True,
            resultado="Caché de íconos reconstruida. Eliminé 4 archivos viejos."
        )
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente", lambda accion, horas=24: False)

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "cache corrupta"}]
    })

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutado["veces"] == 1
    assert "Caché reconstruida" in resultado


def test_riesgo_medio_no_se_ejecuta_la_primera_vez(db_temporal, monkeypatch):
    """
    Nivel de confirmación intermedio: una acción de riesgo medio no
    se ejecuta a la primera lectura -- necesita verse confirmada en
    un segundo ciclo antes de que Ada actúe sola.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "alta"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import auto_reparador
    ejecutado = {"veces": 0}

    def desactivar_fake():
        ejecutado["veces"] += 1
        return "Servicios desactivados."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"desactivar_servicios_basura": desactivar_fake})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "desactivar_servicios_basura", "riesgo": "medio", "razon": "RAM alta"}]
    })

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutado["veces"] == 0, "Riesgo medio no debería ejecutarse a la primera lectura"
    assert "todavía no la ejecuto" in resultado.lower()


def test_riesgo_medio_se_ejecuta_confirmado_en_el_segundo_ciclo(db_temporal, monkeypatch):
    """Contraparte: si el mismo problema persiste y Groq vuelve a
    recomendar la misma acción, ahí sí se ejecuta sola."""
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "alta"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import auto_reparador
    ejecutado = {"veces": 0}

    def desactivar_fake():
        ejecutado["veces"] += 1
        return "Servicios desactivados."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"desactivar_servicios_basura": desactivar_fake})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "desactivar_servicios_basura", "riesgo": "medio", "razon": "RAM alta"}]
    })

    # Ciclo 1: se registra como "pendiente confirmación"
    medico.autodiagnostico_y_reparacion()
    assert ejecutado["veces"] == 0

    # Ciclo 2: mismo problema persiste, Groq recomienda lo mismo otra vez
    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutado["veces"] == 1, "Confirmado en el segundo ciclo, ahora sí se ejecuta"
    assert "Servicios desactivados" in resultado


def test_riesgo_alto_no_se_ejecuta_solo(db_temporal, monkeypatch):
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos",
                         lambda horas=24: [{"tiempo": "2026-07-18 08:00", "nivel": 2, "fuente": "Test"}])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "errores de red")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "reparar_red", "riesgo": "alto", "razon": "perdida de paquetes"}]
    })

    import auto_reparador

    def NO_DEBERIA_LLAMARSE():
        raise AssertionError("Ada ejecutó una acción de riesgo alto sin confirmación humana")

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION",
                         {"reparar_red": NO_DEBERIA_LLAMARSE})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()  # no debe lanzar AssertionError
    assert "riesgo alto" in resultado
    assert "no la ejecuto sola" in resultado


def test_accion_fuera_de_lista_blanca_se_ignora(db_temporal, monkeypatch):
    """
    Fail-safe: si Groq inventa una acción que no está en ninguna de
    las dos listas blancas, Ada no debe ejecutar nada.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "formatear_disco_completo", "riesgo": "alto", "razon": "inventado"}]
    })

    import auto_reparador
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()
    assert resultado == ""


def test_no_repite_la_misma_reparacion_en_24h(db_temporal, monkeypatch):
    """
    El bug real que viste en tu terminal: la misma reparación se
    ejecutaba cada 3 horas para el mismo error viejo del Event Log.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok"})
    monkeypatch.setattr(medico, "leer_eventos_criticos",
                         lambda horas=24: [{"tiempo": "2026-07-11 08:00", "nivel": 2, "fuente": "Test"}])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "errores en registros")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "reparar_archivos_sistema", "riesgo": "medio", "razon": "errores en registros"}]
    })

    import auto_reparador
    llamadas = {"veces": 0}

    def reparar_fake():
        llamadas["veces"] += 1
        return "Reparación completada."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"reparar_archivos_sistema": reparar_fake})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    medico.autodiagnostico_y_reparacion()
    medico.autodiagnostico_y_reparacion()
    medico.autodiagnostico_y_reparacion()

    assert llamadas["veces"] == 1, "No debería repetir la misma reparación dentro de las 24h"


def test_timeout_smart_no_genera_falsa_alarma_critica(monkeypatch):
    """
    Bug real detectado en producción: Get-PhysicalDisk a veces tarda
    más de lo esperado y el chequeo SMART hace timeout. Antes, eso
    hacía que health_status quedara en 'desconocido', y el código
    interpretaba 'desconocido' como 'no está sano' -> alerta crítica
    falsa de "tu disco puede estar fallando, haz un backup ahora"
    cuando en realidad Ada simplemente no pudo consultarlo esa vez.
    """
    import medico
    import subprocess as sp

    def timeout_falso(*args, **kwargs):
        raise sp.TimeoutExpired(cmd="powershell", timeout=20)

    monkeypatch.setattr(sp, "run", timeout_falso)

    class DiscoConEspacioDeSobra:
        free = 200 * (1024 ** 3)
        total = 500 * (1024 ** 3)
        percent = 60.0

    monkeypatch.setattr(medico.psutil, "disk_usage", lambda path: DiscoConEspacioDeSobra())

    resultado = medico.salud_ssd_completa()

    assert resultado["alerta"] is False, \
        "Un timeout de SMART no debería disparar una alerta crítica"
    assert "fallo inminente" not in resultado["voz"], \
        "No debería sonar como si el disco estuviera fallando de verdad"
    assert "no pude verificar" in resultado["voz"].lower()


def test_nucleo_desbalanceado_identifica_al_culpable(monkeypatch):
    """
    Un núcleo saturado mientras el resto está tranquilo debe leerse
    como 'un proceso acaparando un núcleo', no como carga real del
    sistema — y debe intentar identificar cuál proceso es.
    """
    import medico

    monkeypatch.setattr(medico.psutil, "cpu_percent",
                         lambda interval=1, percpu=False: [98, 12, 15, 10] if percpu else 34)

    import nucleo_procesos
    monkeypatch.setattr(nucleo_procesos, "listar_procesos", lambda attrs: [
        {"name": "proceso_raro.exe", "cpu_percent": 95.0},
        {"name": "explorer.exe", "cpu_percent": 2.0},
    ])

    resultado = medico.presion_cpu_nucleos()
    assert resultado["estado"] == "desbalanceado"
    assert resultado["proceso_culpable"] == "proceso_raro.exe"
    assert "no carga real" in resultado["voz"]


def test_todos_los_nucleos_altos_es_carga_real_no_un_culpable(monkeypatch):
    """Cuando TODOS los núcleos están altos y parejos, es carga real
    del sistema — no se debe señalar a un solo proceso."""
    import medico

    monkeypatch.setattr(medico.psutil, "cpu_percent",
                         lambda interval=1, percpu=False: [92, 95, 91, 96] if percpu else 93)

    resultado = medico.presion_cpu_nucleos()
    assert resultado["estado"] == "saturado"
    assert "carga real" in resultado["voz"]


def test_nucleos_tranquilos_no_genera_alerta(monkeypatch):
    import medico

    monkeypatch.setattr(medico.psutil, "cpu_percent",
                         lambda interval=1, percpu=False: [10, 15, 8, 12] if percpu else 11)

    resultado = medico.presion_cpu_nucleos()
    assert resultado["estado"] == "saludable"
    assert resultado["alerta"] is False


def test_predictor_detecta_tendencia_de_cpu_al_alza(db_temporal):
    """
    Antes predecir_fallos() solo miraba disco y RAM — el dato de CPU
    se guardaba pero nadie lo analizaba para tendencias. Esta prueba
    confirma que ahora sí avisa cuando el uso promedio de CPU viene
    subiendo con el tiempo.
    """
    import medico
    import sqlite3
    from datetime import datetime, timedelta

    memoria = db_temporal
    ahora = datetime.now()
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    for i in range(7):
        t = ahora - timedelta(days=i)
        cpu_de_ese_dia = 20 + (6 - i) * 8  # sube de 20% a 68% en la semana
        cur.execute(
            "INSERT INTO historial_medico (fecha_hora, fecha, ram_libre_gb, ram_uso_pct, cpu_pct, disco_libre_gb, procesos_activos) "
            "VALUES (?,?,?,?,?,?,?)",
            (t.strftime("%Y-%m-%d %H:%M:%S.%f"), t.strftime("%Y-%m-%d"), 5.0, 50, cpu_de_ese_dia, 60, 150)
        )
    con.commit()
    con.close()

    predicciones = medico.predecir_fallos()
    tipos = [p["tipo"] for p in predicciones]
    assert "cpu" in tipos, "Debería detectar la tendencia de CPU al alza"


def test_bateria_y_drivers_llegan_al_resumen_que_ve_groq(db_temporal, monkeypatch):
    """
    Conectar batería y drivers al médico autónomo: el mismo
    tratamiento que ya tiene CPU — se leen una vez por ciclo y su
    texto entra al resumen que se manda a Groq. Ninguno de los dos
    debería disparar una reparación automática nueva (no hay ninguna
    en la lista blanca para esto).
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])
    monkeypatch.setattr(
        medico, "_leer_bateria_y_drivers",
        lambda: (
            {"estado": "degradada", "salud_pct": 55, "voz": "Alerta. Mi batería está degradada."},
            {"total": 40, "no_firmados": 1, "estado": "riesgo", "voz": "Encontré 1 driver sin firma."},
        )
    )

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resumen_capturado = {}

    def capturar_resumen(resumen, historial_por_accion=None, componente=None):
        resumen_capturado["texto"] = resumen
        return {"plan": [], "razon": ""}

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", capturar_resumen)

    medico.autodiagnostico_y_reparacion()

    # El triage nuevo ya no repite el "voz" original completo -- usa
    # el "detalle" corto y con números de puntuacion.listar_anomalias(),
    # que para batería degradada incluye el % real y para drivers la
    # cantidad sin firma.
    assert "batería degradada al 55%" in resumen_capturado["texto"].lower()
    assert "sin firma digital" in resumen_capturado["texto"].lower()


def test_diagnostico_completo_incluye_bateria_y_drivers(monkeypatch):
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])
    monkeypatch.setattr(
        medico, "_leer_bateria_y_drivers",
        lambda: (
            {"estado": "excelente", "salud_pct": 92, "voz": "Mi batería está al 92 por ciento."},
            {"total": 40, "no_firmados": 0, "estado": "saludable", "voz": "Todos los drivers firmados."},
        )
    )

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.diagnostico_completo()

    assert "92 por ciento" in resultado
    assert "drivers firmados" in resultado


def test_predictor_incluye_fugas_de_memoria_por_proceso(db_temporal):
    """
    Memoria por proceso a largo plazo: si memoria.detectar_fugas_memoria
    encuentra un proceso con crecimiento sostenido, predecir_fallos()
    debería incluirlo como una predicción más -- mismo tratamiento
    que ya reciben disco/RAM/CPU, y por lo tanto entra también a la
    severidad y al resumen que ve Groq sin necesitar cableado extra.
    """
    import medico
    import sqlite3
    from datetime import datetime, timedelta

    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    ahora = datetime.now()
    for i, v in enumerate([4.0, 7.0, 11.0, 16.0]):
        fecha = (ahora - timedelta(days=(4 - i))).strftime("%Y-%m-%d %H:%M")
        cur.execute(
            "INSERT INTO memoria_por_proceso (nombre, fecha, memoria_pct) VALUES (?, ?, ?)",
            ("app_con_fuga.exe", fecha, v)
        )
    con.commit()
    con.close()

    predicciones = medico.predecir_fallos()
    tipos = [p["tipo"] for p in predicciones]
    assert "fuga_memoria" in tipos

    fuga = next(p for p in predicciones if p["tipo"] == "fuga_memoria")
    assert fuga["urgencia"] == "alta"  # llegó a 16%, por encima del umbral de urgencia alta
    assert "app_con_fuga.exe" in fuga["voz"]


def test_decision_local_confiable_ejecuta_sin_llamar_a_groq(db_temporal, monkeypatch):
    """
    El objetivo final del aprendizaje: cuando Ada ya tiene evidencia
    fuerte y repetida de qué acción funciona para un componente, debe
    poder decidir sola y NUNCA llamar a Groq -- ni gastar la llamada,
    ni depender de que responda bien.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import auto_reparador
    ejecutado = {"veces": 0}

    def limpiar_fake():
        ejecutado["veces"] += 1
        return "Limpieza completada y VERIFICADA."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"limpiar_winsxs": limpiar_fake})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    memoria = db_temporal
    # 8 éxitos previos para el componente "ssd" -- suficiente
    # evidencia real para que Ada confíe sin preguntarle a Groq.
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente", lambda accion, horas=24: False)

    llamadas_a_groq = {"veces": 0}

    import ia
    def groq_no_deberia_llamarse(resumen, historial_por_accion=None, componente=None):
        llamadas_a_groq["veces"] += 1
        return {"plan": [], "razon": ""}
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", groq_no_deberia_llamarse)

    resultado = medico.autodiagnostico_y_reparacion()

    assert llamadas_a_groq["veces"] == 0, "No debería haber llamado a Groq -- ya tenía confianza local"
    assert ejecutado["veces"] == 1
    assert "sin Groq" in resultado


def test_medico_deja_registro_en_el_log_cuando_ejecuta(db_temporal, monkeypatch, caplog):
    """
    El hallazgo real fue que medico.py no escribía nada al log --
    ada_log.txt no mostraba ningún rastro de lo que el médico
    decidía o ejecutaba. Este test confirma que ahora sí queda
    registrado, para poder auditarlo después.
    """
    import logging
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_cpu_nucleos", lambda: {"voz": "CPU ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import auto_reparador
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS",
                         {"limpiar_winsxs": lambda: "Limpieza completada y VERIFICADA."})
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "espacio bajo"}]
    })

    with caplog.at_level(logging.INFO):
        medico.autodiagnostico_y_reparacion()

    mensajes = " ".join(r.message for r in caplog.records)
    assert "[MÉDICO]" in mensajes
    assert "limpiar_winsxs" in mensajes


def test_verificacion_confirma_que_se_resolvio_no_dispara_plan_b(db_temporal, monkeypatch):
    """
    Si tras ejecutar la acción principal el sensor real muestra que
    el problema ya se resolvió, no debe ejecutarse ninguna
    alternativa, y el mensaje debe reflejar la verificación positiva.
    """
    import medico

    # presion_ram cambia de estado entre la primera lectura (dispara
    # el ciclo, fija componente_dominante="ram") y la segunda lectura
    # (verificación post-ejecución) -- simula que la reparación sí
    # funcionó.
    llamadas = {"ram": 0}
    def ram_fake():
        llamadas["ram"] += 1
        if llamadas["ram"] == 1:
            return {"voz": "RAM alta", "estado": "alta"}
        return {"voz": "RAM ok", "estado": "saludable"}

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", ram_fake)
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{
            "accion": "desactivar_servicios_basura", "riesgo": "bajo", "razon": "RAM alta",
            "alternativa": {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "plan B"},
        }]
    })

    import auto_reparador
    plan_b_ejecutado = []
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "desactivar_servicios_basura": lambda: "Servicios desactivados.",
        "limpiar_cache_iconos": lambda: (plan_b_ejecutado.append(True), "Caché limpiada.")[1],
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert plan_b_ejecutado == [], "no debe ejecutarse el plan B si el problema ya se resolvió"
    assert "ya se resolvió" in resultado


def test_verificacion_detecta_que_sigue_mal_y_ejecuta_plan_b(db_temporal, monkeypatch):
    """
    Si tras ejecutar la acción principal el sensor real muestra que
    el problema SIGUE presente, y la acción trajo una alternativa
    válida, esa alternativa debe ejecutarse en el mismo ciclo.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "sigue mal", "estado": "alta"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{
            "accion": "desactivar_servicios_basura", "riesgo": "bajo", "razon": "RAM alta",
            "alternativa": {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "plan B"},
        }]
    })

    import auto_reparador
    plan_b_ejecutado = []
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "desactivar_servicios_basura": lambda: "Servicios desactivados.",
        "limpiar_cache_iconos": lambda: (plan_b_ejecutado.append(True), "Caché limpiada.")[1],
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert plan_b_ejecutado == [True], "el plan B debe ejecutarse cuando el problema persiste"
    assert "Caché limpiada" in resultado
    assert "plan B" in resultado


def test_plan_b_no_se_ejecuta_si_esta_en_cooldown(db_temporal, monkeypatch):
    """El plan B respeta el mismo cooldown de 24h que cualquier acción."""
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "sigue mal", "estado": "alta"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{
            "accion": "desactivar_servicios_basura", "riesgo": "bajo", "razon": "RAM alta",
            "alternativa": {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "plan B"},
        }]
    })

    import auto_reparador
    plan_b_ejecutado = []
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "desactivar_servicios_basura": lambda: "Servicios desactivados.",
        "limpiar_cache_iconos": lambda: (plan_b_ejecutado.append(True), "Caché limpiada.")[1],
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import memoria
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente",
                         lambda accion, horas=24: accion == "limpiar_cache_iconos")

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert plan_b_ejecutado == [], "el plan B en cooldown no debe ejecutarse"


def test_componente_no_verificable_no_agrega_texto_de_verificacion(db_temporal, monkeypatch):
    """
    Para componentes sin sensor directo (ej. batería), no se debe
    afirmar nada sobre si el problema se resolvió o no -- no hay
    evidencia real para decirlo.
    """
    import medico

    resultado = medico._problema_sigue_presente("bateria")
    assert resultado is None


def test_estado_ambiguo_desconocido_no_cuenta_como_problema_persistente(db_temporal, monkeypatch):
    """
    Si el sensor no pudo leer esta vez (estado 'desconocido'), eso no
    debe interpretarse como 'el problema sigue' -- es 'no sé', no 'mal'.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "no pude leer", "estado": "desconocido"})
    assert medico._problema_sigue_presente("ssd") is None



    """
    Planificador multi-acción: si Groq detecta dos problemas
    independientes en el mismo ciclo (SSD lleno + RAM bajo presión)
    y propone una acción de riesgo bajo para cada uno, las dos deben
    ejecutarse en el mismo ciclo -- no solo la primera.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [
            {"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "SSD lleno"},
            {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "cache corrupta"},
        ]
    })

    import auto_reparador
    ejecutadas = []

    def winsxs_fake():
        ejecutadas.append("limpiar_winsxs")
        return "WinSxS limpiado."

    def iconos_fake():
        ejecutadas.append("limpiar_cache_iconos")
        return "Caché reconstruida."

    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "limpiar_winsxs": winsxs_fake,
        "limpiar_cache_iconos": iconos_fake,
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutadas == ["limpiar_winsxs", "limpiar_cache_iconos"], \
        "Las dos acciones deben ejecutarse, en el orden que propuso Groq"
    assert "WinSxS limpiado" in resultado
    assert "Caché reconstruida" in resultado


def test_plan_segunda_accion_no_se_cancela_si_la_primera_queda_bloqueada(db_temporal, monkeypatch):
    """
    Si la primera acción del plan queda bloqueada (ej. ya se ejecutó
    en las últimas 24h), la segunda igual debe evaluarse y ejecutarse
    por su cuenta -- un bloqueo no debe cancelar en cadena el resto
    del plan.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [
            {"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "SSD lleno"},
            {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "cache corrupta"},
        ]
    })

    import auto_reparador
    ejecutadas = []
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "limpiar_winsxs": lambda: (ejecutadas.append("limpiar_winsxs"), "WinSxS limpiado.")[1],
        "limpiar_cache_iconos": lambda: (ejecutadas.append("limpiar_cache_iconos"), "Caché reconstruida.")[1],
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    import memoria
    # limpiar_winsxs "ya se ejecutó" hace poco -- queda en cooldown.
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente",
                         lambda accion, horas=24: accion == "limpiar_winsxs")

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutadas == ["limpiar_cache_iconos"], \
        "limpiar_winsxs debe quedar bloqueada por cooldown, pero la segunda igual debe ejecutarse"
    assert "Caché reconstruida" in resultado
    assert "WinSxS limpiado" not in resultado


def test_alternativa_se_valida_y_solo_aplica_al_primer_item():
    """
    La alternativa (plan B) solo debe conservarse para la primera
    acción del plan, y solo si es válida y distinta de la principal.
    Una alternativa igual a la acción principal, inventada, o puesta
    en el segundo ítem del plan, debe descartarse silenciosamente.
    """
    import ia

    plan_crudo = {
        "razonamiento": "test",
        "plan": [
            {"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "a",
             "alternativa": {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "plan B valido"}},
            {"accion": "desactivar_servicios_basura", "riesgo": "medio", "razon": "b",
             "alternativa": {"accion": "reparar_red", "riesgo": "alto", "razon": "no deberia guardarse"}},
        ],
    }

    class FakeChoice:
        def __init__(self, texto):
            self.message = type("M", (), {"content": texto})()

    class FakeResponse:
        def __init__(self, texto):
            self.choices = [FakeChoice(texto)]

    class FakeCompletions:
        def create(self, **kwargs):
            import json
            return FakeResponse(json.dumps(plan_crudo))

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()
        def with_options(self, **kwargs):
            # ia.py real llama groq_client.with_options(timeout=...)
            # antes de .chat.completions.create() (parte del fallback
            # 70B->8B->heurística) -- el fake necesita responder a eso
            # igual que el cliente real, si no cae directo a heurística.
            return self

    ia.groq_client = FakeClient()
    ia.GROQ_ACTIVO = True

    resultado = ia.diagnosticar_y_recomendar("resumen de prueba")
    plan = resultado["plan"]

    assert "alternativa" in plan[0]
    assert plan[0]["alternativa"]["accion"] == "limpiar_cache_iconos"
    assert "alternativa" not in plan[1], "la segunda acción del plan nunca debe traer alternativa"


def test_alternativa_igual_a_la_principal_se_descarta():
    """Una alternativa idéntica a la acción principal no tiene sentido -- se descarta."""
    import ia

    plan_crudo = {
        "razonamiento": "test",
        "plan": [
            {"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "a",
             "alternativa": {"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "misma accion"}},
        ],
    }

    class FakeChoice:
        def __init__(self, texto):
            self.message = type("M", (), {"content": texto})()

    class FakeResponse:
        def __init__(self, texto):
            self.choices = [FakeChoice(texto)]

    class FakeCompletions:
        def create(self, **kwargs):
            import json
            return FakeResponse(json.dumps(plan_crudo))

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()
        def with_options(self, **kwargs):
            # ia.py real llama groq_client.with_options(timeout=...)
            # antes de .chat.completions.create() (parte del fallback
            # 70B->8B->heurística) -- el fake necesita responder a eso
            # igual que el cliente real, si no cae directo a heurística.
            return self

    ia.groq_client = FakeClient()
    ia.GROQ_ACTIVO = True

    resultado = ia.diagnosticar_y_recomendar("resumen de prueba")
    assert "alternativa" not in resultado["plan"][0]
    """
    Aunque Groq devuelva más de 2 acciones en el plan (por error de
    parseo o por no seguir la instrucción), Ada nunca debe ejecutar
    más de 2 por ciclo -- el límite lo controla el código, no el
    modelo. También verifica que se descarten duplicados y acciones
    fuera de la lista blanca.
    """
    import ia

    plan_crudo = {
        "razonamiento": "test",
        "plan": [
            {"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "a"},
            {"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "duplicada"},
            {"accion": "formatear_disco_completo", "riesgo": "alto", "razon": "inventada"},
            {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "b"},
            {"accion": "reparar_red", "riesgo": "alto", "razon": "c"},
        ],
    }

    class FakeChoice:
        def __init__(self, texto):
            self.message = type("M", (), {"content": texto})()

    class FakeResponse:
        def __init__(self, texto):
            self.choices = [FakeChoice(texto)]

    class FakeCompletions:
        def create(self, **kwargs):
            import json
            return FakeResponse(json.dumps(plan_crudo))

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()
        def with_options(self, **kwargs):
            # ia.py real llama groq_client.with_options(timeout=...)
            # antes de .chat.completions.create() (parte del fallback
            # 70B->8B->heurística) -- el fake necesita responder a eso
            # igual que el cliente real, si no cae directo a heurística.
            return self

    ia.groq_client = FakeClient()
    ia.GROQ_ACTIVO = True

    resultado = ia.diagnosticar_y_recomendar("resumen de prueba")
    acciones = [item["accion"] for item in resultado["plan"]]

    assert len(acciones) == 2, "nunca más de 2 acciones, sin importar cuántas devuelva Groq"
    assert acciones == ["limpiar_winsxs", "limpiar_cache_iconos"], \
        "debe descartar el duplicado y la acción inventada, y respetar el orden de las válidas"


def test_patron_temporal_llega_al_predictor_de_fallos(monkeypatch):
    """
    Un patrón detectado por detectar_patrones_temporales() debe
    aparecer como predicción en predecir_fallos() -- mismo cableado
    automático que ya tienen las fugas de memoria, sin caso especial
    en puntuacion.py (entra como cualquier otra predicción con
    urgencia, y de ahí a la severidad y al resumen que ve Groq).
    """
    import medico

    monkeypatch.setattr("memoria.obtener_promedios_diarios", lambda dias=7: [])
    monkeypatch.setattr("memoria.detectar_fugas_memoria", lambda dias=14: [])
    monkeypatch.setattr("memoria.detectar_patrones_temporales", lambda dias_atras=30: [{
        "componente": "ram", "tipo": "franja_horaria", "detalle": "tarde",
        "casos": 5, "total": 6, "porcentaje": 83.3,
        "voz": "Noto un patrón: 5 de los últimos 6 problemas de ram (83.3%) ocurrieron de tarde.",
    }])

    predicciones = medico.predecir_fallos()

    patrones_temporales = [p for p in predicciones if p["tipo"] == "patron_temporal"]
    assert len(patrones_temporales) == 1
    assert "tarde" in patrones_temporales[0]["voz"]
    assert patrones_temporales[0]["urgencia"] == "media"


def test_mensaje_final_cita_evidencia_real_no_solo_la_razon_de_groq(db_temporal, monkeypatch):
    """
    Cuando Ada ejecuta una acción recomendada por Groq, el mensaje
    final debe citar la evidencia numérica que ella misma tiene
    (intentos/éxitos para este componente) -- no solo repetir la
    frase corta que escribió Groq. "Por qué elegí esto" necesita
    números propios, no solo la palabra ajena.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "SSD lleno"}]
    })

    import auto_reparador
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "limpiar_winsxs": lambda: "WinSxS limpiado.",
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    memoria = db_temporal
    for _ in range(6):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente", lambda accion, horas=24: False)

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert "5/5" in resultado, \
        "debe citar el historial real (éxitos/intentos, limitado a las últimas 5), no solo la razón de Groq"
    assert "este mismo tipo de problema" in resultado


def test_circuito_de_seguridad_bloquea_tras_fallos_consecutivos(db_temporal, monkeypatch):
    """
    Si una acción ya lleva REPARACION_LIMITE_FALLOS_CONSECUTIVOS
    fallos seguidos para este componente, Ada no debe volver a
    intentarla sola -- ni aunque Groq la siga recomendando y el
    cooldown de 24h ya haya pasado. Este es el límite duro contra
    bucles infinitos, no uno aprendido.
    """
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "SSD lleno"}]
    })

    import auto_reparador
    ejecutado = {"veces": 0}
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "limpiar_winsxs": lambda: (ejecutado.__setitem__("veces", ejecutado["veces"] + 1), "ok")[1],
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    memoria = db_temporal
    for _ in range(3):  # 3 fallos seguidos = el límite por defecto
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Error: fallo la limpieza.", componente="ssd",
        )
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente", lambda accion, horas=24: False)

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutado["veces"] == 0, "no debe ejecutar la acción con el circuito de seguridad activado"
    assert "3 fallos seguidos" in resultado


def test_circuito_de_seguridad_no_bloquea_si_el_ultimo_fue_exito(db_temporal, monkeypatch):
    """Con fallos previos pero el más reciente fue éxito, el circuito no debe
    bloquear -- la racha se rompió."""
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "disco ok", "estado": "advertencia"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "RAM ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{"accion": "limpiar_winsxs", "riesgo": "bajo", "razon": "SSD lleno"}]
    })

    import auto_reparador
    ejecutado = {"veces": 0}
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "limpiar_winsxs": lambda: (ejecutado.__setitem__("veces", ejecutado["veces"] + 1), "ok")[1],
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    memoria = db_temporal
    memoria.registrar_decision_medico_ia(  # 1 fallo previo
        "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
        resultado="Error: fallo la limpieza.", componente="ssd",
    )
    memoria.registrar_decision_medico_ia(  # el más reciente fue éxito -- rompe la racha
        "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
        resultado="Limpieza completada y VERIFICADA.", componente="ssd",
    )
    # Con solo 2 intentos totales (por debajo de
    # REPARACION_MINIMO_INTENTOS_PARA_EVALUAR=3), el chequeo de tasa de
    # éxito no opina todavía -- así este test aísla específicamente el
    # circuito de seguridad, sin cruzar ese otro umbral distinto.
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente", lambda accion, horas=24: False)

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert ejecutado["veces"] == 1, "sí debe ejecutarse -- la racha de fallos se rompió con el último éxito"


def test_circuito_de_seguridad_aplica_tambien_al_plan_b(db_temporal, monkeypatch):
    """El plan B no debe estar exento del circuito de seguridad -- si ya
    lleva demasiados fallos seguidos, tampoco se ejecuta solo."""
    import medico

    monkeypatch.setattr(medico, "salud_ssd_completa", lambda: {"voz": "ok", "estado": "saludable"})
    monkeypatch.setattr(medico, "presion_ram", lambda: {"voz": "sigue mal", "estado": "alta"})
    monkeypatch.setattr(medico, "leer_eventos_criticos", lambda horas=24: [])
    monkeypatch.setattr(medico, "resumir_eventos", lambda eventos: "sin errores")
    monkeypatch.setattr(medico, "correlacionar_eventos", lambda eventos: "")
    monkeypatch.setattr(medico, "predecir_fallos", lambda: [])

    import ia
    monkeypatch.setattr(ia, "diagnosticar_y_recomendar", lambda resumen, historial_por_accion=None, componente=None: {
        "plan": [{
            "accion": "desactivar_servicios_basura", "riesgo": "bajo", "razon": "RAM alta",
            "alternativa": {"accion": "limpiar_cache_iconos", "riesgo": "bajo", "razon": "plan B"},
        }]
    })

    import auto_reparador
    plan_b_ejecutado = []
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_AUTOMATICAS", {
        "desactivar_servicios_basura": lambda: "Servicios desactivados.",
        "limpiar_cache_iconos": lambda: (plan_b_ejecutado.append(True), "ok")[1],
    })
    monkeypatch.setattr(auto_reparador, "ACCIONES_MEDICO_REQUIEREN_CONFIRMACION", {})

    memoria = db_temporal
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_cache_iconos", "bajo", "r", ejecutada=True,
            resultado="Error: fallo.", componente="ram",
        )
    monkeypatch.setattr(memoria, "accion_ejecutada_recientemente", lambda accion, horas=24: False)

    import sistema
    monkeypatch.setattr(sistema, "indice_salud", lambda: {"voz": "salud buena"}, raising=False)

    resultado = medico.autodiagnostico_y_reparacion()

    assert plan_b_ejecutado == [], "el plan B con circuito activado no debe ejecutarse"
    assert "no lo intento más" in resultado
