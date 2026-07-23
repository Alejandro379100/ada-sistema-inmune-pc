# ==========================================
#   backtesting.py v1.0 - Validación contra el historial real
#
#   Script standalone, NO corre dentro del ciclo de Ada -- se ejecuta
#   a mano cuando querés saber si todo lo construido (aprendizaje,
#   circuito de seguridad, FSM) está sirviendo de verdad, en vez de
#   confiar en tests con datos sintéticos.
#
#   Uso:
#       python backtesting.py
#       python backtesting.py --log ruta\a\otro\ada_log.txt
#
#   Lee DOS fuentes, porque conviven dos generaciones de datos:
#
#   1. ada_log.txt (texto plano, todo el historial que ya tenías
#      antes de esta ronda). Se reconstruye por regex y por cercanía
#      de tiempo entre líneas -- es lo único que existe de semanas
#      pasadas, así que es la única forma de mirar atrás de verdad.
#
#   2. ada_telemetria.jsonl (JSON estructurado, existe recién desde
#      que se agregó telemetria.py). Cada línea ya trae su trace_id,
#      así que agrupar por ciclo es exacto, no una aproximación por
#      tiempo. A medida que pase más tiempo corriendo, este archivo
#      va a ser la fuente confiable -- el texto plano queda como
#      respaldo para lo viejo.
#
#   Filosofía: nunca afirmar una tasa de éxito con pocos datos como
#   si fuera un hecho sólido -- mismo criterio que ya usás en
#   config.REPARACION_MINIMO_INTENTOS_PARA_EVALUAR. Si hay menos
#   intentos que ese mínimo, el reporte lo dice explícitamente en vez
#   de mostrar un porcentaje que parece más confiable de lo que es.
# ==========================================

import os
import re
import json
import argparse
from collections import defaultdict
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from config import REPARACION_MINIMO_INTENTOS_PARA_EVALUAR as MINIMO_PARA_EVALUAR
except Exception:
    MINIMO_PARA_EVALUAR = 3  # mismo default que config.py si no se puede importar

# ------------------------------------------
#   PARSEO DE ada_log.txt (texto plano)
# ------------------------------------------

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[(\w+)\] (.*)$")

_PATRONES = {
    "ciclo_iniciado":  re.compile(r"Ciclo de diagnóstico: severidad (\w+) \(componente dominante: (\w+)\)\. (\d+) anomalía"),
    "groq_recomendo":  re.compile(r"Groq recomendó '([^']+)' \(riesgo (\w+)\): (.+)"),
    "cooldown":        re.compile(r"'([^']+)' ya se ejecutó en las últimas 24h"),
    "ejecute_groq":    re.compile(r"Ejecuté '([^']+)' sola \(riesgo (\w+)\)\. Resultado: (.+?)(?: \[trace_id=.*\])?$"),
    "decision_local":  re.compile(r"Decisión LOCAL \(sin Groq\): (.+?)\. Ejecuté ([^.]+)\. (.+)"),
    "verifique_sigue": re.compile(r"Verifiqué '([^']+)' -- el problema en '([^']+)' sigue presente"),
    "verifique_ok":    re.compile(r"Verifiqué '([^']+)' -- el problema en '([^']+)' ya se resolvió"),
    "plan_b":          re.compile(r"Verifiqué y '([^']+)' no resolvió\. Ejecuté plan B '([^']+)'\. Resultado: (.+)"),
    "circuito":        re.compile(r"CIRCUITO DE SEGURIDAD.*?'([^']+)' lleva (\d+) fallos"),
    "rollback":        re.compile(r"ROLLBACK: '([^']+)' empeoró '([^']+)' -- revertí con '([^']+)'\. (.+?)(?: \[trace_id=.*\])?$"),
}

# Si pasan más de esto entre dos líneas de [MÉDICO], se considera que
# empezó un ciclo nuevo, no una continuación del anterior -- los
# ciclos reales de Ada corren cada INTERVALO_MEDICO_IA_SEG (3 horas
# por default), así que dos líneas médicas separadas por más de 10
# minutos casi seguro son de ciclos distintos.
_VENTANA_MISMO_CICLO = timedelta(minutes=10)


