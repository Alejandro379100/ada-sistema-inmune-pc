# ==========================================
#   test_memoria.py
#   Prueba el "cerebro" de Ada: historial médico,
#   promedios diarios, migración de bases de datos
#   viejas, cooldown de decisiones, y el límite
#   duro de tamaño en disco.
# ==========================================

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta


def test_historial_medico_guarda_varias_muestras_por_dia(db_temporal):
    """
    Antes de este fix, 'fecha' era la clave única y con INSERT OR
    IGNORE solo la primera lectura del día quedaba guardada. Esta
    prueba confirma que ahora SÍ se guardan varias muestras del
    mismo día y se promedian bien.
    """
    memoria = db_temporal
    for i in range(5):
        memoria.registrar_historial_medico(
            ram_libre_gb=6.0 - i * 0.1,
            ram_uso_pct=50 + i,
            cpu_pct=20 + i,
            disco_libre_gb=40 - i * 0.2,
            procesos_activos=150 + i,
        )

    promedios = memoria.obtener_promedios_diarios(14)
    assert len(promedios) == 1, "Debería quedar un solo día agrupado"
    fecha, ram_prom, disco_prom, cpu_prom, muestras = promedios[0]
    assert muestras == 5, "Debería haber guardado las 5 lecturas, no solo la primera"


