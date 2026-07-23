# ==========================================
#   puntuacion.py v1.0 - Sistema Nervioso de Ada
#   Ada puntúa cada proceso que corre en ella.
#   Problema 14 resuelto: score local, sin Groq.
#
#   Score 0-100 por proceso:
#     90-100 → esencial, Ada lo protege
#     70-89  → normal, Ada lo ignora
#     50-69  → neutral, Ada lo vigila
#     30-49  → sospechoso, Ada lo marca
#     0-29   → basura/peligro, Ada actúa
# ==========================================

import os
import json
import psutil
from typing import Optional
from nucleo_procesos import listar_procesos

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
PROCESOS_PATH  = os.path.join(BASE_DIR, "procesos.json")

# Cache en RAM — se carga una vez al arrancar
_base: dict = {}
_meta: dict = {}

# ------------------------------------------
#   CARGAR BASE DE CONOCIMIENTO LOCAL
# ------------------------------------------

def cargar_base():
    """Carga procesos.json en RAM — solo una vez"""
    global _base, _meta
    try:
        with open(PROCESOS_PATH, 'r', encoding='utf-8') as f:
            datos  = json.load(f)
        _base  = datos.get("procesos", {})
        _meta  = datos.get("_meta", {})
        print(f"✅ Base de procesos cargada — {len(_base)} procesos conocidos")
        return True
    except Exception as e:
        print(f"⚠️  No pude cargar procesos.json: {e}")
        return False

def _buscar_proceso(nombre: str) -> Optional[dict]:
    """Busca un proceso por nombre exacto o parcial"""
    nombre_lower = nombre.lower().strip()

    # Búsqueda exacta primero
    if nombre_lower in _base:
        return _base[nombre_lower]

    # Búsqueda parcial — el nombre puede tener ruta completa
    nombre_base = os.path.basename(nombre_lower)
    if nombre_base in _base:
        return _base[nombre_base]

    # Búsqueda por "contiene" — para variantes como "code.exe" vs
    # "Code.exe". Antes esto devolvía la PRIMERA clave que calzara,
    # en el orden en que quedó guardada en procesos.json — así que una
    # clave corta y genérica podía "robarse" el score de un proceso que
    # no tenía nada que ver. Ahora se elige la coincidencia MÁS
    # específica (la clave más larga que calce), y se ignoran claves
    # demasiado cortas (menos de 4 letras) porque esas son las que más
    # falsos positivos generan.
    mejor_clave = None
    for clave in _base.keys():
        if clave == "unknown" or len(clave) < 4:
            continue
        if clave in nombre_lower or nombre_lower in clave:
            if mejor_clave is None or len(clave) > len(mejor_clave):
                mejor_clave = clave

    if mejor_clave:
        return _base[mejor_clave]

    # No encontrado → usar "unknown"
    return _base.get("unknown")

# ------------------------------------------
#   SCORE PRINCIPAL
#   Combina base de conocimiento + uso real
# ------------------------------------------

