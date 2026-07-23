# ==========================================
#   fsm_medico.py v1.0 - Máquina de estados del médico
#
#   Explicita los estados por los que pasa cada acción que
#   Ada ejecuta sola, y resuelve el hueco que existía en el
#   código: el punto de restauración se creaba pero nunca se
#   usaba, porque _problema_sigue_presente() solo distinguía
#   "resuelto" / "sigue igual" -- nunca "empeoró".
#
#   IDLE -> DIAGNOSING -> STAGING_ACTION -> EXECUTING ->
#   VERIFYING -> (RESUELTO | SIGUE_IGUAL | ROLLBACK) ->
#   CIRCUIT_BROKEN (si el rollback no es posible)
#
#   Los primeros cuatro estados (IDLE..EXECUTING) ya existen
#   como pasos reales dentro de medico.py -- este módulo no
#   los reemplaza, los nombra. Lo que sí agrega de verdad es
#   la decisión que pasa DESPUÉS de VERIFYING.
#
#   Filosofía acordada con Alejandro: el estado ROLLBACK NUNCA
#   dispara una restauración completa del sistema (Restore-
#   Computer) de forma automática -- eso exige reiniciar el
#   equipo y revierte más que lo que Ada tocó, así que queda
#   reservado a una decisión humana. Cuando hay una reversión
#   puntual conocida para la acción (hoy solo
#   desactivar_servicios_basura -> reactivar_servicios_basura),
#   la FSM la aplica sola. Cuando no la hay, pasa a
#   CIRCUIT_BROKEN: se bloquea la acción y se avisa del punto
#   de restauración disponible, sin tocarlo.
# ==========================================

from enum import Enum
import logging

import telemetria


class Estado(Enum):
    IDLE            = "idle"
    DIAGNOSING      = "diagnosing"
    STAGING_ACTION  = "staging_action"
    EXECUTING       = "executing"
    VERIFYING       = "verifying"
    RESUELTO        = "resuelto"
    SIGUE_IGUAL     = "sigue_igual"
    ROLLBACK        = "rollback"
    CIRCUIT_BROKEN  = "circuit_broken"


# ------------------------------------------
#   COMPARACIÓN ANTES/DESPUÉS
#   Solo mira los campos relevantes al componente que motivó
#   la acción -- no tiene sentido juzgar "empeoró" mirando CPU
#   cuando lo que se estaba tratando era el SSD.
# ------------------------------------------

# Para cada campo de telemetria.snapshot_metricas(): si un número más
# alto es mejor o peor.
_DIRECCION_BUENA = {
    "ram_libre_gb":         "mas_es_mejor",
    "ssd_libre_gb":         "mas_es_mejor",
    "cpu_promedio_pct":     "menos_es_mejor",
    "cpu_nucleos_saturados":"menos_es_mejor",
}

# Margen mínimo de cambio para no confundir ruido normal de medición
# con un empeoramiento real -- una décima de GB o un punto de CPU no
# cuentan como "empeoró", son variación normal del sistema.
_TOLERANCIA = {
    "ram_libre_gb":          0.3,
    "ssd_libre_gb":          0.3,
    "cpu_promedio_pct":      5,
    "cpu_nucleos_saturados": 1,
}

# Qué campos del snapshot son relevantes para cada componente.
_CAMPOS_POR_COMPONENTE = {
    "ram": ["ram_libre_gb"],
    "ssd": ["ssd_libre_gb"],
    "cpu": ["cpu_promedio_pct", "cpu_nucleos_saturados"],
}


def comparar_metricas(componente: str, metricas_antes: dict, metricas_despues: dict) -> str:
    """
    Compara el vector ANTES/DESPUÉS solo en los campos relevantes al
    componente tratado. Devuelve 'mejoro', 'empeoro', 'igual' o
    'desconocido' (falta algún dato -- nunca se asume un
    empeoramiento sin evidencia numérica real).
    """
    campos = _CAMPOS_POR_COMPONENTE.get(componente)
    if not campos or not metricas_antes or not metricas_despues:
        return "desconocido"

    peor_en_algun_campo  = False
    mejor_en_algun_campo = False
    tuvo_dato_valido     = False

    for campo in campos:
        antes   = metricas_antes.get(campo)
        despues = metricas_despues.get(campo)
        if antes is None or despues is None:
            continue
        tuvo_dato_valido = True

        direccion  = _DIRECCION_BUENA.get(campo)
        tolerancia = _TOLERANCIA.get(campo, 0)
        delta      = despues - antes

        if direccion == "mas_es_mejor":
            if delta <= -tolerancia:
                peor_en_algun_campo = True
            elif delta >= tolerancia:
                mejor_en_algun_campo = True
        elif direccion == "menos_es_mejor":
            if delta >= tolerancia:
                peor_en_algun_campo = True
            elif delta <= -tolerancia:
                mejor_en_algun_campo = True

    if not tuvo_dato_valido:
        return "desconocido"
    if peor_en_algun_campo:
        return "empeoro"
    if mejor_en_algun_campo:
        return "mejoro"
    return "igual"


# ------------------------------------------
#   REVERSIONES CONOCIDAS
#   accion ejecutada -> nombre de la función de reversión en
#   auto_reparador.py. Si una acción no aparece acá, NO tiene una
#   reversión puntual segura conocida -- el camino es CIRCUIT_BROKEN,
#   nunca un intento a ciegas de deshacerla de otra forma.
# ------------------------------------------
REVERSIONES_DISPONIBLES = {
    "desactivar_servicios_basura": "reactivar_servicios_basura",
}