def test_migracion_de_base_de_datos_vieja(db_temporal, monkeypatch):
    """
    Simula exactamente el bug real que ocurrió: una instalación de
    Ada ya existente, con el esquema viejo de historial_medico (sin
    la columna fecha_hora). inicializar_db() no debe reventar, y las
    filas viejas deben sobrevivir la migración.
    """
    import memoria

    tmp_path = tempfile.mktemp(suffix=".db")
    con = sqlite3.connect(tmp_path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE historial_medico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT UNIQUE,
            ram_libre_gb REAL, ram_uso_pct REAL, cpu_pct REAL,
            disco_libre_gb REAL, procesos_activos INTEGER
        )
    """)
    cur.executemany(
        "INSERT INTO historial_medico (fecha, ram_libre_gb, ram_uso_pct, cpu_pct, disco_libre_gb, procesos_activos) "
        "VALUES (?,?,?,?,?,?)",
        [("2026-07-01", 5.0, 55, 20, 80, 150),
         ("2026-07-02", 4.8, 57, 22, 79, 152)]
    )
    con.commit()
    con.close()

    monkeypatch.setattr(memoria, "DB_PATH", tmp_path)
    memoria.inicializar_db()  # no debería lanzar ninguna excepción

    con = sqlite3.connect(tmp_path)
    cur = con.cursor()
    cur.execute("SELECT fecha_hora, fecha FROM historial_medico ORDER BY fecha")
    filas = cur.fetchall()
    con.close()
    os.remove(tmp_path)

    assert len(filas) == 2, "Las filas viejas no deberían perderse en la migración"
    assert all(f[0] is not None for f in filas), "fecha_hora debería quedar rellenada"


def test_cooldown_evita_repetir_la_misma_decision(db_temporal):
    """
    El bug real que viste en tu terminal: la misma reparación se
    ejecutaba cada 3 horas para el mismo problema viejo. Esta prueba
    confirma que accion_ejecutada_recientemente() detecta que ya se
    hizo y evita repetirla.
    """
    memoria = db_temporal
    assert memoria.accion_ejecutada_recientemente("reparar_archivos_sistema", horas=24) is False

    memoria.registrar_decision_medico_ia(
        "reparar_archivos_sistema", "medio", "errores en registro",
        ejecutada=True, resultado="reparado"
    )

    assert memoria.accion_ejecutada_recientemente("reparar_archivos_sistema", horas=24) is True
    # Una acción DISTINTA no debería verse afectada por el cooldown de otra
    assert memoria.accion_ejecutada_recientemente("limpiar_winsxs", horas=24) is False


def test_inferir_exito_reconoce_verificacion_real():
    import memoria
    exito_txt = "Reparación completada y VERIFICADA. Windows encontró y corrigió archivos dañados."
    assert memoria._inferir_exito_desde_resultado(exito_txt, ejecutada=True) == 1


def test_inferir_exito_reconoce_fracaso():
    import memoria
    fracaso_txt = "No pude ejecutar la reparación: timeout"
    assert memoria._inferir_exito_desde_resultado(fracaso_txt, ejecutada=True) == 0


def test_inferir_exito_es_none_si_no_se_ejecuto():
    import memoria
    assert memoria._inferir_exito_desde_resultado("cualquier texto", ejecutada=False) is None


def test_inferir_exito_es_none_si_es_ambiguo():
    import memoria
    texto_sin_marcas_conocidas = "Se hizo algo, no está claro el resultado."
    assert memoria._inferir_exito_desde_resultado(texto_sin_marcas_conocidas, ejecutada=True) is None


def test_tasa_exito_reparacion_sin_historial(db_temporal):
    memoria = db_temporal
    tasa = memoria.tasa_exito_reparacion("reparar_archivos_sistema")
    assert tasa == {"intentos": 0, "exitos": 0, "porcentaje": None}


def test_tasa_exito_reparacion_cuenta_solo_lo_ejecutado_y_no_ambiguo(db_temporal):
    """
    Aprendizaje de reparaciones: la tasa de éxito solo debe contar
    intentos EJECUTADOS con un resultado claro. Las recomendaciones
    sin ejecutar (riesgo alto) y los resultados ambiguos no deberían
    ensuciar el número.
    """
    memoria = db_temporal

    # 1 éxito real
    memoria.registrar_decision_medico_ia(
        "reparar_archivos_sistema", "medio", "razon", ejecutada=True,
        resultado="Reparación completada y VERIFICADA. Todo bien."
    )
    # 1 fracaso real
    memoria.registrar_decision_medico_ia(
        "reparar_archivos_sistema", "medio", "razon", ejecutada=True,
        resultado="No pude ejecutar la reparación: error de permisos."
    )
    # Solo recomendada, nunca ejecutada -> no debería contar
    memoria.registrar_decision_medico_ia(
        "reparar_archivos_sistema", "alto", "razon", ejecutada=False,
        resultado="Pendiente de confirmación del usuario"
    )
    # Ejecutada pero con texto ambiguo -> tampoco debería contar
    memoria.registrar_decision_medico_ia(
        "reparar_archivos_sistema", "medio", "razon", ejecutada=True,
        resultado="Se corrió el comando."
    )

    tasa = memoria.tasa_exito_reparacion("reparar_archivos_sistema", ultimas=5)
    assert tasa["intentos"] == 2, "Solo cuentan los 2 casos con resultado claro"
    assert tasa["exitos"] == 1
    assert tasa["porcentaje"] == 50.0


def test_tasa_exito_reparacion_respeta_el_limite_de_ultimas(db_temporal):
    memoria = db_temporal
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "razon", ejecutada=True,
            resultado="Limpieza de componentes Windows completada. Liberé 1.2 gigabytes de verdad."
        )
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "razon", ejecutada=True,
            resultado="No pude limpiar WinSxS: acceso denegado."
        )

    tasa = memoria.tasa_exito_reparacion("limpiar_winsxs", ultimas=2)
    # Solo mira las últimas 2 (las más recientes son los 3 fracasos)
    assert tasa["intentos"] == 2
    assert tasa["exitos"] == 0
    assert tasa["porcentaje"] == 0.0


def test_severidad_se_guarda_en_la_decision(db_temporal):
    memoria = db_temporal
    memoria.registrar_decision_medico_ia(
        "reparar_archivos_sistema", "medio", "razon", ejecutada=True,
        resultado="Reparación completada y VERIFICADA.", severidad="alto"
    )
    filas = memoria.historial_decisiones_medico_ia(1)
    fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito = filas[0]
    assert severidad == "alto"
    assert exito == 1


def test_persistencia_primera_vez_no_confirma(db_temporal):
    """La primera vez que se ve una acción de riesgo medio, todavía
    no hay nada que confirmar — no debería ejecutarse a ciegas."""
    memoria = db_temporal
    assert memoria.necesita_confirmacion_por_persistencia("desactivar_servicios_basura") is False


def test_persistencia_se_confirma_en_el_segundo_ciclo(db_temporal):
    memoria = db_temporal
    memoria.registrar_decision_medico_ia(
        "desactivar_servicios_basura", "medio", "RAM alta", ejecutada=False,
        resultado="Pendiente confirmación por persistencia — si el problema sigue en el próximo diagnóstico, la ejecuto sola."
    )
    assert memoria.necesita_confirmacion_por_persistencia("desactivar_servicios_basura") is True


def test_persistencia_no_confirma_si_riesgo_no_era_medio(db_temporal):
    """Solo el mecanismo de riesgo medio deja rastro de 'pendiente' —
    si la última decisión fue de otro tipo, no cuenta como confirmación."""
    memoria = db_temporal
    memoria.registrar_decision_medico_ia(
        "reparar_red", "alto", "sin internet", ejecutada=False,
        resultado="Pendiente de confirmación del usuario"
    )
    assert memoria.necesita_confirmacion_por_persistencia("reparar_red") is False


def test_persistencia_no_confirma_si_ya_se_ejecuto_antes(db_temporal):
    memoria = db_temporal
    memoria.registrar_decision_medico_ia(
        "limpiar_winsxs", "bajo", "disco lleno", ejecutada=True,
        resultado="Limpieza de componentes Windows completada. Liberé 1 gigabyte de verdad."
    )
    assert memoria.necesita_confirmacion_por_persistencia("limpiar_winsxs") is False


def test_persistencia_expira_fuera_de_la_ventana(db_temporal):
    """Si la 'primera vez vista' quedó demasiado atrás en el tiempo,
    no debería confirmarse solo por antigüedad — se trata como una
    observación nueva."""
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    fecha_vieja = (datetime.now() - timedelta(hours=100)).strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO decisiones_medico_ia (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito)
        VALUES (?, 'desactivar_servicios_basura', 'medio', 'razon', 0, 'pendiente', NULL, NULL)
    """, (fecha_vieja,))
    con.commit()
    con.close()

    assert memoria.necesita_confirmacion_por_persistencia("desactivar_servicios_basura", horas=48) is False


