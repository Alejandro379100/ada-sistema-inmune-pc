# ==========================================
#   test_puntuacion.py
#   Prueba el reconocimiento de procesos: que
#   elija la coincidencia MÁS ESPECÍFICA, no la
#   primera que encuentre por substring.
# ==========================================

import puntuacion


def test_coincidencia_exacta_tiene_prioridad():
    # _base es perezoso: solo se llena cuando se llama cargar_base()
    # (normalmente lo hace calcular_score_proceso() por dentro).
    puntuacion.cargar_base()
    resultado = puntuacion._buscar_proceso("chrome.exe")
    assert resultado is not None


def test_coincidencia_por_substring_elige_la_mas_especifica(monkeypatch):
    """
    Antes: iterar el diccionario y quedarse con la PRIMERA clave que
    hiciera match por substring — una clave corta y genérica podía
    robarle el score a un proceso que no tenía nada que ver.
    Ahora: se queda con la coincidencia más larga (más específica).
    """
    base_de_prueba = {
        "unknown": {"nombre": "Desconocido", "es_critico": False},
        "code": {"nombre": "Genérico corto", "es_critico": False},
        "visual studio code": {"nombre": "Editor real", "es_critico": False},
    }
    monkeypatch.setattr(puntuacion, "_base", base_de_prueba)

    resultado = puntuacion._buscar_proceso("visual studio code helper.exe")

    assert resultado["nombre"] == "Editor real", \
        "Debería elegir la clave más específica, no la más corta que también calza"


def test_proceso_desconocido_cae_en_unknown(monkeypatch):
    base_de_prueba = {
        "unknown": {"nombre": "Desconocido", "es_critico": False},
        "chrome": {"nombre": "Chrome", "es_critico": False},
    }
    monkeypatch.setattr(puntuacion, "_base", base_de_prueba)

    resultado = puntuacion._buscar_proceso("un_proceso_que_no_existe_en_ningun_lado.exe")
    assert resultado["nombre"] == "Desconocido"


# ==========================================
#   calcular_severidad_diagnostico()
#   Priorización por severidad — reglas fijas,
#   sin Groq, para que sea reproducible.
# ==========================================

SSD_OK    = {"estado": "saludable"}
RAM_OK    = {"estado": "saludable"}
CPU_OK    = {"estado": "saludable"}


def test_todo_sano_da_severidad_baja():
    resultado = puntuacion.calcular_severidad_diagnostico(SSD_OK, RAM_OK, CPU_OK, [], [])
    assert resultado["categoria"] == "bajo"
    assert resultado["puntaje"] == 0


def test_ssd_critico_domina_sobre_ram_moderada():
    """
    Un disco muriéndose debe pesar más que una RAM con presión
    moderada, aunque ambos estén presentes a la vez — el hallazgo
    más grave es el que define la categoría final.
    """
    ssd = {"estado": "critico"}
    ram = {"estado": "moderada"}
    resultado = puntuacion.calcular_severidad_diagnostico(ssd, ram, CPU_OK, [], [])
    assert resultado["categoria"] == "critico"
    assert resultado["componente_dominante"] == "ssd"


def test_ram_critica_es_alta_pero_no_critica_por_si_sola():
    ram = {"estado": "critica"}
    resultado = puntuacion.calcular_severidad_diagnostico(SSD_OK, ram, CPU_OK, [], [])
    assert resultado["categoria"] == "alto"
    assert resultado["componente_dominante"] == "ram"


def test_muchos_eventos_criticos_suben_la_severidad():
    eventos = [{"nivel": 1} for _ in range(6)]
    resultado = puntuacion.calcular_severidad_diagnostico(SSD_OK, RAM_OK, CPU_OK, eventos, [])
    assert resultado["categoria"] == "alto"
    assert resultado["componente_dominante"] == "eventos"


def test_prediccion_urgencia_alta_se_refleja_en_severidad():
    predicciones = [{"tipo": "disco", "urgencia": "alta"}]
    resultado = puntuacion.calcular_severidad_diagnostico(SSD_OK, RAM_OK, CPU_OK, [], predicciones)
    assert resultado["categoria"] == "medio"
    assert "prediccion_disco" == resultado["componente_dominante"]


