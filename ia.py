# ==========================================
#   ia.py v3.3 - Cerebro de Ada
#   Dos modelos Groq según urgencia:
#   - Principal (70B): preguntas de Alejandro
#   - Rápido (8B): análisis internos silenciosos
#   Médico autónomo: planificador MULTI-ACCIÓN,
#   hasta 2 reparaciones por ciclo si resuelven
#   problemas distintos.
# ==========================================

import os
import json
import logging
import threading
from groq import Groq
from datetime import datetime
from perfil_pc import PERFIL
from config import (GROQ_MODELO_PRINCIPAL, GROQ_MODELO_RAPIDO,
                    GROQ_MAX_TOKENS_PUBLICO, GROQ_MAX_TOKENS_INTERNO,
                    GROQ_TIMEOUT_PRINCIPAL_SEG, GROQ_TIMEOUT_RAPIDO_SEG)
from puntuacion import calcular_score_proceso, necesita_groq, cargar_base

BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
CONOCIMIENTO_PATH = os.path.join(BASE_DIR, "conocimiento.json")
MAX_KB            = 512 * 1024

groq_client = None  # type: ignore
GROQ_ACTIVO = False

# ------------------------------------------
#   PROMPTS QUIRÚRGICOS
# ------------------------------------------

def _construir_prompt_maestro():
    cpu  = PERFIL["cpu"]["nombre"]
    ram  = PERFIL["ram"]["total_gb"]
    ssd  = PERFIL["disco"]["modelo"]
    gpu  = PERFIL["gpu"]["nombre"]
    meta = PERFIL["ram"]["meta_libre_para_programar_gb"]
    so   = PERFIL["sistema_operativo"]["nombre"]
    return (
        f"Asistente de Ada para {PERFIL['nombre_pc']} — {cpu} {ram}GB RAM {so}. "
        f"GPU {gpu} comparte RAM. SSD {ssd}. "
        f"Propósito: programación con VS Code y Python. "
        f"REGLAS: español, máximo 2 oraciones, software siempre liviano y gratuito de calidad mundial, "
        f"nunca tocar procesos críticos Windows, nunca desfragmentar SSD, "
        f"meta mantener {meta}GB+ RAM libre para VS Code."
    )

PROMPT_MAESTRO = _construir_prompt_maestro()

# Modelo rápido — solo para análisis internos
PROMPT_INMUNE = (
    "Sistema inmune PC Win11. Solo JSON válido sin texto extra: "
    '{"amenaza":bool,"tipo":"malware|basura|innecesario|seguro|critico",'
    '"accion":"eliminar|terminar|ignorar|alertar","razon":"max 6 palabras","riesgo":"alto|medio|bajo|ninguno"}'
)

# Recomendador de software — prioridad máxima
PROMPT_SOFTWARE = (
    "PC: Lenovo i5-8350U 16GB RAM GPU integrada SSD NVMe 256GB Win11. Programación. "
    "Recomienda software MÁS LIVIANO y MEJOR CALIDAD MUNDIAL. "
    "Solo JSON: "
    '{"nombre":"","peso_mb":0,"para_que":"max 8 palabras",'
    '"por_que_mejor":"max 8 palabras","url_oficial":""}'
)

# ------------------------------------------
#   MÉDICO AUTÓNOMO — Groq elige, Ada ejecuta
#   Lista blanca cerrada: Groq NUNCA manda un
#   comando libre, solo una palabra de esta
#   lista. Ada es la única que decide qué
#   función de Python corre según esa palabra.
# ------------------------------------------
ACCIONES_MEDICO_VALIDAS = [
    "reparar_archivos_sistema", "limpiar_winsxs", "limpiar_cache_iconos",
    "desactivar_servicios_basura", "reparar_red", "actualizar_con_winget",
    "ninguna"
]