# ==========================================
#   Memoria por proceso a largo plazo
#   registrar_muestra_proceso() / detectar_fugas_memoria()
# ==========================================

def test_primera_muestra_de_un_proceso_siempre_se_guarda(db_temporal):
    memoria = db_temporal
    memoria.registrar_muestra_proceso("chrome.exe", 5.0)
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM memoria_por_proceso WHERE nombre = 'chrome.exe'")
    assert cur.fetchone()[0] == 1
    con.close()


def test_cambio_pequeno_no_genera_una_fila_nueva(db_temporal):
    """El corazón del diseño por deltas: si la memoria del proceso
    casi no cambió desde la última muestra guardada, no vale la pena
    guardar otra fila — así no se infla la base de datos."""
    memoria = db_temporal
    memoria.registrar_muestra_proceso("chrome.exe", 5.0)
    memoria.registrar_muestra_proceso("chrome.exe", 5.2)  # delta 0.2, por debajo del umbral (1.5)

    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM memoria_por_proceso WHERE nombre = 'chrome.exe'")
    assert cur.fetchone()[0] == 1, "Un cambio chico no debería generar una segunda fila"
    con.close()


def test_cambio_grande_si_genera_una_fila_nueva(db_temporal):
    memoria = db_temporal
    memoria.registrar_muestra_proceso("chrome.exe", 5.0)
    memoria.registrar_muestra_proceso("chrome.exe", 8.0)  # delta 3.0, supera el umbral

    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM memoria_por_proceso WHERE nombre = 'chrome.exe'")
    assert cur.fetchone()[0] == 2
    con.close()


def test_detectar_fugas_sin_historial_suficiente_no_reporta_nada(db_temporal):
    memoria = db_temporal
    memoria.registrar_muestra_proceso("chrome.exe", 5.0)
    memoria.registrar_muestra_proceso("chrome.exe", 8.0)  # solo 2 muestras, mínimo son 4

    assert memoria.detectar_fugas_memoria(dias=14) == []


def test_detectar_fuga_real_por_crecimiento_sostenido(db_temporal):
    """
    El caso central: un proceso que viene subiendo de a poco durante
    varias muestras, con crecimiento neto por encima del umbral,
    debería reportarse como posible fuga.
    """
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    ahora = datetime.now()
    valores = [4.0, 6.0, 8.5, 11.0]  # crecimiento neto: 7 puntos, todos dentro de 14 días
    for i, v in enumerate(valores):
        fecha = (ahora - timedelta(days=(len(valores) - i))).strftime("%Y-%m-%d %H:%M")
        cur.execute(
            "INSERT INTO memoria_por_proceso (nombre, fecha, memoria_pct) VALUES (?, ?, ?)",
            ("edge_actualizador.exe", fecha, v)
        )
    con.commit()
    con.close()

    fugas = memoria.detectar_fugas_memoria(dias=14)
    assert len(fugas) == 1
    assert fugas[0]["nombre"] == "edge_actualizador.exe"
    assert fugas[0]["memoria_inicial_pct"] == 4.0
    assert fugas[0]["memoria_actual_pct"] == 11.0