def test_severidad_es_determinística_no_depende_de_orden():
    """Mismos datos, mismo resultado — sin importar el orden interno
    en que se evalúan los componentes."""
    ssd = {"estado": "advertencia"}
    ram = {"estado": "alta"}
    r1 = puntuacion.calcular_severidad_diagnostico(ssd, ram, CPU_OK, [], [])
    r2 = puntuacion.calcular_severidad_diagnostico(ssd, ram, CPU_OK, [], [])
    assert r1 == r2


def test_bateria_critica_pesa_mas_que_ram_moderada():
    """Mismo tratamiento que CPU: batería entra al mismo cálculo de
    severidad que el resto de los componentes."""
    ram = {"estado": "moderada"}
    bateria = {"estado": "critica", "salud_pct": 38}
    resultado = puntuacion.calcular_severidad_diagnostico(
        SSD_OK, ram, CPU_OK, [], [], bateria=bateria)
    assert resultado["categoria"] == "alto"
    assert resultado["componente_dominante"] == "bateria"


def test_bateria_ok_no_suma_severidad():
    bateria = {"estado": "excelente", "salud_pct": 95}
    resultado = puntuacion.calcular_severidad_diagnostico(
        SSD_OK, RAM_OK, CPU_OK, [], [], bateria=bateria)
    assert resultado["categoria"] == "bajo"


def test_drivers_sin_firma_suben_severidad():
    drivers = {"total": 50, "no_firmados": 4, "estado": "riesgo"}
    resultado = puntuacion.calcular_severidad_diagnostico(
        SSD_OK, RAM_OK, CPU_OK, [], [], drivers=drivers)
    assert resultado["categoria"] == "medio"
    assert resultado["componente_dominante"] == "drivers"


def test_severidad_sin_bateria_ni_drivers_sigue_funcionando_igual():
    """bateria/drivers son opcionales — nadie que ya usaba esta
    función antes debería romperse por no pasarlos."""
    resultado = puntuacion.calcular_severidad_diagnostico(SSD_OK, RAM_OK, CPU_OK, [], [])
    assert resultado["categoria"] == "bajo"


# ==========================================
#   listar_anomalias()
#   Triage puro para Groq: solo lo que está
#   mal, con números — nada de "RAM: bien".
# ==========================================

def test_todo_sano_no_da_anomalias():
    resultado = puntuacion.listar_anomalias(SSD_OK, RAM_OK, CPU_OK, [], [])
    assert resultado == []


def test_una_sola_anomalia_aparece_sola():
    ssd = {"estado": "advertencia"}
    resultado = puntuacion.listar_anomalias(ssd, RAM_OK, CPU_OK, [], [])
    assert len(resultado) == 1
    assert "espacio libre" in resultado[0]


def test_anomalias_usan_los_mismos_umbrales_que_la_severidad():
    """
    listar_anomalias() y calcular_severidad_diagnostico() comparten
    _listar_candidatos_severidad() -- si algo cuenta como anomalía
    para una, tiene que contar para la otra. Nunca deberían
    desacordar sobre qué es "normal".
    """
    ram = {"estado": "critica"}
    anomalias = puntuacion.listar_anomalias(SSD_OK, ram, CPU_OK, [], [])
    severidad = puntuacion.calcular_severidad_diagnostico(SSD_OK, ram, CPU_OK, [], [])
    assert len(anomalias) == 1
    assert severidad["componente_dominante"] == "ram"


def test_varias_anomalias_se_ordenan_de_mas_a_menos_grave():
    ssd = {"estado": "advertencia"}   # puntaje 55
    ram = {"estado": "critica"}       # puntaje 85
    resultado = puntuacion.listar_anomalias(ssd, ram, CPU_OK, [], [])
    assert len(resultado) == 2
    assert "swap" in resultado[0] or "crítica" in resultado[0].lower(), \
        "La más grave (RAM crítica) debería ir primero"