def calcular_score_proceso(nombre: str, ram_pct: float, cpu_pct: float) -> dict:
    """
    Calcula el score de salud de un proceso.

    Retorna:
    {
        "nombre": str,
        "score": int (0-100),
        "categoria": str,
        "critico": bool,
        "descripcion": str,    ← Ada habla del proceso en 1ra persona
        "accion": str,
        "penalizacion": int,   ← cuántos puntos perdió por uso alto
        "estado": str          ← "saludable"|"vigilar"|"alerta"|"critico"
    }
    """
    if not _base:
        cargar_base()

    info = _buscar_proceso(nombre)
    if not info:
        info = _base.get("unknown", {
            "cat": "desconocido", "peso_normal_mb": 0, "score_base": 40,
            "critico": False, "desc": "Proceso desconocido.",
            "accion_si_alto": "analizar_con_groq"
        })

    score_base  = info.get("score_base", 50)
    peso_normal = info.get("peso_normal_mb", 100)
    critico     = info.get("critico", False)

    # ── PENALIZACIONES POR USO REAL ──────────────────
    penalizacion = 0

    # RAM: si consume más del doble de lo normal, penalizar
    if ram_pct > 0 and peso_normal > 0:
        try:
            ram_real_mb = _pct_a_mb(ram_pct)
            if ram_real_mb > peso_normal * 3:
                penalizacion += 30
            elif ram_real_mb > peso_normal * 2:
                penalizacion += 15
            elif ram_real_mb > peso_normal * 1.5:
                penalizacion += 5
        except Exception:
            pass

    # CPU: si consume más del 30% sostenido
    if cpu_pct > 60:
        penalizacion += 25
    elif cpu_pct > 30:
        penalizacion += 10
    elif cpu_pct > 15:
        penalizacion += 5

    # Procesos críticos nunca bajan de 70 aunque consuman
    if critico:
        penalizacion = min(penalizacion, score_base - 70)

    score_final = max(0, min(100, score_base - penalizacion))

    # ── ESTADO SEGÚN SCORE ───────────────────────────
    if score_final >= 70:
        estado = "saludable"
    elif score_final >= 50:
        estado = "vigilar"
    elif score_final >= 30:
        estado = "alerta"
    else:
        estado = "critico"

    # ── ACCIÓN RECOMENDADA ────────────────────────────
    accion = info.get("accion_si_alto", "ignorar")
    if score_final >= 70:
        accion = "ignorar"  # aunque tenga acción, si está bien, no hacer nada

    return {
        "nombre":      nombre,
        "score":       score_final,
        "categoria":   info.get("cat", "desconocido"),
        "critico":     critico,
        "descripcion": info.get("desc", "Proceso en ejecución."),
        "accion":      accion,
        "penalizacion": penalizacion,
        "estado":      estado,
    }

def _pct_a_mb(pct: float) -> float:
    """Convierte porcentaje de RAM a MB reales"""
    try:
        total_mb = psutil.virtual_memory().total / (1024**2)
        return (pct / 100) * total_mb
    except Exception:
        return 0.0

# ------------------------------------------
#   SNAPSHOT COMPLETO DEL SISTEMA
#   Ada analiza todos sus procesos a la vez
# ------------------------------------------

def snapshot_procesos() -> dict:
    """
    Analiza TODOS los procesos activos y retorna un resumen.

    Retorna:
    {
        "total": int,
        "score_promedio": int,
        "criticos": int,
        "alertas": [...],      ← procesos con score < 50
        "basura": [...],       ← procesos cat=basura activos
        "top_ram": [...],      ← los 5 que más RAM usan
        "top_cpu": [...],      ← los 5 que más CPU usan
        "procesos": {nombre: resultado_calcular_score}
    }
    """
    if not _base:
        cargar_base()

    resultados   = {}
    alertas      = []
    basura       = []
    scores       = []
    procs_ram    = []
    procs_cpu    = []

    for info in listar_procesos(['pid', 'name', 'memory_percent', 'cpu_percent']):
        try:
            nombre  = info.get('name') or "unknown"
            ram_pct = info.get('memory_percent') or 0
            cpu_pct = info.get('cpu_percent') or 0

            resultado = calcular_score_proceso(nombre, ram_pct, cpu_pct)
            resultados[nombre] = resultado
            scores.append(resultado["score"])

            if resultado["estado"] in ("alerta", "critico"):
                alertas.append({
                    "nombre": nombre,
                    "score":  resultado["score"],
                    "accion": resultado["accion"],
                    "ram":    round(ram_pct, 1),
                    "cpu":    round(cpu_pct, 1),
                })

            if resultado["categoria"] == "basura":
                basura.append(nombre)

            if ram_pct > 1.0:
                procs_ram.append((nombre, round(ram_pct, 1)))

            if cpu_pct > 5.0:
                procs_cpu.append((nombre, round(cpu_pct, 1)))

        except Exception:
            continue

    score_promedio = int(sum(scores) / len(scores)) if scores else 50
    procs_ram.sort(key=lambda x: x[1], reverse=True)
    procs_cpu.sort(key=lambda x: x[1], reverse=True)
    alertas.sort(key=lambda x: x["score"])

    return {
        "total":          len(resultados),
        "score_promedio": score_promedio,
        "criticos":       sum(1 for r in resultados.values() if r["critico"]),
        "alertas":        alertas[:5],
        "basura":         basura,
        "top_ram":        procs_ram[:5],
        "top_cpu":        procs_cpu[:5],
        "procesos":       resultados,
    }