def test_crecimiento_menor_al_umbral_no_se_reporta(db_temporal):
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    ahora = datetime.now()
    valores = [4.0, 4.5, 5.0, 5.5]  # crecimiento neto: solo 1.5, por debajo del umbral de 3.0
    for i, v in enumerate(valores):
        fecha = (ahora - timedelta(days=(len(valores) - i))).strftime("%Y-%m-%d %H:%M")
        cur.execute(
            "INSERT INTO memoria_por_proceso (nombre, fecha, memoria_pct) VALUES (?, ?, ?)",
            ("proceso_estable.exe", fecha, v)
        )
    con.commit()
    con.close()

    assert memoria.detectar_fugas_memoria(dias=14) == []


def test_fugas_fuera_de_la_ventana_de_dias_no_cuentan(db_temporal):
    """Muestras viejas, de hace más de `dias`, no deberían contarse
    para la tendencia actual."""
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    fecha_vieja = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M")
    for v in [4.0, 6.0, 8.0, 11.0]:
        cur.execute(
            "INSERT INTO memoria_por_proceso (nombre, fecha, memoria_pct) VALUES (?, ?, ?)",
            ("proceso_viejo.exe", fecha_vieja, v)
        )
    con.commit()
    con.close()

    assert memoria.detectar_fugas_memoria(dias=14) == []


def test_limite_de_tamano_recorta_y_compacta(db_temporal, monkeypatch):
    """
    Red de seguridad final: si la base de datos supera DB_MAX_MB,
    debe recortar el historial más viejo y compactar con VACUUM —
    sin perder todos los datos.
    """
    import memoria
    import config

    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    ahora = datetime.now()
    for i in range(2000):
        t = ahora - timedelta(minutes=i)
        cur.execute(
            "INSERT INTO historial_medico (fecha_hora, fecha, ram_libre_gb, ram_uso_pct, cpu_pct, disco_libre_gb, procesos_activos) "
            "VALUES (?,?,?,?,?,?,?)",
            (t.strftime("%Y-%m-%d %H:%M:%S.%f"), t.strftime("%Y-%m-%d"), 4.0, 60, 30, 50, 180)
        )
    con.commit()
    con.close()

    tam_antes = os.path.getsize(memoria.DB_PATH) / (1024 * 1024)
    monkeypatch.setattr(config, "DB_MAX_MB", 0.01)  # forzar el límite para la prueba

    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    memoria._verificar_tamano_maximo(cur, con)
    con.close()

    tam_despues = os.path.getsize(memoria.DB_PATH) / (1024 * 1024)
    assert tam_despues < tam_antes, "Debería haber reducido el tamaño del archivo"

    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM historial_medico")
    restantes = cur.fetchone()[0]
    con.close()
    assert 0 < restantes < 2000, "No debería borrar TODO el historial, solo el 20% más viejo por pasada"


# ==========================================
#   decision_local_confiable()
#   El objetivo final: que Ada deje de
#   depender de Groq para lo que ya aprendió.
# ==========================================

def test_sin_historial_no_hay_confianza_local(db_temporal):
    memoria = db_temporal
    assert memoria.decision_local_confiable("ssd") is None


def test_pocos_intentos_no_alcanzan_para_decidir_sola(db_temporal):
    """Con menos intentos que el mínimo configurado, Ada todavía no
    debe animarse a saltarse a Groq, aunque todos hayan sido éxito."""
    memoria = db_temporal
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    assert memoria.decision_local_confiable("ssd", minimo_intentos=8, umbral_pct=90) is None


def test_suficientes_exitos_habilitan_la_decision_local(db_temporal):
    """Con suficiente evidencia y una tasa de éxito muy alta para el
    mismo componente, Ada puede decidir sola sin preguntarle a Groq."""
    memoria = db_temporal
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    resultado = memoria.decision_local_confiable("ssd", minimo_intentos=8, umbral_pct=90)
    assert resultado is not None
    assert resultado["accion"] == "limpiar_winsxs"
    assert resultado["porcentaje"] >= 90