def parsear_log_texto(ruta: str) -> list:
    """
    Devuelve una lista de "ciclos" reconstruidos del texto plano. Cada
    ciclo es un dict con lo que se pudo extraer de sus líneas [MÉDICO].
    No tiene trace_id real -- se agrupa por cercanía de tiempo, así que
    es una aproximación, no una reconstrucción exacta.
    """
    if not os.path.exists(ruta):
        return []

    ciclos = []
    ciclo_actual = None
    ultimo_ts = None

    with open(ruta, "r", encoding="utf-8", errors="replace") as f:
        for linea in f:
            m = _TS_RE.match(linea.strip())
            if not m:
                continue
            ts_txt, nivel, mensaje = m.groups()
            if "[MÉDICO]" not in linea and "MÉDICO" not in mensaje and not any(
                p.search(mensaje) for p in _PATRONES.values()
            ):
                continue

            try:
                ts = datetime.strptime(ts_txt, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if ciclo_actual is None or (ultimo_ts and ts - ultimo_ts > _VENTANA_MISMO_CICLO):
                ciclo_actual = {"inicio": ts, "eventos": []}
                ciclos.append(ciclo_actual)
            ultimo_ts = ts

            for tipo, patron in _PATRONES.items():
                match = patron.search(mensaje)
                if match:
                    ciclo_actual["eventos"].append({"tipo": tipo, "grupos": match.groups(), "ts": ts})
                    break

    return ciclos


# ------------------------------------------
#   PARSEO DE ada_telemetria.jsonl (estructurado)
# ------------------------------------------

def parsear_telemetria(ruta: str) -> dict:
    """
    Agrupa eventos JSONL por trace_id -- acá sí es exacto, no una
    aproximación por tiempo. Devuelve {trace_id: [eventos...]}.
    """
    ciclos = defaultdict(list)
    if not os.path.exists(ruta):
        return ciclos

    with open(ruta, "r", encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                evento = json.loads(linea)
            except json.JSONDecodeError:
                continue
            tid = evento.get("trace_id")
            if tid:
                ciclos[tid].append(evento)

    return ciclos


# ------------------------------------------
#   ESTADÍSTICAS POR ACCIÓN
# ------------------------------------------

def calcular_estadisticas(ciclos_texto: list, ciclos_telemetria: dict) -> dict:
    """
    Combina ambas fuentes en un solo conteo por acción: intentos,
    éxitos (verificados como resueltos), circuito de seguridad
    disparado, rollbacks aplicados. No mezcla los conceptos de las dos
    fuentes -- una "verificación" en texto plano y un "evento_verificacion"
    en JSON representan lo mismo, así que se suman al mismo contador.
    """
    stats = defaultdict(lambda: {
        "intentos": 0, "verificados_resueltos": 0, "verificados_sigue": 0,
        "cooldowns": 0, "circuito_activado": 0, "rollbacks": 0, "plan_b_usado": 0,
    })

    for ciclo in ciclos_texto:
        for ev in ciclo["eventos"]:
            tipo, g = ev["tipo"], ev["grupos"]
            if tipo == "ejecute_groq":
                stats[g[0]]["intentos"] += 1
            elif tipo == "decision_local":
                stats[g[1].strip()]["intentos"] += 1
            elif tipo == "verifique_ok":
                stats[g[0]]["verificados_resueltos"] += 1
            elif tipo == "verifique_sigue":
                stats[g[0]]["verificados_sigue"] += 1
            elif tipo == "cooldown":
                stats[g[0]]["cooldowns"] += 1
            elif tipo == "circuito":
                stats[g[0]]["circuito_activado"] += 1
            elif tipo == "rollback":
                stats[g[0]]["rollbacks"] += 1
            elif tipo == "plan_b":
                stats[g[1]]["intentos"] += 1
                stats[g[0]]["plan_b_usado"] += 1

    for tid, eventos in ciclos_telemetria.items():
        for ev in eventos:
            tipo = ev.get("tipo")
            accion = ev.get("accion")
            if tipo == "decision" and ev.get("ejecutada") and accion:
                stats[accion]["intentos"] += 1
                if ev.get("origen") == "plan_b":
                    stats[accion]["plan_b_usado"] += 1
                if ev.get("origen") == "rollback":
                    stats[accion]["rollbacks"] += 1
            elif tipo == "verificacion" and accion is None and ev.get("componente"):
                # evento_verificacion no trae 'accion' -- se cuenta contra
                # el componente, útil para el resumen general aunque no
                # se pueda atribuir a una acción puntual específica.
                clave = f"(componente:{ev['componente']})"
                if ev.get("sigue_presente") is False:
                    stats[clave]["verificados_resueltos"] += 1
                elif ev.get("sigue_presente") is True:
                    stats[clave]["verificados_sigue"] += 1
            elif tipo == "circuito_seguridad" and accion:
                stats[accion]["circuito_activado"] += 1

    return stats


def imprimir_reporte(stats: dict, n_ciclos_texto: int, n_ciclos_telemetria: int):
    print("=" * 60)
    print("  BACKTESTING — Ada, historial real")
    print("=" * 60)
    print(f"Ciclos reconstruidos de ada_log.txt (aproximado):  {n_ciclos_texto}")
    print(f"Ciclos exactos de ada_telemetria.jsonl (trace_id): {n_ciclos_telemetria}")
    print()

    if not stats:
        print("No hay suficientes datos todavía en ninguna de las dos fuentes.")
        print("Esto es normal si ada_telemetria.jsonl recién se activó — dejá correr")
        print("Ada un tiempo y volvé a correr este script.")
        return

    for accion, s in sorted(stats.items(), key=lambda kv: -kv[1]["intentos"]):
        total_verificado = s["verificados_resueltos"] + s["verificados_sigue"]
        print(f"— {accion}")
        print(f"    intentos ejecutados:     {s['intentos']}")
        if total_verificado > 0:
            tasa = round(100 * s["verificados_resueltos"] / total_verificado, 1)
            if total_verificado < MINIMO_PARA_EVALUAR:
                print(f"    tasa de éxito verificado: {tasa}% "
                      f"({s['verificados_resueltos']}/{total_verificado}) "
                      f"⚠ MUESTRA CHICA — menos de {MINIMO_PARA_EVALUAR} verificaciones, "
                      f"no sacar conclusiones todavía")
            else:
                print(f"    tasa de éxito verificado: {tasa}% ({s['verificados_resueltos']}/{total_verificado})")
        if s["cooldowns"]:
            print(f"    veces evitada por cooldown 24h: {s['cooldowns']}")
        if s["plan_b_usado"]:
            print(f"    usada como plan B: {s['plan_b_usado']}")
        if s["circuito_activado"]:
            print(f"    ⚠ circuito de seguridad activado: {s['circuito_activado']} vez/veces")
        if s["rollbacks"]:
            print(f"    ⚠ rollback aplicado: {s['rollbacks']} vez/veces")
        print()

    print("=" * 60)
    total_intentos = sum(s["intentos"] for s in stats.values())
    total_circuitos = sum(s["circuito_activado"] for s in stats.values())
    total_rollbacks = sum(s["rollbacks"] for s in stats.values())
    print(f"Total de acciones ejecutadas en el historial: {total_intentos}")
    print(f"Total de veces que se activó el circuito de seguridad: {total_circuitos}")
    print(f"Total de rollbacks aplicados: {total_rollbacks}")
    if total_intentos < 10:
        print()
        print("⚠ Con menos de 10 acciones en todo el historial, esto todavía no alcanza")
        print("  para decir si el médico mejora las decisiones o no. Es una foto del punto")
        print("  de partida, no una validación -- volvé a correr esto en unas semanas.")


def main():
    parser = argparse.ArgumentParser(description="Backtesting del médico de Ada contra el historial real.")
    parser.add_argument("--log", default=os.path.join(BASE_DIR, "ada_log.txt"),
                         help="Ruta a ada_log.txt (default: junto a este script)")
    parser.add_argument("--telemetria", default=os.path.join(BASE_DIR, "ada_telemetria.jsonl"),
                         help="Ruta a ada_telemetria.jsonl (default: junto a este script)")
    args = parser.parse_args()

    ciclos_texto = parsear_log_texto(args.log)
    ciclos_telemetria = parsear_telemetria(args.telemetria)
    stats = calcular_estadisticas(ciclos_texto, ciclos_telemetria)
    imprimir_reporte(stats, len(ciclos_texto), len(ciclos_telemetria))


if __name__ == "__main__":
    main()