def _construir_prompt_medico(historial_por_accion: dict = None) -> str:
    """
    Arma el system prompt del médico autónomo DINÁMICAMENTE desde
    CATALOGO_ACCIONES (auto_reparador.py), en vez de tener la lista
    de acciones hardcodeada como texto plano. Groq deja de tener que
    adivinar qué hace cada acción por su nombre — recibe qué hace,
    cuándo aplica, y el historial real de éxito EN ESTE EQUIPO pegado
    a cada una, no suelto en un párrafo aparte.

    historial_por_accion: {"limpiar_winsxs": {"intentos":5,"exitos":4}, ...}
    Solo se listan acciones con intentos > 0 — sin data, no hay nada
    útil que agregar y solo sería ruido.

    v3.3: planificador MULTI-ACCIÓN. Antes Groq elegía una sola acción
    por ciclo aunque el triage mostrara dos problemas independientes
    (ej. SSD lleno Y RAM bajo presión) — tocaba esperar al ciclo
    siguiente para el segundo. Ahora puede devolver hasta 2 acciones
    en el mismo ciclo, pero SOLO si cada una resuelve una anomalía
    DISTINTA — nunca dos acciones para el mismo problema. Cada acción
    del plan sigue pasando, una por una, por las mismas reglas de
    seguridad de siempre en medico.py (cooldown, tasa de éxito,
    confirmación por persistencia, riesgo alto = humano).
    """
    from auto_reparador import CATALOGO_ACCIONES
    historial_por_accion = historial_por_accion or {}

    lineas = []
    for nombre, d in CATALOGO_ACCIONES.items():
        linea = f'- {nombre} (riesgo base {d["riesgo_base"]}): {d["que_hace"]}. Usar cuando: {d["usar_cuando"]}.'
        h = historial_por_accion.get(nombre)
        if h and h.get("intentos", 0) > 0:
            tipo_evidencia = ("para este mismo tipo de problema" if h.get("especifico_de_este_componente")
                               else "en general, para cualquier problema")
            linea += (f' Historial {tipo_evidencia}: {h["exitos"]}/{h["intentos"]} exitos recientes.')
        lineas.append(linea)

    return (
        "Eres el planificador del medico autonomo de Ada, sistema inmune de un PC Win11.\n"
        "Vas a recibir SOLO los problemas reales detectados ahora (sin ruido de lo que esta bien).\n"
        "Herramientas disponibles (nunca uses ninguna fuera de esta lista):\n"
        + "\n".join(lineas) + "\n\n"
        "Podes proponer UNA o DOS acciones en el mismo ciclo, nunca mas de dos. "
        "Agrega una segunda accion SOLO si resuelve una anomalia DIFERENTE a la primera "
        "(ej. SSD lleno + RAM bajo presion = dos acciones validas; dos sintomas del mismo "
        "problema = una sola accion). Nunca repitas la misma accion dos veces en el plan. "
        "El orden importa: la primera se ejecuta primero.\n"
        "La PRIMERA accion del plan puede incluir opcionalmente una 'alternativa' (mismo "
        "formato: accion, riesgo, razon) -- un plan B que Ada va a intentar SOLO si, despues "
        "de ejecutar la principal, vuelve a medir el mismo componente y el problema sigue "
        "presente. Usala cuando dos acciones del catalogo podrian resolver el mismo problema "
        "y preferis que Ada lo compruebe con datos reales en vez de asumir que la primera "
        "alcanzo. La alternativa debe ser distinta a la accion principal. No le pongas "
        "alternativa a la segunda accion del plan (todavia no se puede verificar).\n"
        "Antes de responder, razona brevemente que problema especifico resuelve cada accion "
        "elegida y si el historial la respalda. Responde SOLO JSON, sin texto extra:\n"
        '{"razonamiento":"max 30 palabras, para tu propio registro interno",'
        '"plan":[{"accion":"<nombre_exacto_del_catalogo>","riesgo":"bajo|medio|alto",'
        '"razon":"max 12 palabras, para explicarle a Alejandro",'
        '"alternativa":{"accion":"...","riesgo":"...","razon":"..."} o null}]}\n'
        "Si no hay ningun problema real arriba que estas herramientas resuelvan, "
        'responde "plan":[] (lista vacia) — nunca inventes una accion fuera del catalogo. '
        "Si dudas entre proponer o no una accion, no la propongas."
    )