def test_fracasos_recientes_bajan_la_confianza_local(db_temporal):
    """Si la acción empezó a fallar, la confianza local desaparece
    hasta que vuelva a ganársela -- mismo espíritu que
    tasa_exito_reparacion() para la red de seguridad de Groq."""
    memoria = db_temporal
    for _ in range(4):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    for _ in range(4):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Error: acceso denegado.", componente="ssd",
        )
    assert memoria.decision_local_confiable("ssd", minimo_intentos=8, umbral_pct=90) is None


def test_componente_distinto_no_hereda_confianza_de_otro(db_temporal):
    """La confianza aprendida para un componente (ssd) no debería
    aplicarse a un componente distinto (ram) que nunca se probó."""
    memoria = db_temporal
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    assert memoria.decision_local_confiable("ram") is None


def test_compara_dos_acciones_y_gana_la_de_mejor_tasa_aunque_no_sea_la_ultima(db_temporal):
    """
    Aprendizaje real: si dos acciones distintas se probaron para el
    mismo componente, Ada debe comparar sus tasas de éxito y quedarse
    con la mejor -- no con la última usada por pura recencia. Acá
    'limpiar_winsxs' tiene mejor historial pero 'reparar_archivos_sistema'
    fue la más reciente y salió mal; debe ganar limpiar_winsxs.
    """
    memoria = db_temporal
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "reparar_archivos_sistema", "bajo", "corrupcion", ejecutada=True,
            resultado="Error: fallo la reparacion.", componente="ssd",
        )

    resultado = memoria.decision_local_confiable("ssd", minimo_intentos=8, umbral_pct=90)
    assert resultado is not None
    assert resultado["accion"] == "limpiar_winsxs", \
        "debe ganar la de mejor tasa de éxito, no la más reciente"


def test_decision_local_explica_la_comparacion_con_numeros_reales(db_temporal):
    """
    Aprendizaje real de verdad no es solo "elegí bien" -- es poder
    explicar CON QUÉ NÚMEROS comparó. La razón debe mencionar el
    porcentaje del ganador Y el del segundo candidato, para que el
    usuario vea la evidencia real detrás de la decisión, no una
    afirmación sin sustento.
    """
    memoria = db_temporal
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "reparar_archivos_sistema", "bajo", "corrupcion", ejecutada=True,
            resultado="Error: fallo la reparacion.", componente="ssd",
        )

    resultado = memoria.decision_local_confiable("ssd", minimo_intentos=8, umbral_pct=90)
    assert "100" in resultado["razon"], "debe citar el porcentaje real del ganador"
    assert "reparar_archivos_sistema" in resultado["razon"], \
        "debe nombrar contra qué otra acción comparó"
    assert "0" in resultado["razon"], "debe citar el porcentaje real del que perdió"


def test_decision_local_sin_competencia_no_inventa_una_comparacion(db_temporal):
    """
    Si solo hay UNA acción con historial suficiente para este
    componente, la razón no debe inventar una comparación que nunca
    existió -- debe explicar la evidencia sola, sin mencionar un
    "segundo lugar" que no hubo.
    """
    memoria = db_temporal
    for _ in range(8):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "espacio bajo", ejecutada=True,
            resultado="Limpieza completada y VERIFICADA.", componente="ssd",
        )

    resultado = memoria.decision_local_confiable("ssd", minimo_intentos=8, umbral_pct=90)
    assert resultado is not None
    assert "mejor que" not in resultado["razon"], \
        "no debe afirmar una comparación cuando no hubo otro candidato"
    assert "100" in resultado["razon"]