# ------------------------------------------
#   SEVERIDAD DEL DIAGNÓSTICO — determinística
#   NO usa Groq acá. Esto se calcula con reglas
#   fijas para que sea reproducible y auditable:
#   un LLM no debería decidir qué tan grave es
#   un disco muriéndose, eso lo decide el dato.
#   Groq entra DESPUÉS, ya con esto resuelto,
#   para razonar QUÉ HACER con el contexto.
# ------------------------------------------

def _listar_candidatos_severidad(ssd: dict, ram: dict, cpu: dict,
                                  eventos: list, predicciones: list,
                                  bateria: dict = None, drivers: dict = None) -> list:
    """
    Toda la lógica de umbrales vive acá — es la ÚNICA fuente de
    verdad de qué cuenta como anomalía y qué tan grave es. Tanto
    calcular_severidad_diagnostico() (se queda con la peor) como
    listar_anomalias() (usa todas, para el triage que ve Groq) llaman
    a esta misma función, así que ambas siempre están de acuerdo
    sobre qué es "normal" y qué no.

    Retorna lista de tuplas (puntaje, componente, detalle) — vacía si
    no hay ninguna anomalía real.
    """
    candidatos = []  # (puntaje, componente, detalle)

    # --- SSD ---
    ssd_estado = ssd.get("estado", "desconocido")
    if ssd_estado == "critico":
        candidatos.append((95, "ssd", "el disco reporta estado crítico o casi sin espacio"))
    elif ssd_estado == "advertencia":
        candidatos.append((55, "ssd", "el disco tiene poco espacio libre"))

    # --- RAM ---
    ram_estado = ram.get("estado", "saludable")
    if ram_estado == "critica":
        candidatos.append((85, "ram", "RAM en presión crítica, usando swap"))
    elif ram_estado == "alta":
        candidatos.append((55, "ram", "RAM bajo presión alta"))
    elif ram_estado == "moderada":
        candidatos.append((30, "ram", "RAM con presión moderada"))

    # --- CPU ---
    cpu_estado = cpu.get("estado", "saludable")
    if cpu_estado == "saturado":
        candidatos.append((60, "cpu", "todos los núcleos saturados, carga real"))
    elif cpu_estado == "desbalanceado":
        candidatos.append((45, "cpu", "un proceso acaparando un núcleo"))

    # --- Batería (mismo tratamiento que CPU: entra a la severidad,
    #     nunca dispara una reparación automática) ---
    if bateria:
        bat_estado = bateria.get("estado", "desconocido")
        salud_pct = bateria.get("salud_pct")
        if bat_estado == "critica":
            candidatos.append((78, "bateria", f"batería crítica, retiene solo {salud_pct}% de su capacidad"))
        elif bat_estado == "degradada":
            candidatos.append((48, "bateria", f"batería degradada al {salud_pct}%"))

    # --- Drivers ---
    if drivers:
        no_firmados = drivers.get("no_firmados", 0)
        if no_firmados >= 3:
            candidatos.append((50, "drivers", f"{no_firmados} drivers sin firma digital"))
        elif no_firmados >= 1:
            candidatos.append((30, "drivers", f"{no_firmados} driver(s) sin firma digital"))

    # --- Eventos del Event Log ---
    # nivel 1/2 = crítico/error, 3 = advertencia (mismo criterio que
    # resumir_eventos(), por número de nivel, no por texto en inglés/español)
    criticos_ev = [e for e in (eventos or []) if e.get("nivel") in (1, 2)]
    if len(criticos_ev) >= 5:
        candidatos.append((70, "eventos", f"{len(criticos_ev)} errores en el Event Log en 24h"))
    elif len(criticos_ev) >= 1:
        candidatos.append((40, "eventos", f"{len(criticos_ev)} error(es) en el Event Log en 24h"))

    # --- Predicciones del predictor de tendencias ---
    for p in (predicciones or []):
        urgencia = p.get("urgencia")
        tipo = p.get("tipo", "tendencia")
        if urgencia == "alta":
            candidatos.append((50, f"prediccion_{tipo}", f"tendencia de {tipo} con urgencia alta"))
        elif urgencia == "media":
            candidatos.append((25, f"prediccion_{tipo}", f"tendencia de {tipo} con urgencia media"))

    return candidatos


