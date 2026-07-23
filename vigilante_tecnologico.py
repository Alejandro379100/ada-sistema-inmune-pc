# ==========================================
#   vigilante_tecnologico.py v1.0
#   Su único trabajo: vigilar cambios de
#   versión/build de Windows, para que
#   actualizar Ada después de un Windows
#   Update sea revisar una lista concreta,
#   no adivinar desde cero qué se rompió.
# ==========================================

import os
import json
import logging
import winreg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(BASE_DIR, "privado", "version_os_snapshot.json")

CLAVE_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"

# Módulos de Ada que dependen directamente del sistema operativo
# (WMI, PowerShell, subprocess, rutas del registro) -- son los que
# más probabilidad tienen de romperse con una actualización de
# Windows, porque dependen de que ciertos comandos o formatos de
# salida se mantengan iguales entre versiones.
#
# Esta lista es fija y deliberadamente honesta: Ada NO tiene acceso a
# las notas oficiales de un parche de Windows, así que no puede saber
# con certeza qué cambió puntualmente en esta actualización. En vez
# de inventar esa certeza, señala TODO lo que depende del sistema
# operativo, para que un humano (o Claude, con el log en la mano)
# decida qué revisar primero según la prioridad que se calcula abajo.
MODULOS_ACOPLADOS_AL_SO = [
    ("auto_reparador.py",
     "corre DISM, SFC y comandos de limpieza de WinSxS -- la sintaxis "
     "o el formato de salida de estos comandos puede cambiar entre builds"),
    ("medico.py",
     "lee batería y drivers vía PowerShell/WMI -- los cmdlets y su "
     "formato de salida pueden cambiar"),
    ("sistema.py",
     "usa WMI y psutil para RAM/CPU/procesos -- las claves de WMI "
     "pueden renombrarse o cambiar de formato entre versiones"),
    ("monitor_arranque.py",
     "lee claves del registro de arranque -- las rutas pueden migrar "
     "en versiones nuevas de Windows"),
    ("perfil_pc.py",
     "lee información de hardware del sistema -- mismas dependencias "
     "de WMI y registro que el resto"),
]

def _leer_version_windows() -> dict:
    """
    Lee la versión/build actual de Windows directamente del registro
    -- no depende de parsear la salida de ningún comando externo
    (más liviano y más confiable que 'winver' o 'systeminfo').

    Retorna {} si algo falla (por ejemplo, corriendo en un sistema
    que no es Windows, o la clave no existe) -- nunca lanza excepción
    hacia quien lo llama.
    """
    try:
        reg = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CLAVE_VERSION, 0, winreg.KEY_READ)

        def _leer(nombre, default=""):
            try:
                valor, _ = winreg.QueryValueEx(reg, nombre)
                return str(valor)
            except FileNotFoundError:
                return default

        datos = {
            "build": _leer("CurrentBuild"),
            "ubr": _leer("UBR"),
            "version_nombre": _leer("DisplayVersion") or _leer("ReleaseId"),
            "product_name": _leer("ProductName"),
        }
        winreg.CloseKey(reg)
        datos["build_completo"] = f"{datos['build']}.{datos['ubr']}" if datos["build"] else ""
        return datos
    except Exception as e:
        logging.warning(f"[VIGILANTE TECNOLÓGICO] No pude leer la versión de Windows: {e}")
        return {}