def test_tasa_por_componente_separa_evidencia_de_tasa_global(db_temporal):
    """
    tasa_exito_reparacion_por_componente no debe mezclar ejecuciones
    de otros componentes -- una acción puede haber funcionado bien
    para 'ram' y mal para 'cpu', y esa diferencia se tiene que poder
    ver por separado.
    """
    memoria = db_temporal
    for _ in range(5):
        memoria.registrar_decision_medico_ia(
            "desactivar_servicios_basura", "bajo", "ram alta", ejecutada=True,
            resultado="Servicios desactivados y VERIFICADA.", componente="ram",
        )
    for _ in range(5):
        memoria.registrar_decision_medico_ia(
            "desactivar_servicios_basura", "bajo", "prueba", ejecutada=True,
            resultado="Error: no se pudo aplicar.", componente="cpu",
        )

    tasa_ram = memoria.tasa_exito_reparacion_por_componente("desactivar_servicios_basura", "ram", ultimas=5)
    tasa_cpu = memoria.tasa_exito_reparacion_por_componente("desactivar_servicios_basura", "cpu", ultimas=5)

    assert tasa_ram["porcentaje"] == 100.0
    assert tasa_cpu["porcentaje"] == 0.0


# ==========================================
#   Memoria de tendencias por tiempo
#   detectar_patrones_temporales()
# ==========================================

def test_patron_de_dia_semana_se_detecta_con_evidencia_suficiente(db_temporal):
    """
    Si un componente tiene problemas que se concentran repetidamente
    en el mismo día de la semana (distintas semanas), debe detectarse
    como patrón -- con evidencia real (casos/total), no una corazonada.
    """
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()

    base = datetime.now() - timedelta(days=1)
    dia_objetivo = base.weekday()
    # 4 casos en el mismo día de la semana, en 4 semanas distintas
    for i in range(4):
        f = base - timedelta(weeks=i)
        cur.execute("""
            INSERT INTO decisiones_medico_ia
            (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito, componente)
            VALUES (?, 'limpiar_winsxs', 'bajo', 'r', 1, 'ok', 'medio', 1, 'ssd')
        """, (f.strftime("%Y-%m-%d %H:%M"),))
    # 1 caso en otro día de la semana -- no debe romper el patrón (80% sigue siendo mayoría clara)
    otro_dia = base - timedelta(days=1)
    cur.execute("""
        INSERT INTO decisiones_medico_ia
        (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito, componente)
        VALUES (?, 'limpiar_winsxs', 'bajo', 'r', 1, 'ok', 'medio', 1, 'ssd')
    """, (otro_dia.strftime("%Y-%m-%d %H:%M"),))
    con.commit()
    con.close()

    patrones = memoria.detectar_patrones_temporales(dias_atras=30, minimo_casos=4, umbral_pct=60)

    assert len(patrones) == 1
    p = patrones[0]
    assert p["componente"] == "ssd"
    assert p["tipo"] == "dia_semana"
    assert p["detalle"] == memoria._DIAS_SEMANA_ES[dia_objetivo]
    assert p["casos"] == 4
    assert p["total"] == 5
    assert str(p["porcentaje"]) in p["voz"] or "80" in p["voz"]


def test_patron_franja_horaria_se_detecta_cuando_no_hay_patron_de_dia(db_temporal):
    """
    Si los casos caen en días de la semana distintos (sin patrón de
    día) pero siempre a la misma hora del día, debe detectarse el
    patrón por franja horaria en su lugar.
    """
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()

    base = datetime.now() - timedelta(days=1)
    for i in range(4):
        f = (base - timedelta(days=i)).replace(hour=14, minute=0)
        cur.execute("""
            INSERT INTO decisiones_medico_ia
            (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito, componente)
            VALUES (?, 'desactivar_servicios_basura', 'bajo', 'r', 1, 'ok', 'medio', 1, 'ram')
        """, (f.strftime("%Y-%m-%d %H:%M"),))
    con.commit()
    con.close()

    patrones = memoria.detectar_patrones_temporales(dias_atras=30, minimo_casos=4, umbral_pct=60)

    assert len(patrones) == 1
    p = patrones[0]
    assert p["componente"] == "ram"
    assert p["tipo"] == "franja_horaria"
    assert p["detalle"] == "tarde"


def test_patron_no_se_reporta_sin_evidencia_suficiente(db_temporal):
    """Menos casos que minimo_casos -- no debe afirmar ningún patrón, evidencia insuficiente."""
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    base = datetime.now() - timedelta(days=1)
    for i in range(3):  # por debajo de minimo_casos=4
        f = base - timedelta(weeks=i)
        cur.execute("""
            INSERT INTO decisiones_medico_ia
            (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito, componente)
            VALUES (?, 'limpiar_winsxs', 'bajo', 'r', 1, 'ok', 'medio', 1, 'ssd')
        """, (f.strftime("%Y-%m-%d %H:%M"),))
    con.commit()
    con.close()

    assert memoria.detectar_patrones_temporales(dias_atras=30, minimo_casos=4, umbral_pct=60) == []