def _intentar_modelo_medico(prompt: str, resumen_diagnostico: str, modelo: str,
                             max_tokens: int, timeout_seg: float) -> dict:
    """
    Un solo intento contra un modelo Groq puntual, con timeout propio.
    Levanta la excepción tal cual si falla (timeout, rate limit, JSON
    inválido, lo que sea) -- decidir qué hacer con ese fallo es
    responsabilidad de diagnosticar_y_recomendar(), no de esta función.

    with_options(timeout=...) en vez de pasar timeout directo a
    .create(): es la forma estándar de estos clientes generados
    (mismo patrón que el SDK de OpenAI, del que el de Groq deriva) de
    fijar un timeout puntual para UNA llamada sin tocar el timeout
    default del cliente global.
    """
    r = groq_client.with_options(timeout=timeout_seg).chat.completions.create(  # type: ignore
        model       = modelo,
        messages    = [
            {"role": "system", "content": prompt},
            {"role": "user",   "content": resumen_diagnostico}
        ],
        max_tokens  = max_tokens,
        temperature = 0.1
    )
    texto = (r.choices[0].message.content or "").strip()
    texto = texto.replace("```json", "").replace("```", "").strip()
    return json.loads(texto)


def _plan_heuristico_local(componente: str, historial_por_accion: dict = None) -> list:
    """
    ÚLTIMO escalón de la degradación elegante -- sin ningún modelo de
    IA. Se usa solo cuando ni Groq 70B ni Groq 8B respondieron (sin
    internet, Groq caído, o sin API key configurada).

    No reemplaza a memoria.decision_local_confiable() -- esa ya corrió
    ANTES en medico.autodiagnostico_y_reparacion() y, si estamos acá,
    es porque no encontró evidencia suficiente para decidir con su
    propio umbral (más exigente). Acá el bar es más bajo A PROPÓSITO
    -- es el último recurso cuando no hay nadie más a quien
    preguntarle, no el camino normal -- pero las salvaguardas nunca se
    relajan:

      - Nunca propone riesgo medio o alto -- sin ningún modelo que
        juzgue el contexto, solo lo más inofensivo del catálogo es
        aceptable para actuar a ciegas.
      - Nunca propone una acción sin un mínimo de evidencia real
        (>= 2 intentos) y un piso de 60% de éxito -- sin eso, mejor no
        hacer nada que adivinar.
      - Como mucho UNA acción -- sin ningún modelo que razone un plan
        de varios pasos, no se arma nada compuesto.
      - Nunca una acción en cooldown -- misma regla que en cualquier
        otro camino de decisión.

    Retorna una lista con a lo sumo un dict {"accion","riesgo","razon"},
    o [] si ninguna opción cumple las condiciones de arriba (en cuyo
    caso Ada simplemente no actúa este ciclo, y lo dice).
    """
    from auto_reparador import CATALOGO_ACCIONES

    if not componente or not historial_por_accion:
        return []

    candidatos = []
    for nombre_accion, datos in historial_por_accion.items():
        if CATALOGO_ACCIONES.get(nombre_accion, {}).get("riesgo_base") != "bajo":
            continue
        if datos.get("en_cooldown"):
            continue
        intentos = datos.get("intentos", 0)
        exitos = datos.get("exitos", 0)
        if intentos < 2:
            continue
        porcentaje = exitos / intentos
        if porcentaje < 0.6:
            continue
        candidatos.append((nombre_accion, porcentaje, intentos))

    if not candidatos:
        return []

    # Mejor porcentaje primero; ante empate, el que tenga más intentos
    # detrás (más evidencia real sosteniendo el mismo porcentaje).
    candidatos.sort(key=lambda c: (c[1], c[2]), reverse=True)
    mejor_accion, mejor_pct, intentos = candidatos[0]

    return [{
        "accion": mejor_accion,
        "riesgo": "bajo",
        "razon": (f"Sin Groq disponible -- heurística local sin IA: {mejor_accion} tuvo "
                  f"{round(mejor_pct * 100, 1)}% de éxito en {intentos} intentos, riesgo bajo."),
    }]