def _cargar_snapshot() -> dict:
    try:
        if os.path.exists(SNAPSHOT):
            with open(SNAPSHOT, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _guardar_snapshot(datos: dict):
    try:
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        with open(SNAPSHOT, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"[VIGILANTE TECNOLÓGICO] No pude guardar snapshot: {e}")

def inicializar():
    """
    Se llama una sola vez al arrancar Ada (mismo patrón que
    monitor_arranque.inicializar): guarda la versión actual como
    línea base, SIN generar ninguna alerta todavía -- recién a partir
    de la próxima comparación (verificar_actualizacion_os) tiene
    sentido avisar de un cambio real.
    """
    actual = _leer_version_windows()
    if actual and actual.get("build") and not _cargar_snapshot():
        _guardar_snapshot(actual)

def verificar_actualizacion_os(preguntar_groq_fn=None) -> str:
    """
    Compara la versión actual de Windows contra la última guardada.

    Si cambió, registra el cambio en memoria.cambios_tecnologicos con:
      - qué cambió (versión anterior -> nueva, build completo)
      - qué módulos de Ada podrían verse afectados (MODULOS_ACOPLADOS_AL_SO,
        ver el comentario ahí arriba sobre por qué es una lista fija
        y no un intento de adivinar el contenido exacto del parche)
      - prioridad y por qué: "alta" si cambió el número de build (una
        actualización de función/feature update, más propensa a tocar
        formatos de salida de comandos), "media" si solo cambió el UBR
        (un parche acumulativo/de seguridad menor, más contenido pero
        con mucha menos probabilidad de romper algo que Ada usa)

    preguntar_groq_fn (opcional, mismo patrón de inyección que
    monitor_arranque.analizar_con_groq): si se pasa, además le pide a
    Groq una estimación GENERAL de qué tipo de cosas suelen cambiar en
    actualizaciones como esta. Se deja explícito en el propio mensaje
    que es una estimación general y no las notas reales de este
    parche -- Groq tampoco tiene acceso a eso, así que aparentar más
    certeza de la que hay sería peor que no decir nada.

    Retorna un string con el tag [VIGILANTE TECNOLÓGICO] (fácil de
    encontrar cuando se pega el log completo) para log/voz, o ""
    si no hubo ningún cambio.
    """
    from memoria import registrar_cambio_tecnologico

    actual = _leer_version_windows()
    if not actual or not actual.get("build"):
        return ""

    anterior = _cargar_snapshot()
    if not anterior:
        # Primera vez que corre esto (o se perdió el snapshot) -- se
        # guarda como línea base, nunca como "cambio" en sí mismo.
        _guardar_snapshot(actual)
        return ""

    build_completo_anterior = anterior.get("build_completo", "")
    build_completo_actual   = actual.get("build_completo", "")

    if build_completo_anterior == build_completo_actual:
        return ""  # sin cambios

    build_cambio = anterior.get("build") != actual.get("build")
    prioridad = "alta" if build_cambio else "media"
    tipo_cambio = ("actualización de función (cambió el número de build)" if build_cambio
                   else "parche acumulativo (solo cambió la revisión UBR)")

    razon = (f"Windows pasó de build {build_completo_anterior or 'desconocida'} a "
             f"{build_completo_actual} -- {tipo_cambio}.")

    modulos = [m[0] for m in MODULOS_ACOPLADOS_AL_SO]
    registrar_cambio_tecnologico(
        tipo="actualizacion_windows",
        version_anterior=build_completo_anterior or "desconocida",
        version_nueva=build_completo_actual,
        prioridad=prioridad,
        razon=razon,
        modulos_afectados=modulos,
    )

    detalle_modulos = "; ".join(f"{nombre} ({motivo})" for nombre, motivo in MODULOS_ACOPLADOS_AL_SO)
    voz = (
        f"[VIGILANTE TECNOLÓGICO] Windows se actualizó: {build_completo_anterior or 'desconocida'} → "
        f"{build_completo_actual} ({tipo_cambio}). Prioridad: {prioridad}. "
        f"Módulos a revisar: {detalle_modulos}. "
        f"No tengo acceso a las notas oficiales del parche -- esto es una lista honesta de "
        f"qué depende del sistema operativo, no una confirmación de qué se rompió de verdad."
    )

    if preguntar_groq_fn:
        try:
            estimacion = preguntar_groq_fn(
                f"Windows 11 se actualizo de build {build_completo_anterior} a {build_completo_actual}. "
                f"Sin acceso a las notas oficiales del parche, da una estimacion GENERAL Y BREVE (maximo 3 lineas) "
                f"de que tipo de cosas suelen cambiar en actualizaciones de Windows que podrian afectar un script "
                f"Python que usa subprocess/PowerShell/WMI para leer bateria, drivers, disco, RAM y ejecutar "
                f"reparaciones (DISM, SFC). Aclara que es una estimacion general, no las notas reales de este parche."
            )
            if estimacion:
                voz += f" Estimación general de Groq: {estimacion}"
        except Exception as e:
            logging.warning(f"[VIGILANTE TECNOLÓGICO] No pude consultar a Groq: {e}")

    # logging.warning (no .info) a propósito -- esto necesita destacar
    # en el log cuando se revise, no perderse entre líneas rutinarias.
    logging.warning(voz)
    _guardar_snapshot(actual)
    return voz