def test_patron_no_se_reporta_si_distribucion_es_pareja(db_temporal):
    """
    Casos repartidos parejo entre días y franjas distintas -- no hay
    concentración real, así que no debe inventarse ningún patrón.
    """
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    base = datetime.now() - timedelta(days=1)
    horas = [1, 8, 14, 20]  # una por franja: madrugada, mañana, tarde, noche
    for i in range(4):
        f = (base - timedelta(days=i)).replace(hour=horas[i], minute=0)
        cur.execute("""
            INSERT INTO decisiones_medico_ia
            (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito, componente)
            VALUES (?, 'limpiar_winsxs', 'bajo', 'r', 1, 'ok', 'medio', 1, 'ssd')
        """, (f.strftime("%Y-%m-%d %H:%M"),))
    con.commit()
    con.close()

    assert memoria.detectar_patrones_temporales(dias_atras=30, minimo_casos=4, umbral_pct=60) == []


def test_patron_ignora_casos_fuera_de_la_ventana_de_dias(db_temporal):
    """Casos más viejos que dias_atras no deben contar para el patrón."""
    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    base = datetime.now() - timedelta(days=1)
    for i in range(4):
        f = base - timedelta(weeks=i, days=40)  # bien fuera de la ventana de 30 días
        cur.execute("""
            INSERT INTO decisiones_medico_ia
            (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito, componente)
            VALUES (?, 'limpiar_winsxs', 'bajo', 'r', 1, 'ok', 'medio', 1, 'ssd')
        """, (f.strftime("%Y-%m-%d %H:%M"),))
    con.commit()
    con.close()

    assert memoria.detectar_patrones_temporales(dias_atras=30, minimo_casos=4, umbral_pct=60) == []


# ==========================================
#   Circuito de seguridad contra bucles infinitos
#   fallos_consecutivos()
# ==========================================

def test_fallos_consecutivos_cuenta_desde_el_mas_reciente_hacia_atras(db_temporal):
    """3 fallos seguidos (los más recientes) deben contarse como 3, sin importar
    que antes de esos hubiera un éxito -- la racha se corta ahí."""
    memoria = db_temporal
    memoria.registrar_decision_medico_ia(
        "limpiar_winsxs", "bajo", "r", ejecutada=True, resultado="Limpieza completada y VERIFICADA.",
        componente="ssd",
    )
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "r", ejecutada=True, resultado="Error: fallo.",
            componente="ssd",
        )

    assert memoria.fallos_consecutivos("limpiar_winsxs", "ssd") == 3


def test_fallos_consecutivos_se_resetea_tras_un_exito(db_temporal):
    """Si la ejecución MÁS RECIENTE fue un éxito, la racha de fallos es 0,
    aunque antes hubiera habido varios fallos seguidos."""
    memoria = db_temporal
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "limpiar_winsxs", "bajo", "r", ejecutada=True, resultado="Error: fallo.",
            componente="ssd",
        )
    memoria.registrar_decision_medico_ia(
        "limpiar_winsxs", "bajo", "r", ejecutada=True, resultado="Limpieza completada y VERIFICADA.",
        componente="ssd",
    )

    assert memoria.fallos_consecutivos("limpiar_winsxs", "ssd") == 0


def test_fallos_consecutivos_sin_historial_es_cero(db_temporal):
    """Sin ninguna ejecución previa, no hay racha -- 0, no una excepción."""
    memoria = db_temporal
    assert memoria.fallos_consecutivos("limpiar_winsxs", "ssd") == 0


def test_fallos_consecutivos_distingue_por_componente(db_temporal):
    """Fallos seguidos de la misma acción para OTRO componente no deben
    contar para el componente que se está consultando."""
    memoria = db_temporal
    for _ in range(3):
        memoria.registrar_decision_medico_ia(
            "desactivar_servicios_basura", "bajo", "r", ejecutada=True, resultado="Error: fallo.",
            componente="cpu",
        )

    assert memoria.fallos_consecutivos("desactivar_servicios_basura", "ram") == 0
    assert memoria.fallos_consecutivos("desactivar_servicios_basura", "cpu") == 3