def diagnosticar_y_recomendar(resumen_diagnostico: str, historial_por_accion: dict = None,
                               componente: str = None) -> dict:
    """
    Le pasa a Groq un resumen de SOLO LOS PROBLEMAS REALES (triage,
    armado por medico.py) y le pide planificar hasta 2 acciones de
    una lista cerrada de reparaciones que YA existen y ya están
    probadas en auto_reparador.py — nunca un comando libre ni texto
    para ejecutar. El prompt se arma dinámicamente con el catálogo
    real de herramientas y el historial de éxito de cada una en este
    equipo, para que Groq decida con evidencia y no adivinando por
    el nombre.

    v3.3: devuelve {"plan": [...]} en vez de una sola acción. Cada
    entrada del plan sigue siendo validada UNA POR UNA contra la
    lista blanca (ACCIONES_MEDICO_VALIDAS, sin "ninguna" — un plan
    vacío ya significa "no hacer nada"). Reglas de saneamiento, en
    este orden:
      1. Descartar cualquier entrada cuya "accion" no esté en la
         lista blanca (fail-safe: mejor omitir que ejecutar algo
         inventado).
      2. Descartar duplicados, quedándose con la primera aparición
         (Groq ya tiene la instrucción de no repetir, esto es la
         red de seguridad si igual lo hace).
      3. Truncar a 2 acciones máximo, sin importar cuántas haya
         devuelto Groq — el límite lo decide Ada, no el modelo.

    v3.4: la PRIMERA acción del plan puede traer una "alternativa"
    opcional (plan B) — medico.py la va a intentar solo si, después
    de ejecutar la principal, vuelve a medir el sensor real y el
    problema sigue presente. Se valida igual que cualquier acción
    (lista blanca, no repetida) y solo se conserva para el primer
    elemento del plan.

    Si Groq falla, no responde JSON válido, o el plan queda vacío
    después de filtrar, se trata como "sin acciones" por seguridad:
    mejor no actuar que actuar mal.

    v4.0: DEGRADACIÓN ELEGANTE en tres escalones, para que un
    problema de red o un Groq caído no deje a Ada completamente
    ciega:
      1. Groq 70B (GROQ_MODELO_PRINCIPAL) -- el escalón normal.
      2. Si falla o da timeout (GROQ_TIMEOUT_PRINCIPAL_SEG) -> Groq
         8B (GROQ_MODELO_RAPIDO) -- mismo prompt, menos preciso pero
         sigue siendo una IA real razonando sobre el problema.
      3. Si también falla o da timeout (GROQ_TIMEOUT_RAPIDO_SEG), o
         si no hay API key configurada -> heurística local
         determinista, SIN ningún modelo (_plan_heuristico_local) --
         como mucho una acción de riesgo bajo con evidencia real, o
         directamente no actuar.

    El resultado siempre incluye "nivel_ia" ("groq_70b" / "groq_8b" /
    "heuristica_local" / "ninguno") para que quede registrado con qué
    nivel de degradación se tomó cada decisión -- transparencia real,
    no solo "algo respondió".
    """
    resultado_seguro = {"plan": [], "razonamiento": "sin diagnostico claro", "nivel_ia": "ninguno"}
    if not GROQ_ACTIVO:
        # Ni siquiera hay API key configurada -- vamos directo al
        # último escalón, no tiene sentido intentar Groq de ningún
        # tamaño.
        plan = _plan_heuristico_local(componente, historial_por_accion)
        return {"plan": plan,
                "razonamiento": "Groq no configurado -- decisión con heurística local, sin IA",
                "nivel_ia": "heuristica_local" if plan else "ninguno"}

    prompt = _construir_prompt_medico(historial_por_accion)
    data = None
    nivel_usado = None

    try:
        data = _intentar_modelo_medico(prompt, resumen_diagnostico, GROQ_MODELO_PRINCIPAL,
                                        max_tokens=260, timeout_seg=GROQ_TIMEOUT_PRINCIPAL_SEG)
        nivel_usado = "groq_70b"
    except Exception as e:
        logging.warning(f"[MÉDICO IA] Groq 70B no respondió ({type(e).__name__}: {e}) -- "
                        f"probando el modelo rápido (8B).")
        try:
            data = _intentar_modelo_medico(prompt, resumen_diagnostico, GROQ_MODELO_RAPIDO,
                                            max_tokens=220, timeout_seg=GROQ_TIMEOUT_RAPIDO_SEG)
            nivel_usado = "groq_8b"
        except Exception as e2:
            logging.warning(f"[MÉDICO IA] Groq 8B tampoco respondió ({type(e2).__name__}: {e2}) -- "
                            f"cayendo a heurística local, sin ningún modelo de IA.")

    if data is None:
        plan = _plan_heuristico_local(componente, historial_por_accion)
        razon = ("Ni Groq 70B ni 8B respondieron -- decisión con heurística local, sin IA"
                  if plan else
                  "Ni Groq 70B ni 8B respondieron, y no hay evidencia local suficiente -- no se actuó")
        return {"plan": plan, "razonamiento": razon,
                "nivel_ia": "heuristica_local" if plan else "ninguno"}

    try:
        plan_crudo = data.get("plan", [])
        if not isinstance(plan_crudo, list):
            resultado_seguro["nivel_ia"] = nivel_usado
            return resultado_seguro

        plan_validado = []
        vistas = set()
        for item in plan_crudo:
            if not isinstance(item, dict):
                continue
            accion = item.get("accion")
            if accion not in ACCIONES_MEDICO_VALIDAS or accion == "ninguna":
                continue
            if accion in vistas:
                continue
            vistas.add(accion)

            entrada = {
                "accion": accion,
                "riesgo": item.get("riesgo", "medio"),
                "razon":  item.get("razon", ""),
            }

            # La alternativa (plan B si la principal no resuelve) solo
            # se valida y se guarda para la PRIMERA acción del plan --
            # es la única para la que medico.py puede verificar el
            # resultado real después, porque coincide con el
            # componente_dominante de todo el ciclo. Una segunda
            # acción del plan ataca un problema distinto y no hay
            # forma de verificarla todavía, así que cargarle una
            # alternativa no tendría ningún efecto real.
            if len(plan_validado) == 0:
                alt = item.get("alternativa")
                if isinstance(alt, dict):
                    alt_accion = alt.get("accion")
                    if (alt_accion in ACCIONES_MEDICO_VALIDAS and alt_accion != "ninguna"
                            and alt_accion != accion):
                        entrada["alternativa"] = {
                            "accion": alt_accion,
                            "riesgo": alt.get("riesgo", "medio"),
                            "razon":  alt.get("razon", ""),
                        }

            plan_validado.append(entrada)
            if len(plan_validado) >= 2:
                break

        return {"plan": plan_validado, "razonamiento": data.get("razonamiento", ""),
                "nivel_ia": nivel_usado}
    except Exception as e:
        logging.warning(f"[MÉDICO IA] Error de saneamiento sobre la respuesta de {nivel_usado}: "
                        f"{type(e).__name__}: {e}")
        resultado_seguro["nivel_ia"] = nivel_usado
        return resultado_seguro

