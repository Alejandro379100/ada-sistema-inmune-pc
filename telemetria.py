# ==========================================
#   telemetria.py v1.0 - Registro estructurado de Ada
#   Corre EN PARALELO a ada_log.txt (no lo reemplaza).
#
#   Cada ciclo de diagnóstico del médico recibe un
#   trace_id propio, y cada evento relevante de ese
#   ciclo (decisión, ejecución, verificación) queda
#   como UNA línea JSON con ese mismo trace_id.
#
#   Por qué separado de ada_log.txt: ese archivo está
#   pensado para que Alejandro lo lea ("Ejecuté X sola,
#   riesgo bajo"). Este archivo está pensado para que un
#   script lo parsee (backtesting, patrones, causalidad
#   entre componentes) sin tener que hacer regex sobre
#   frases en español que van a seguir cambiando.
#
#   Filosofía: esto es OBSERVABILIDAD, nunca lógica
#   crítica. Si telemetria.py falla, el ciclo del médico
#   tiene que seguir andando igual -- Ada nunca deja de
#   diagnosticar o reparar por un problema de logging.
# ==========================================

import os
import json
import uuid
import logging
import logging.handlers
from datetime import datetime

from config import LOG_ROTACION_DIAS, LOG_BACKUPS_MAXIMOS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUTA_TELEMETRIA = os.path.join(BASE_DIR, "ada_telemetria.jsonl")

_logger_telemetria = None


def _obtener_logger():
    """
    Logger separado del logging general de Ada (el que configura
    app.py). Nunca se mezcla con ada_log.txt: si una línea JSON
    queda mal formada por lo que sea, no ensucia el log en texto
    plano que Alejandro lee, y viceversa.

    Misma política de rotación que ada_log.txt (config.LOG_ROTACION_DIAS
    / LOG_BACKUPS_MAXIMOS) para que crezca acotado igual que el resto
    de los logs de Ada -- ninguna razón para que este tenga una regla
    de retención distinta.
    """
    global _logger_telemetria
    if _logger_telemetria is not None:
        return _logger_telemetria

    logger = logging.getLogger("ada.telemetria")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.handlers.TimedRotatingFileHandler(
            RUTA_TELEMETRIA, when="D", interval=LOG_ROTACION_DIAS,
            backupCount=LOG_BACKUPS_MAXIMOS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    _logger_telemetria = logger
    return logger


def nuevo_trace_id() -> str:
    """
    ID corto (8 caracteres hex) para agrupar todos los eventos de un
    mismo ciclo de diagnóstico. No hace falta un UUID completo acá:
    el mutex de instancia única de app.py ya garantiza que nunca hay
    dos Adas corriendo en paralelo en el mismo equipo, así que el
    volumen real de ciclos por instancia hace la chance de colisión
    en 8 caracteres irrelevante en la práctica.
    """
    return uuid.uuid4().hex[:8]


def _escribir(evento: dict):
    """
    Punto único de escritura. Atrapa cualquier excepción -- un typo
    en un valor no serializable a JSON no puede tumbar un ciclo real
    de diagnóstico o reparación.
    """
    try:
        evento["ts"] = datetime.now().isoformat(timespec="seconds")
        _obtener_logger().info(json.dumps(evento, ensure_ascii=False, default=str))
    except Exception as e:
        logging.warning(f"[TELEMETRÍA] No pude escribir evento estructurado: {e}")


def snapshot_metricas(ssd: dict = None, ram: dict = None, cpu: dict = None) -> dict:
    """
    Convierte los diccionarios que medico.py ya calcula
    (salud_ssd_completa, presion_ram, presion_cpu_nucleos) en un
    vector chico y estable de NÚMEROS -- sin arrastrar los textos de
    'voz', que cambian de redacción entre versiones y no sirven para
    comparar ANTES/DESPUÉS de forma programática.

    No mide nada nuevo: solo reempaqueta lo que Ada ya midió en ese
    mismo ciclo, así que este llamado no tiene costo extra real.
    """
    m = {}
    if ram:
        m["ram_libre_gb"]  = ram.get("libre_gb")
        m["ram_usado_pct"] = ram.get("usado_pct")
        m["ram_swap_gb"]   = ram.get("swap_gb")
    if ssd:
        m["ssd_libre_gb"]  = ssd.get("libre_gb")
        m["ssd_usado_pct"] = ssd.get("usado_pct")
        m["ssd_health"]    = ssd.get("health_status")
    if cpu:
        nucleos = cpu.get("nucleos_pct") or []
        m["cpu_promedio_pct"]       = round(sum(nucleos) / len(nucleos), 1) if nucleos else None
        m["cpu_nucleos_saturados"]  = cpu.get("nucleos_saturados")
    return m


# ------------------------------------------
#   EVENTOS DEL CICLO
#   Un evento por cada momento clave -- todos
#   comparten trace_id para poder reconstruir
#   el ciclo completo filtrando por ese campo.
# ------------------------------------------

def evento_ciclo_iniciado(trace_id: str, severidad: str, componente: str,
                           anomalias: int, metricas_antes: dict):
    _escribir({
        "trace_id": trace_id, "tipo": "ciclo_iniciado",
        "severidad": severidad, "componente": componente,
        "anomalias": anomalias, "metricas_antes": metricas_antes,
    })


def evento_decision(trace_id: str, origen: str, accion: str, riesgo: str,
                     razon: str, ejecutada: bool, resultado: str = "",
                     componente: str = None):
    """
    origen: 'local' (decisión sin Groq, ya confiable por historial),
            'groq' (parte de un plan que devolvió Groq),
            'plan_b' (alternativa tras verificar que el problema seguía).
    """
    _escribir({
        "trace_id": trace_id, "tipo": "decision", "origen": origen,
        "accion": accion, "riesgo": riesgo, "razon": razon,
        "ejecutada": ejecutada, "resultado": resultado, "componente": componente,
    })


def evento_verificacion(trace_id: str, componente: str, sigue_presente,
                         metricas_despues: dict):
    """
    sigue_presente: True/False/None -- mismo significado que devuelve
    medico._problema_sigue_presente(): None es 'no se pudo verificar',
    nunca se confunde con 'se resolvió'.
    """
    _escribir({
        "trace_id": trace_id, "tipo": "verificacion", "componente": componente,
        "sigue_presente": sigue_presente, "metricas_despues": metricas_despues,
    })


def evento_circuito_seguridad(trace_id: str, accion: str, componente: str,
                               fallos_consecutivos: int):
    _escribir({
        "trace_id": trace_id, "tipo": "circuito_seguridad",
        "accion": accion, "componente": componente,
        "fallos_consecutivos": fallos_consecutivos,
    })


def evento_ciclo_cerrado(trace_id: str, mensajes_generados: int):
    _escribir({
        "trace_id": trace_id, "tipo": "ciclo_cerrado",
        "mensajes_generados": mensajes_generados,
    })
