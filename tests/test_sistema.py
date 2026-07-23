# ==========================================
#   test_sistema.py
#   Prueba el enganche de memoria por proceso a
#   largo plazo dentro del análisis profundo de
#   procesos que ya corre cada 10 minutos.
# ==========================================

import sqlite3


def test_analisis_profundo_registra_muestra_de_procesos_relevantes(db_temporal, monkeypatch):
    """
    _analisis_profundo_procesos() ya recorre todos los procesos cada
    ciclo — memoria por proceso se engancha ahí mismo, sin agregar
    un hilo ni un ciclo nuevo. Un proceso con memoria suficiente debe
    quedar registrado para poder rastrear su tendencia después.
    """
    import sistema

    procesos_falsos = [
        {"pid": 111, "name": "chrome.exe", "memory_percent": 6.0, "cpu_percent": 2.0},
        {"pid": 222, "name": "svchost.exe", "memory_percent": 0.05, "cpu_percent": 0.1},
    ]
    monkeypatch.setattr(sistema, "listar_procesos", lambda attrs: procesos_falsos)
    monkeypatch.setattr(sistema, "_analizar_proceso",
                         lambda nombre, mem, cpu: {"amenaza": False, "tipo": "normal"})

    sistema._analisis_profundo_procesos()

    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT nombre, memoria_pct FROM memoria_por_proceso")
    filas = cur.fetchall()
    con.close()

    nombres = [f[0] for f in filas]
    assert "chrome.exe" in nombres, "Un proceso con memoria relevante debería quedar registrado"


def test_analisis_profundo_no_registra_procesos_irrelevantes(db_temporal, monkeypatch):
    """
    Procesos con memoria y CPU insignificantes no deberían generar
    filas — eso es justamente lo que mantiene la tabla liviana.
    """
    import sistema

    procesos_falsos = [
        {"pid": 333, "name": "proceso_minimo.exe", "memory_percent": 0.1, "cpu_percent": 0.2},
    ]
    monkeypatch.setattr(sistema, "listar_procesos", lambda attrs: procesos_falsos)
    monkeypatch.setattr(sistema, "_analizar_proceso",
                         lambda nombre, mem, cpu: {"amenaza": False, "tipo": "normal"})

    sistema._analisis_profundo_procesos()

    memoria = db_temporal
    con = sqlite3.connect(memoria.DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM memoria_por_proceso WHERE nombre = 'proceso_minimo.exe'")
    total = cur.fetchone()[0]
    con.close()

    assert total == 0