# ------------------------------------------
#   INICIALIZACIÓN
# ------------------------------------------

def iniciar_groq(api_key):
    global groq_client, GROQ_ACTIVO
    try:
        groq_client = Groq(api_key=api_key)
        GROQ_ACTIVO = True
        print(f"✅ Groq conectado — modelo principal: {GROQ_MODELO_PRINCIPAL}")
        print(f"   Modelo rápido interno: {GROQ_MODELO_RAPIDO}")
        cargar_base()
    except Exception as e:
        GROQ_ACTIVO = False
        print(f"⚠️ Groq no disponible: {e}")

# ------------------------------------------
#   CONSULTA PÚBLICA — Alejandro pregunta
#   Usa modelo potente 70B
# ------------------------------------------

def preguntar_groq(pregunta, contexto_extra=""):
    from memoria import buscar_cache_groq, guardar_cache_groq

    # Caché primero — sin gastar API
    pregunta_normalizada = pregunta.lower().strip()
    cached = buscar_cache_groq(pregunta_normalizada)
    if cached:
        return cached

    if not GROQ_ACTIVO:
        return "No tengo conexión con Groq. Puedo hacer tareas básicas sin internet."

    try:
        msg = pregunta if not contexto_extra else f"{contexto_extra}\n{pregunta}"
        r   = groq_client.chat.completions.create(  # type: ignore
            model       = GROQ_MODELO_PRINCIPAL,
            messages    = [
                {"role": "system", "content": PROMPT_MAESTRO},
                {"role": "user",   "content": msg}
            ],
            max_tokens  = GROQ_MAX_TOKENS_PUBLICO,
            temperature = 0.4
        )
        resultado = (r.choices[0].message.content or "").strip()

        # Guardar en caché si es técnica
        if any(p in pregunta_normalizada for p in
               ["proceso", "programa", "ram", "cpu", "disco", "driver", "windows", "instalar"]):
            threading.Thread(
                target=guardar_cache_groq,
                args=(pregunta_normalizada, resultado),
                daemon=True
            ).start()

        return resultado

    except Exception as e:
        print(f"[ERROR Groq público] {type(e).__name__}: {e}")
        return "No pude conectarme con Groq ahora mismo."