def listar_anomalias(ssd: dict, ram: dict, cpu: dict,
                      eventos: list, predicciones: list,
                      bateria: dict = None, drivers: dict = None) -> list:
    """
    Triage puro: solo lo que está MAL, con números reales, ordenado
    de más a menos grave. Nada de "RAM: sin problemas" — si un
    componente está saludable, simplemente no aparece acá. Esto es
    lo que arma medico.py para pasarle a Groq en vez del informe
    completo de siempre — así Groq no tiene que leer 6 líneas para
    encontrar la 1 que importa.

    Retorna lista de strings, ej: ["el disco tiene poco espacio libre", ...]
    Vacía si todo está bien.
    """
    candidatos = _listar_candidatos_severidad(ssd, ram, cpu, eventos, predicciones, bateria, drivers)
    candidatos.sort(key=lambda c: c[0], reverse=True)
    return [detalle for _, _, detalle in candidatos]


def calcular_severidad_diagnostico(ssd: dict, ram: dict, cpu: dict,
                                     eventos: list, predicciones: list,
                                     bateria: dict = None, drivers: dict = None) -> dict:
    """
    Combina ssd/ram/cpu/eventos/predicciones (las mismas estructuras
    que ya arma medico.py) en un solo puntaje de severidad 0-100 y
    una categoría, para que el médico autónomo sepa qué tan urgente
    es la situación ANTES de preguntarle a Groq qué hacer.

    bateria y drivers son opcionales (default None) para no romper a
    quien ya llamaba esta función antes de que existieran — mismo
    tratamiento que se le dio a CPU: entran al mismo cálculo de
    severidad y al mismo resumen que ve Groq. A diferencia de CPU/RAM,
    no hay ninguna reparación automática de la lista blanca para
    batería o drivers (degradación de batería es un problema de
    hardware, y tocar drivers sin una acción probada es riesgoso) —
    así que esto solo alimenta severidad y el diagnóstico que Ada le
    comunica al usuario, nunca dispara una acción nueva por sí solo.

    Retorna:
    {
        "puntaje": int (0-100),
        "categoria": "critico"|"alto"|"medio"|"bajo",
        "componente_dominante": str,  ← qué aportó el mayor puntaje
        "voz": str                    ← línea corta para el prompt a Groq
    }
    """
    candidatos = _listar_candidatos_severidad(ssd, ram, cpu, eventos, predicciones, bateria, drivers)

    if not candidatos:
        return {
            "puntaje": 0,
            "categoria": "bajo",
            "componente_dominante": "ninguno",
            "voz": "Severidad: baja. No hay señales preocupantes ahora mismo.",
        }

    puntaje, componente, detalle = max(candidatos, key=lambda c: c[0])

    if puntaje >= 90:
        categoria = "critico"
    elif puntaje >= 65:
        categoria = "alto"
    elif puntaje >= 35:
        categoria = "medio"
    else:
        categoria = "bajo"

    return {
        "puntaje": puntaje,
        "categoria": categoria,
        "componente_dominante": componente,
        "voz": f"Severidad: {categoria} ({puntaje}/100) — {detalle}.",
    }

# ------------------------------------------
#   NECESITA GROQ?
#   Ada decide si vale la pena gastar API
# ------------------------------------------

def necesita_groq(nombre: str, ram_pct: float, cpu_pct: float) -> bool:
    """
    Retorna True solo si Ada realmente necesita preguntarle a Groq.
    Problema 16: reducir llamadas innecesarias.
    """
    if not _base:
        cargar_base()

    info = _buscar_proceso(nombre)

    # Si lo conocemos y no es unknown → decidir local
    if info and info.get("cat") != "desconocido":
        resultado = calcular_score_proceso(nombre, ram_pct, cpu_pct)
        # Solo consultar Groq si:
        # 1. Es completamente desconocido (cat=desconocido)
        # 2. O es sospechoso Y consume mucho (score < 30)
        if resultado["score"] >= 30:
            return False
        if resultado["critico"]:
            return False
        return True  # Score muy bajo en proceso conocido → confirmar con Groq

    # Proceso completamente desconocido
    return True