def decidir_tras_verificacion(trace_id: str, accion: str, componente: str, sigue_presente,
                               metricas_antes: dict, metricas_despues: dict) -> dict:
    """
    Punto central de la FSM. A partir de lo que devolvió
    medico._problema_sigue_presente() (True/False/None) y el vector
    de métricas antes/después, decide el estado del ciclo.

    Retorna {"estado": Estado, "comparacion": str, "accion_reversion": str|None}

      - sigue_presente False -> RESUELTO.
      - sigue_presente None  -> no se pudo re-medir; SIGUE_IGUAL por
        defecto -- sin evidencia numérica, nunca se asume que empeoró.
      - sigue_presente True  -> se compara el vector antes/después:
          'empeoro'              -> ROLLBACK (si hay reversión conocida)
                                     o CIRCUIT_BROKEN (si no la hay)
          'igual' / 'mejoro'     -> SIGUE_IGUAL (sigue mal, pero no
                                     empeoró -- camino normal a plan B)
          'desconocido'          -> SIGUE_IGUAL (ante la duda, nunca
                                     se dispara un rollback sin evidencia)
    """
    if sigue_presente is False:
        estado, comparacion, accion_reversion = Estado.RESUELTO, "resuelto", None
    elif sigue_presente is None:
        estado, comparacion, accion_reversion = Estado.SIGUE_IGUAL, "sin_verificar", None
    else:
        comparacion = comparar_metricas(componente, metricas_antes, metricas_despues)
        if comparacion == "empeoro":
            accion_reversion = REVERSIONES_DISPONIBLES.get(accion)
            estado = Estado.ROLLBACK if accion_reversion else Estado.CIRCUIT_BROKEN
        else:
            estado, accion_reversion = Estado.SIGUE_IGUAL, None

    telemetria.evento_verificacion(trace_id, componente, sigue_presente, metricas_despues)
    return {"estado": estado, "comparacion": comparacion, "accion_reversion": accion_reversion}


def ejecutar_rollback(trace_id: str, accion: str, componente: str, accion_reversion: str,
                       severidad_categoria: str) -> str:
    """
    Ejecuta la reversión puntual conocida para 'accion'. NUNCA dispara
    una restauración completa del sistema -- eso queda deliberadamente
    fuera del alcance de esta función.
    """
    from memoria import registrar_decision_medico_ia
    import auto_reparador

    funcion_reversion = getattr(auto_reparador, accion_reversion, None)
    if not funcion_reversion:
        # No debería pasar nunca si REVERSIONES_DISPONIBLES está bien
        # armado -- pero si algún día se desincroniza, no se ejecuta
        # nada a ciegas.
        logging.error(f"[FSM] Reversión '{accion_reversion}' no existe en auto_reparador.py "
                      f"-- revisar REVERSIONES_DISPONIBLES.")
        return ""

    try:
        resultado = funcion_reversion()
    except Exception as e:
        resultado = f"Error revirtiendo {accion}: {e}"

    registrar_decision_medico_ia(
        accion_reversion, "bajo",
        f"Rollback de '{accion}': el componente '{componente}' empeoró después de ejecutarla",
        ejecutada=True, resultado=resultado, severidad=severidad_categoria, componente=componente,
    )
    telemetria.evento_decision(trace_id, origen="rollback", accion=accion_reversion, riesgo="bajo",
                                razon=f"revertir {accion} (empeoró {componente})", ejecutada=True,
                                resultado=resultado, componente=componente)
    logging.warning(f"[FSM] ROLLBACK: '{accion}' empeoró '{componente}' -- revertí con "
                    f"'{accion_reversion}'. {resultado} [trace_id={trace_id}]")
    return (f"Verifiqué después de {accion} y el problema EMPEORÓ -- la revertí de inmediato "
            f"({accion_reversion}). {resultado}")


def circuito_roto_sin_rollback(trace_id: str, accion: str, componente: str,
                                severidad_categoria: str) -> str:
    """
    La acción empeoró el componente y no hay una reversión puntual
    segura conocida. Se bloquea la acción (mismo espíritu que el
    circuito de fallos consecutivos, pero disparado por UN solo
    empeoramiento verificado, no por acumular 3 fallos) y se avisa del
    punto de restauración disponible -- sin dispararlo.
    """
    from memoria import registrar_decision_medico_ia
    import auto_reparador

    momento = auto_reparador.momento_ultimo_punto_restauracion()
    momento_txt = momento.strftime("%Y-%m-%d %H:%M") if momento else "no disponible esta sesión"

    registrar_decision_medico_ia(
        accion, "bajo", "",
        ejecutada=False,
        resultado=(f"CIRCUITO DE SEGURIDAD (FSM): '{accion}' empeoró '{componente}' y no tiene "
                   f"reversión puntual segura. Bloqueada hasta revisión humana."),
        severidad=severidad_categoria, componente=componente,
    )
    telemetria.evento_circuito_seguridad(trace_id, accion, componente, fallos_consecutivos=1)
    logging.error(f"[FSM] CIRCUITO DE SEGURIDAD: '{accion}' empeoró '{componente}' sin reversión "
                  f"puntual conocida -- bloqueada. Punto de restauración: {momento_txt}. "
                  f"[trace_id={trace_id}]")
    return (f"Verifiqué después de {accion} y el problema EMPEORÓ. No tengo una forma segura de "
            f"revertir esto sola, así que la bloqueé -- no la vuelvo a intentar sin que la revises. "
            f"Hay un punto de restauración de Windows del {momento_txt} por si querés usarlo vos.")