# ------------------------------------------
#   CONSULTA INTERNA — Ada piensa sola
#   Usa modelo rápido 8B — más liviano
# ------------------------------------------

def consulta_interna(pregunta_tecnica):
    """Ada se pregunta algo sola — modelo rápido, sin gastar cuota"""
    if not GROQ_ACTIVO:
        return ""
    try:
        r = groq_client.chat.completions.create(  # type: ignore
            model       = GROQ_MODELO_RAPIDO,
            messages    = [
                {"role": "system", "content": PROMPT_MAESTRO},
                {"role": "user",   "content": pregunta_tecnica}
            ],
            max_tokens  = GROQ_MAX_TOKENS_INTERNO,
            temperature = 0.2
        )
        return (r.choices[0].message.content or "").strip()
    except Exception:
        return ""

# ------------------------------------------
#   ANÁLISIS SILENCIOSO DE PROCESOS
#   Usa modelo rápido 8B
# ------------------------------------------

def analizar_proceso_silencioso(nombre, memoria_pct, cpu_pct):
    # Primero decide local — sin gastar Groq
    if not necesita_groq(nombre, memoria_pct, cpu_pct):
        resultado = calcular_score_proceso(nombre, memoria_pct, cpu_pct)
        return {
            "amenaza": resultado["score"] < 30,
            "tipo":    resultado["categoria"],
            "accion":  resultado["accion"],
            "razon":   resultado["descripcion"][:50],
            "riesgo":  "alto" if resultado["score"] < 30 else
                       "medio" if resultado["score"] < 50 else "ninguno"
        }
    # Solo llega aquí si es proceso desconocido o score muy bajo
    if not GROQ_ACTIVO:
        return {"amenaza": False, "tipo": "desconocido", "accion": "ignorar",
                "razon": "offline", "riesgo": "ninguno"}
    try:
        prompt = f"Proceso: {nombre} RAM:{memoria_pct:.1f}% CPU:{cpu_pct:.1f}%"
        r = groq_client.chat.completions.create(
            model       = GROQ_MODELO_RAPIDO,
            messages    = [
                {"role": "system", "content": PROMPT_INMUNE},
                {"role": "user",   "content": prompt}
            ],
            max_tokens  = 100,
            temperature = 0.1
        )
        texto = (r.choices[0].message.content or "").strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        return json.loads(texto)
    except Exception:
        # Groq falló — respuesta segura por defecto
        return {"amenaza": False, "tipo": "seguro", "accion": "ignorar",
                "razon": "error", "riesgo": "ninguno"} 

# ------------------------------------------
#   RECOMENDADOR DE SOFTWARE LIVIANO
#   PRIORIDAD MÁXIMA — modelo potente 70B
# ------------------------------------------

def recomendar_software_liviano(tarea):
    if not GROQ_ACTIVO:
        return "Necesito internet para buscar la mejor recomendación."
    try:
        r = groq_client.chat.completions.create(  # type: ignore
            model       = GROQ_MODELO_PRINCIPAL,
            messages    = [
                {"role": "system", "content": PROMPT_SOFTWARE},
                {"role": "user",   "content": f"Tarea: {tarea}"}
            ],
            max_tokens  = 150,
            temperature = 0.3
        )
        texto = (r.choices[0].message.content or "").strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        import re
        match = re.search(r"\{.*?\}", texto, re.DOTALL)
        if match:
            texto = match.group(0)
        try:
            data = json.loads(texto)
            return (
                f"El mejor software liviano para {tarea} es {data['nombre']}. "
                f"Pesa aproximadamente {data['peso_mb']} megabytes. "
                f"Sirve para {data['para_que']}. "
                f"Es el mejor porque {data['por_que_mejor']}. "
                f"Descárgalo en {data['url_oficial']}. "
                f"¿Quieres que abra la página de descarga?"
            ), data.get('url_oficial', '')
        except Exception:
            return texto, ''
    except Exception as e:
        return f"No pude buscar recomendaciones: {e}", ''

# ------------------------------------------
#   AUTOCONOCIMIENTO AL ARRANCAR
# ------------------------------------------

def autoconocimiento_pc():
    import psutil
    from memoria import registrar_salud_ssd

    ram   = psutil.virtual_memory()
    disco = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
    cpu   = psutil.cpu_percent(interval=1)
    bat   = psutil.sensors_battery()

    libre_gb = round(ram.available / (1024**3), 1)
    disco_gb = round(disco.free    / (1024**3), 1)

    registrar_salud_ssd(disco_gb, round(disco.total / (1024**3), 1))

    # Tip interno con modelo rápido
    if GROQ_ACTIVO:
        tip = consulta_interna(
            f"RAM:{libre_gb}GB libre disco:{disco_gb}GB CPU:{cpu:.0f}% "
            f"GPU integrada comparte RAM. Una acción concreta para optimizar."
        )
        if tip:
            _guardar_conocimiento("tip_arranque", tip)

    estado_bat = ""
    if bat:
        estado_bat = f" Batería al {int(bat.percent)} por ciento."

    nota_ram = "lista"
    if libre_gb < 6:
        nota_ram = "justa, optimizando ahora"

    resumen = (
        f"Sistema listo. RAM {nota_ram}: {libre_gb} gigabytes libres. "
        f"Disco: {disco_gb} gigabytes libres.{estado_bat}"
    )
    return resumen, {"ram_libre_gb": libre_gb, "disco_libre_gb": disco_gb, "cpu_pct": cpu}

# ------------------------------------------
#   HELPERS
# ------------------------------------------

def es_proceso_critico(nombre):
    return any(c in nombre.lower() for c in PERFIL["procesos_criticos"])

def _guardar_conocimiento(clave, valor):
    try:
        datos = {}
        if os.path.exists(CONOCIMIENTO_PATH):
            with open(CONOCIMIENTO_PATH, 'r', encoding='utf-8') as f:
                datos = json.load(f)
        datos[clave] = {"valor": str(valor)[:200], "fecha": datetime.now().strftime("%Y-%m-%d")}
        contenido    = json.dumps(datos, ensure_ascii=False)
        if len(contenido.encode()) > MAX_KB:
            claves = sorted(datos.keys(), key=lambda k: datos[k].get("fecha", ""))
            for vieja in claves[:max(1, len(claves)//3)]:
                del datos[vieja]
        with open(CONOCIMIENTO_PATH, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

