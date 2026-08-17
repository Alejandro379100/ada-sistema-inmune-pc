# ==========================================
#   comandos.py v4.0 - Cerebro de Ordenes
#   + Medico autonomo nivel dios
#   + Auto-reparador integrado
#   + Sin caracteres rotos
#   + Menu actualizado
# ==========================================

import os
import re
import time
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import sistema
import medico
import puntuacion
import seguridad
from ia import (preguntar_groq, es_proceso_critico,
                recomendar_software_liviano)
from memoria import (recordar_sesion, agregar_contexto, obtener_contexto,
                     resumen_sesion, resumen_optimizaciones)
from perfil_pc import PERFIL

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
NOTAS_DIR = os.path.join(BASE_DIR, "notas")
os.makedirs(NOTAS_DIR, exist_ok=True)

# ------------------------------------------
#   ESTADOS DE CONVERSACION
# ------------------------------------------
_estado = {
    "esperando_pegar":              False,
    "esperando_confirmar_apagado":  False,
    "esperando_confirmar_reinicio": False,
    "esperando_confirmar_proceso":  False,
    "esperando_confirmar_borrar":   False,
    "proceso_pendiente":            None,
    "archivo_pendiente_borrar":     None,
    "ultimo_software_url":          None,
    "edge_preguntado":              False,
    "lista_apps":                  [],
    # Contraseña de seguridad antes de acciones destructivas
    "esperando_password":           False,
    "accion_pendiente":             None,   # "apagar" | "reiniciar" | "borrar" | "desinstalar"
    "accion_pendiente_data":        None,   # datos extra que necesite la accion (ej: nombre del archivo/app)
}


def _ejecutar_accion_pendiente():
    """Ejecuta la acción que quedó guardada tras verificar la contraseña."""
    accion = _estado["accion_pendiente"]
    data   = _estado["accion_pendiente_data"]
    _estado["accion_pendiente"]      = None
    _estado["accion_pendiente_data"] = None

    if accion == "apagar":
        os.system("shutdown /s /t 5")
        return "Apagando. Hasta pronto."

    if accion == "reiniciar":
        os.system("shutdown /r /t 5")
        return "Reiniciando."

    if accion == "borrar":
        nombre = data
        try:
            if os.path.isfile(nombre):
                os.remove(nombre)
                return "Archivo eliminado."
            elif os.path.isdir(nombre):
                import shutil
                shutil.rmtree(nombre, ignore_errors=True)
                return "Carpeta eliminada."
            return f"No encontre '{nombre}'."
        except Exception as e:
            return f"No pude eliminar: {e}"

    if accion == "desinstalar":
        return _desinstalar_app_real(data)

    return "No supe que accion ejecutar."


def _requiere_password(accion, data=None):
    """
    Si hay contraseña configurada, la pide antes de seguir.
    Si no hay contraseña (usuario no configuró CONTRASENA_SECRETA),
    ejecuta la acción directo, igual que siempre — no le cambia el
    comportamiento a quien nunca configuró seguridad.
    """
    if seguridad.hay_contrasena():
        _estado["esperando_password"]    = True
        _estado["accion_pendiente"]      = accion
        _estado["accion_pendiente_data"] = data
        return "Esa accion requiere contrasena. Escribela para confirmar."
    _estado["accion_pendiente"]      = accion
    _estado["accion_pendiente_data"] = data
    return _ejecutar_accion_pendiente()

# ------------------------------------------
#   SISTEMA DE INTENCIONES
# ------------------------------------------

INTENCIONES = {
    "saludo":         ["hola", "buenos dias", "buenas tardes", "buenas noches", "hey"],
    "identidad":      ["quien eres", "que eres",
                       "para que sirves", "como te llamas", "tu nombre"],
    "estado_ada":     ["como estas", "como te encuentras"],
    "ayuda":          ["ayuda", "que puedes hacer", "capacidades", "funciones"],
    "cerrar_ada":     ["cierrate", "apagate ada", "descansa ada", "duerme ada"],
    "gracias":        ["gracias", "muchas gracias"],

    # Tiempo
    "hora":           ["que hora", "dime la hora"],
    "fecha":          ["que dia", "que fecha"],

    # Sistema
    "optimizar":      ["optimiza", "optimizar", "limpia", "limpiar", "libera ram",
                       "borra basura", "limpiar pc", "libera memoria"],
    "estado_pc":      ["estado del sistema", "estado del pc",
                       "cuanta ram", "como te sientes", "tu salud",
                       "indice de salud", "salud del pc"],
    "procesos":       ["procesos pesados", "que consume",
                       "procesos", "que esta consumiendo"],
    "temperatura":    ["temperatura", "calor del procesador"],
    "nucleos_cpu":    ["revisa los nucleos", "como estan mis nucleos", "diagnostico de cpu",
                       "revisa el procesador", "nucleos del procesador"],
    "historial_opt":  ["historial de optimizaciones", "cuanto has limpiado"],
    "ram_ada":        ["cuanta ram usas", "cuanto consumes",
                       "cuanta ram consume ada", "tu ram", "ram de ada",
                       "cuanto pesas"],
    "sw_pesado":      ["software pesado", "programas pesados", "que programas tengo",
                       "cual es el mas pesado", "programas instalados",
                       "que hay instalado"],
    "vs_code":        ["cuanta ram consume vs code", "cuanta ram consume vscode",
                       "cuanto pesa vs code", "cuanto pesa vscode",
                       "cuanto consume vs code", "cuanto consume vscode",
                       "ram de vs code", "ram de vscode",
                       "cuanto cpu usa vs code", "cuanto cpu usa vscode",
                       "cpu de vs code", "cpu de vscode"],

    # Seguridad
    "bloquear":       ["bloquea el equipo", "bloquear pantalla"],
    "suspender":      ["suspender", "modo sleep", "pon en reposo"],
    "modo_seguro":    ["modo seguro", "activa seguridad"],

    # Notas
    "guardar_nota":   ["anota", "toma nota", "guarda nota", "escribe esto"],
    "leer_notas":     ["lee mis notas", "leer notas", "mis notas"],

    # VS Code
    "vscode_pegar":   ["pega el codigo", "pegar el codigo"],
    "vscode_guardar": ["guarda el archivo", "guardar archivo"],
    "vscode_ejecutar":["ejecuta el codigo", "corre el codigo", "ejecutar codigo"],
    "vscode_nuevo":   ["archivo nuevo", "nuevo archivo", "crea un archivo"],
    "vscode_terminal":["terminal de vs code", "terminal integrada"],

    # Volumen
    "vol_subir":      ["sube el volumen", "subir volumen", "mas volumen"],
    "vol_bajar":      ["baja el volumen", "bajar volumen", "menos volumen"],
    "vol_silencio":   ["silencia", "silenciar", "quita el sonido", "mute"],

    # Web
    "buscar_google":  ["busca en google", "buscar en google", "googlea"],

    # Captura
    "captura":        ["toma una captura", "captura de pantalla", "screenshot"],

    # Control
    "apagar":         ["apaga el equipo", "apagar equipo", "apagar el pc",
                       "apaga el pc", "apaga", "apagar", "apagar pc"],
    "reiniciar":      ["reinicia el equipo", "reiniciar equipo", "reiniciar pc"],

    # Software liviano
    "recomendar_sw":  ["recomienda software", "recomendar software",
                       "que programa uso para", "que usar para",
                       "mejor programa para", "software liviano", "aplicacion para",
                       "que instalo para", "programa para",
                       "herramienta para", "necesito algo para"],

    # Explorador
    "apps_instaladas":   ["muestrame las app instaladas", "muestrame las aplicaciones instaladas",
                          "que tengo instalado", "lista de programas", "programas instalados en windows",
                          "que programas hay instalados", "que programas hay en mi pc",
                          "que aplicaciones tengo instaladas", "lista de aplicaciones instaladas",
                          "que hay instalado en mi pc", "muestrame los programas instalados"],
    "explorador_ver":    ["muestrame", "que hay en",
                          "ver archivos", "ver carpeta", "mostrar archivos"],
    "explorador_buscar": ["busca el archivo", "buscar archivo", "donde esta el archivo"],
    "explorador_borrar": ["borra el archivo", "elimina el archivo",
                          "borrar archivo", "eliminar archivo"],
    "explorador_abrir":  ["abre la carpeta", "abre mis documentos", "abre documentos",
                          "abre mis descargas", "abre descargas", "abre downloads",
                          "abre el escritorio", "abre escritorio",
                          "muestrame documentos", "muestrame descargas", "muestrame el escritorio",
                          "abre la carpeta de ada", "abre ada"],

    # Groq
    "groq_directo":   ["preguntale a groq", "consulta con groq"],

    # Resumen
    "resumen":        ["resumen de sesion", "resumen sesion", "cuantas ordenes"],

    # Historial medico
    "historial_medico": ["historial medico",
                         "como ha estado el pc", "tendencias del pc",
                         "como ha evolucionado"],
    "diagnostico":      ["diagnostico", "chequeo medico",
                         "examinate", "examinate",
                         "examinarte", "examina ti", "examina te",
                         "examina", "chequeo", "revision completa",
                         "como estas por dentro"],

    # Medico autonomo
    "reparar_sistema":   ["repara el sistema", "reparar windows", "sfc", "dism",
                          "repara archivos", "corregir errores del sistema"],
    "limpiar_winsxs":    ["limpia winsxs", "limpiar componentes", "libera espacio windows"],
    "limpiar_iconos":    ["iconos rotos", "iconos en blanco", "repara iconos", "cache de iconos"],
    "confirmar_reparacion": ["ya revise", "ya lo revise", "ya corri sfc", "confirmo la revision",
                             "ya revise el sistema", "problema resuelto"],
    "desactivar_basura": ["desactiva servicios basura", "servicios innecesarios",
                          "optimizar servicios", "desactivar telemetria"],
    "reparar_red":       ["repara la red", "wifi lento", "dns lento", "reset red",
                          "problemas de internet"],
    "revisar_drivers":   ["revisa los drivers", "drivers danados", "drivers actualizados",
                          "estado de drivers"],
    "desinstalar_app":   ["desinstala", "quita", "elimina la app", "desinstalar"],
    "actualizar_todo":   ["actualiza todo", "actualizar software", "winget actualizar",
                          "actualiza mis programas"],
    "modo_enfoque":      ["modo enfoque", "modo concentracion", "pomodoro", "enfocate", "quiero programar en paz"],
    "modo_normal":       ["modo normal", "modo escuchar", "desactiva enfoque", "sal del enfoque"],
    "revisar_arranque":  ["revisar arranque", "que hay en el arranque", "programas al inicio", "analiza el arranque"],
    "reporte_semanal":   ["reporte semanal", "genera reporte", "informe de la semana"],
    "decisiones_medico": ["que has decidido", "que decidiste", "historial de reparaciones",
                          "que ha hecho el medico", "revisa tus decisiones"],
    "bateria_salud":     ["salud de la bateria", "bateria salud", "cuanto dura mi bateria",
                          "estado bateria", "ciclos bateria"],
    "cambios_tecnologicos": ["cambios tecnologicos", "hubo actualizacion de windows",
                             "que cambio en windows", "revisa actualizaciones", "vigilante tecnologico"],

}


PROGRAMAS_ABRIR = {
    ("bloc de notas", "abre el bloc", "abrir bloc"):            ("notepad.exe",        "Abriendo el bloc de notas."),
    ("abre la calculadora", "abrir calculadora"):               ("calc.exe",           "Abriendo la calculadora."),
    ("explorador de archivos", "abre el explorador"):           ("explorer.exe",       "Abriendo el explorador."),
    ("abre chrome", "abrir chrome", "abre google chrome"):      ("chrome.exe",         "Abriendo Google Chrome."),
    ("abre vs code", "abrir vs code", "abre visual studio"):    ("code",               "Abriendo Visual Studio Code."),
    ("abre el word", "abrir word"):                             ("winword.exe",        "Abriendo Word."),
    ("abre el excel", "abrir excel"):                           ("excel.exe",          "Abriendo Excel."),
    ("abre powerpoint", "abrir powerpoint"):                    ("powerpnt.exe",       "Abriendo PowerPoint."),
    ("abre teams", "abrir teams"):                              ("ms-teams:",          "Abriendo Teams."),
    ("abre whatsapp", "abrir whatsapp"):                        ("whatsapp:",          "Abriendo WhatsApp."),
    ("abre el paint", "abrir paint"):                           ("mspaint.exe",        "Abriendo Paint."),
    ("abre postman", "abrir postman"):                          ("Postman",            "Abriendo Postman."),
    ("abre git", "abrir git", "git bash"):                      ("git-bash.exe",       "Abriendo Git Bash."),
    ("abre mongodb", "abrir mongodb"):                          ("MongoDBCompass",     "Abriendo MongoDB Compass."),
    ("abre spotify", "abrir spotify"):                          ("spotify:",           "Abriendo Spotify."),
    ("administrador de tareas",):                               ("taskmgr.exe",        "Abriendo administrador de tareas."),
    ("abre la terminal", "abrir terminal", "abre powershell"):  ("powershell.exe",     "Abriendo PowerShell."),
    ("abre cmd", "abrir cmd"):                                  ("cmd.exe",            "Abriendo CMD."),
    ("abre la configuracion", "abrir configuracion", "ajustes"):("ms-settings:",       "Abriendo configuracion."),
    ("panel de control",):                                      ("control.exe",        "Abriendo panel de control."),
    ("abre foxit", "lector pdf"):                               ("FoxitPDFReader.exe", "Abriendo Foxit PDF Reader."),
    ("abre psint", "abrir psint"):                              ("PSeInt",             "Abriendo PSeInt."),
    ("abre localsend", "abrir localsend"):                      ("LocalSend",          "Abriendo LocalSend."),
    ("microsoft store", "abre la tienda"):                      ("ms-windows-store:",  "Abriendo Microsoft Store."),
    ("sticky notes", "notas rapidas"):                          ("ms-stickynotes:",    "Abriendo notas rapidas."),
    ("microsoft to do", "abre to do"):                          ("ms-todo:",           "Abriendo Microsoft To Do."),
    ("lenovo vantage", "abre lenovo"):                          ("LenovoVantage:",     "Abriendo Lenovo Vantage."),
    ("abre outlook", "abrir outlook"):                          ("outlook.exe",        "Abriendo Outlook."),
    ("abre el reloj", "abrir reloj"):                           ("ms-clock:",          "Abriendo el reloj."),
}

PROGRAMAS_CERRAR = {
    ("cierra la calculadora",):    ["calc.exe", "CalculatorApp.exe"],
    ("cierra el bloc",):           ["notepad.exe"],
    ("cierra chrome",):            ["chrome.exe"],
    ("cierra vs code",):           ["Code.exe"],
    ("cierra el word",):           ["WINWORD.EXE"],
    ("cierra el excel",):          ["EXCEL.EXE"],
    ("cierra powerpoint",):        ["POWERPNT.EXE"],
    ("cierra teams",):             ["Teams.exe"],
    ("cierra whatsapp",):          ["WhatsApp.exe"],
    ("cierra outlook",):           ["OUTLOOK.EXE"],
    ("cierra spotify",):           ["Spotify.exe"],
    ("cierra postman",):           ["Postman.exe"],
    ("cierra el explorador",):     ["explorer.exe"],
    ("cierra edge", "cerrar edge", "cierra el edge"): ["msedge.exe"],
}

WEBS = {
    ("abre youtube", "abrir youtube"):  "https://www.youtube.com",
    ("whatsapp web",):                  "https://web.whatsapp.com",
    ("abre gmail", "abrir gmail"):      "https://mail.google.com",
    ("abre github", "abrir github"):    "https://github.com",
    ("abre claude", "abrir claude"):    "https://claude.ai",
    ("abre chatgpt",):                  "https://chat.openai.com",
    ("abre gemini", "abrir gemini"):        "https://gemini.google.com",
    ("stack overflow",):                "https://stackoverflow.com",
    ("mdn web",):                       "https://developer.mozilla.org",
}

# ------------------------------------------
#   DETECTAR INTENCION
# ------------------------------------------

def detectar_intencion(texto):
    """
    Elige la intención priorizando, en este orden:
    1. La palabra clave más larga que coincide AL INICIO del mensaje
       (lo que la persona quiso ORDENAR, no lo que escribió después).
    2. Si ninguna coincide al inicio, la más larga en cualquier parte.

    Por qué el paso 1 es necesario: antes, "gana la más larga en
    cualquier parte del texto" causaba que una orden como
    "anota [texto libre que menciona 'consulta con groq']" fuera
    secuestrada por la frase de groq_directo, solo porque esa frase
    era más larga que "anota" — aunque "anota" era literalmente la
    primera palabra y la intención real de la persona. Priorizar el
    inicio del mensaje arregla esto sin perder el arreglo anterior
    (las colisiones tipo "cuanta ram" vs "cuanta ram usas" siguen
    resolviéndose bien, porque ambas coinciden al inicio del mensaje
    y ahí sí gana la más larga).
    """
    o = texto.lower().strip()

    mejor_inicio, mejor_inicio_len = None, -1
    mejor_global, mejor_global_len = None, -1
    for intencion, palabras in INTENCIONES.items():
        for p in palabras:
            if p in o:
                if len(p) > mejor_global_len:
                    mejor_global, mejor_global_len = intencion, len(p)
                if o.startswith(p) and len(p) > mejor_inicio_len:
                    mejor_inicio, mejor_inicio_len = intencion, len(p)

    if mejor_inicio:
        return mejor_inicio
    if mejor_global:
        return mejor_global

    for claves in PROGRAMAS_ABRIR:
        if any(k in o for k in claves):
            return "abrir_programa"
    for claves in PROGRAMAS_CERRAR:
        if any(k in o for k in claves):
            return "cerrar_programa"
    for claves in WEBS:
        if any(k in o for k in claves):
            return "abrir_web"

    # Último recurso antes de Groq: si la orden empieza con un verbo
    # de "abrir" y no coincidio con nada especifico de arriba, se
    # intenta resolver de forma dinamica (apps instaladas en Windows +
    # busqueda de archivos/carpetas) en vez de rendirse directo a Groq.
    if o.startswith(("abre ", "abrir ", "abreme ", "ejecuta ")):
        return "abrir_generico"

    return "groq_fallback"

# ------------------------------------------
#   HELPERS
# ------------------------------------------

def _abrir(cmd):
    try:
        # "start" enruta a través de ShellExecute de Windows, que sabe
        # encontrar programas registrados (como Chrome) aunque no
        # estén en el PATH del sistema. Importante: NO se envuelve
        # {cmd} en comillas propias aquí, porque algunas llamadas ya
        # traen sus propias comillas (ej: 'explorer.exe "C:\...\Docs"')
        # y envolverlas de nuevo generaba comillas anidadas rotas que
        # hacían fallar el comando en silencio.
        subprocess.Popen(f'start "" {cmd}', shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        print(f"[ERROR abrir] {e}")

def _cerrar(exe):
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", exe],
            capture_output=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass

# ------------------------------------------
#   ABRIR "CUALQUIER COSA" (resolver dinamico)
#
#   En vez de mantener una lista fija de programas y carpetas (que
#   se desactualiza apenas Alejandro instala algo nuevo), esto le
#   pregunta a Windows en el momento que se ejecuta la orden:
#   1) ¿Hay una app instalada que se parezca a lo que pidio?
#   2) Si no, ¿hay un archivo o carpeta suya que se parezca?
#   3) Si tampoco, recien ahi se avisa que no se encontro.
# ------------------------------------------

_cache_apps        = None
_cache_apps_tiempo = 0.0
_CACHE_APPS_SEGUNDOS = 300  # 5 minutos: no vuelve a listar apps en cada orden

def _listar_apps_instaladas():
    """
    Devuelve [(nombre, app_id), ...] de todo lo que aparece en el
    menu Inicio de Windows (UWP y de escritorio por igual), usando
    Get-StartApps de PowerShell. Se cachea unos minutos porque esta
    consulta puede tardar 1-2 segundos.
    """
    global _cache_apps, _cache_apps_tiempo
    ahora = time.time()
    if _cache_apps is not None and (ahora - _cache_apps_tiempo) < _CACHE_APPS_SEGUNDOS:
        return _cache_apps
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        import json
        data = json.loads(r.stdout) if r.stdout.strip() else []
        if isinstance(data, dict):
            data = [data]
        apps = [(d.get("Name", ""), d.get("AppID", "")) for d in data if d.get("Name")]
        _cache_apps = apps
        _cache_apps_tiempo = ahora
        return apps
    except Exception:
        return _cache_apps or []

def _buscar_app_instalada(objetivo: str):
    """Busca, entre las apps instaladas de verdad en Windows, la que
    mejor calce con lo que la persona pidio. Devuelve (nombre, app_id)
    o None si no hay ningun parecido razonable."""
    apps = _listar_apps_instaladas()
    objetivo_low = objetivo.lower()
    # Coincidencia exacta primero
    for nombre, app_id in apps:
        if nombre.lower() == objetivo_low:
            return (nombre, app_id)
    # Coincidencia parcial (el nombre pedido esta dentro del nombre real,
    # o al reves) — cubre "abre spotify" -> "Spotify Music", por ejemplo
    for nombre, app_id in apps:
        nombre_low = nombre.lower()
        if objetivo_low in nombre_low or nombre_low in objetivo_low:
            return (nombre, app_id)
    return None

def _buscar_archivo_o_carpeta(objetivo: str):
    """Busca un archivo o carpeta real de la persona (Escritorio,
    Documentos, Descargas) que calce con lo pedido. Reusa el mismo
    filtro anti-ruido de 'busca el archivo' (sin node_modules, etc.)."""
    IGNORAR_CARPETAS = {"node_modules", ".git", "__pycache__",
                         ".venv", "venv", "dist", "build",
                         ".next", "target", ".cache"}
    objetivo_low = objetivo.lower()
    exactos, parciales = [], []
    for raiz in [os.path.expanduser("~\\Desktop"),
                 os.path.expanduser("~\\Documents"),
                 os.path.expanduser("~\\Downloads")]:
        if not os.path.isdir(raiz):
            continue
        for dirpath, dirnames, filenames in os.walk(raiz):
            dirnames[:] = [d for d in dirnames if d.lower() not in IGNORAR_CARPETAS]
            for item in dirnames + filenames:
                item_low = item.lower()
                ruta = os.path.join(dirpath, item)
                if item_low == objetivo_low or os.path.splitext(item_low)[0] == objetivo_low:
                    exactos.append(ruta)
                elif objetivo_low in item_low:
                    parciales.append(ruta)
            if len(exactos) >= 1:
                break
        if len(exactos) >= 1:
            break
    encontrados = exactos or parciales
    return encontrados[0] if encontrados else None

def _abrir_generico(objetivo: str) -> str:
    """El resolver de 3 capas: app instalada -> archivo/carpeta -> nada."""
    app = _buscar_app_instalada(objetivo)
    if app:
        nombre, app_id = app
        # shell:AppsFolder\<AppID> es la forma oficial de Windows de
        # lanzar CUALQUIER cosa del menu Inicio (UWP o de escritorio)
        # por su identificador, sin necesitar la ruta del .exe.
        _abrir(f'explorer.exe "shell:AppsFolder\\{app_id}"')
        return f"Abriendo {nombre}."

    archivo = _buscar_archivo_o_carpeta(objetivo)
    if archivo:
        _abrir(f'"{archivo}"')
        return f"Abriendo {os.path.basename(archivo)}."

    return (f"No encontre nada llamado '{objetivo}' entre tus programas "
            f"instalados ni en Escritorio, Documentos o Descargas. "
            f"Verifica el nombre.")

def _captura_pantalla():
    try:
        import PIL.ImageGrab
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(BASE_DIR, f"captura_{ts}.png")
        PIL.ImageGrab.grab().save(ruta)
        return "Captura guardada."
    except Exception:
        _abrir("snippingtool")
        return "Abriendo herramienta de recorte."

def _accion_vscode(teclas, ok, error):
    try:
        import pygetwindow as gw
        import pyautogui
        ventanas = gw.getWindowsWithTitle('Visual Studio Code')
        if ventanas:
            ventanas[0].activate()
            time.sleep(0.3)
            pyautogui.hotkey(*teclas)
            return ok
        return "No encontre VS Code abierto."
    except Exception:
        return error

def _controlar_volumen(accion):
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices   = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume    = cast(interface, POINTER(IAudioEndpointVolume))
        if accion == 'subir':
            volume.SetMasterVolumeLevelScalar(min(volume.GetMasterVolumeLevelScalar() + 0.1, 1.0), None)
            return "Subiendo el volumen."
        elif accion == 'bajar':
            volume.SetMasterVolumeLevelScalar(max(volume.GetMasterVolumeLevelScalar() - 0.1, 0.0), None)
            return "Bajando el volumen."
        elif accion == 'silenciar':
            volume.SetMute(1, None)
            return "Silenciando."
    except Exception:
        return "No pude controlar el volumen."

def _explorador_ver(ruta_texto):
    try:
        mapeo = {
            "documentos": os.path.expanduser("~\\Documents"),
            "descargas":  os.path.expanduser("~\\Downloads"),
            "escritorio": os.path.expanduser("~\\Desktop"),
            "imagenes":   os.path.expanduser("~\\Pictures"),
            "ada":        BASE_DIR,
        }
        ruta = None
        for palabra, path in mapeo.items():
            if palabra in ruta_texto:
                ruta = path
                break
        if not ruta or not os.path.exists(ruta):
            return "Di el nombre de la carpeta: documentos, descargas, escritorio, etc."
        items    = list(Path(ruta).iterdir())
        carpetas = [i.name for i in items if i.is_dir()][:5]
        archivos = [i.name for i in items if i.is_file()][:5]
        msg = f"En {os.path.basename(ruta)}: "
        if carpetas:
            msg += f"{len(carpetas)} carpetas: {', '.join(carpetas[:3])}. "
        if archivos:
            msg += f"{len(archivos)} archivos: {', '.join(archivos[:3])}."
        return msg
    except Exception as e:
        return f"No pude leer esa carpeta: {e}"

def _guardar_nota(texto):
    try:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ruta = os.path.join(NOTAS_DIR, "notas.txt")
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {texto}\n")
        subprocess.Popen(f"notepad.exe {ruta}", shell=True)
        return "Nota guardada."
    except Exception:
        return "No pude guardar la nota."

def _leer_notas():
    try:
        ruta = os.path.join(NOTAS_DIR, "notas.txt")
        if not os.path.exists(ruta):
            return "No tienes notas guardadas todavia."
        with open(ruta, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        if not lineas:
            return "No tienes notas guardadas todavia."
        return f"Tu ultima nota dice: {lineas[-1].strip()}"
    except Exception:
        return "No pude leer las notas."

def _desinstalar_app_real(app: str) -> str:
    """Busca y desinstala una app con winget. Se llama solo despues
    de pasar el chequeo de contrasena (si hay una configurada)."""
    buscar = subprocess.run(
        ["winget", "search", app, "--accept-source-agreements"],
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW)
    id_app = None
    for linea in buscar.stdout.split("\n"):
        partes = linea.split()
        if len(partes) >= 2 and app.lower() in linea.lower():
            for parte in partes:
                if "." in parte and len(parte) > 5:
                    id_app = parte
                    break
        if id_app:
            break
    if not id_app:
        return f"No encontre {app} en winget. Verifica el nombre."
    r = subprocess.run(
        ["winget", "uninstall", "--id", id_app, "--accept-source-agreements"],
        capture_output=True, text=True, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode == 0:
        return f"{app} desinstalado correctamente."
    subprocess.Popen("start ms-settings:appsfeatures", shell=True)
    return f"No encontre {app} en winget. Abri Configuracion de Windows para que lo desinstales manualmente."

# ------------------------------------------
#   MENU DE AYUDA
# ------------------------------------------

MENU = """
=======================================================
  ADA v5.0 — Medico autonomo de tu PC
=======================================================
  SISTEMA:
  'como te sientes'       -> salud 0-100
  'optimiza'              -> limpia RAM y disco
  'diagnostico'           -> chequeo medico completo
  'procesos pesados'      -> que consume mas
  'temperatura'           -> calor del procesador
  'cuanta ram consume vs code' -> RAM y CPU de VS Code, y por que

  MEDICO AUTONOMO:
  'salud de la bateria'   -> salud real en ciclos
  'revisa los drivers'    -> 162 drivers revisados
  'revisa los nucleos'    -> diagnostico de CPU por nucleo
  'desactiva servicios'   -> elimina basura de Windows
  'repara el sistema'     -> SFC + DISM automatico
  'reporte semanal'       -> informe en el escritorio
  'que has decidido'      -> historial del medico autonomo
  'repara la red'         -> resetea DNS y Winsock
  'limpia winsxs'         -> libera hasta 3GB de Windows
  'ya revise'             -> confirma una reparacion revisada a mano,
                             resetea el circuito de seguridad bloqueado

  PROGRAMAS:
  'abre chrome'           -> abre Chrome
  'abre vs code'          -> abre VS Code
  'cierra edge'           -> cierra Edge
  'abre youtube'          -> abre YouTube
  'abre claude'           -> abre Claude

  VOZ:
  'habla'                 -> Ada habla en voz alta
  'silencio'              -> Ada solo escribe

  CONTROL:
  'apaga'                 -> apaga el PC
  'salir'                 -> cierra Ada
=======================================================
"""

# ------------------------------------------
#   PROCESADOR PRINCIPAL
# ------------------------------------------

def _contiene_confirmacion(texto, palabras):
    """
    Bug real que pasó de verdad: "si" ∈ "como te sientes" daba True
    con un simple `p in o`, porque "sientes" empieza con "si" — Ada
    terminó cerrando un proceso porque el usuario preguntó "cómo te
    sientes", nada que ver con confirmar nada.

    Frases de más de una palabra ("si borra", "confirmar apagado")
    son lo bastante específicas para seguir comparando por substring
    sin riesgo real. Pero las palabras sueltas cortas ("si", "ya") NO
    se comparan como substring — deben aparecer como palabra completa
    (separada por espacios o signos de puntuación), con \\b de regex.
    Así "sientes", "sistema", "positivo", "playa" ya no confirman
    nada por accidente.
    """
    for p in palabras:
        if " " in p:
            if p in texto:
                return True
        elif re.search(rf"\b{re.escape(p)}\b", texto):
            return True
    return False


def procesar_orden(orden, hablar):
    o = orden.lower().strip()
    recordar_sesion("ultima_orden", o)

    # ==========================================
    #   CONTRASEÑA PENDIENTE (va primero: nada más
    #   se procesa mientras Ada espera la clave)
    # ==========================================
    if _estado["esperando_password"]:
        correcta, se_bloqueo = seguridad.verificar_contrasena(orden.strip())
        if correcta:
            _estado["esperando_password"] = False
            return _ejecutar_accion_pendiente()
        if se_bloqueo:
            _estado["esperando_password"]    = False
            _estado["accion_pendiente"]      = None
            _estado["accion_pendiente_data"] = None
            return "Contrasena incorrecta demasiadas veces. Bloquee la pantalla por seguridad."
        # Antes esto cancelaba la accion pendiente al primer error, sin
        # importar que seguridad.py ya llevaba la cuenta de hasta 3
        # intentos antes de bloquear — nunca daba la oportunidad real
        # de un segundo intento. Ahora sí se respeta esa cuenta.
        restantes = seguridad.intentos_restantes()
        return f"Contrasena incorrecta. Te quedan {restantes} intentos antes de que bloquee la pantalla."

    # ==========================================
    #   ESTADOS EN ESPERA
    # ==========================================

    if _estado["esperando_pegar"] and _contiene_confirmacion(o, ["listo", "ya", "adelante"]):
        _estado["esperando_pegar"] = False
        try:
            import pygetwindow as gw, pyautogui
            ventanas = gw.getWindowsWithTitle('Visual Studio Code')
            if ventanas:
                ventanas[0].activate()
                time.sleep(0.5)
                pyautogui.hotkey('ctrl', 'v')
                return "Codigo pegado."
        except Exception:
            return "No pude pegar."

    if _estado["esperando_confirmar_apagado"] and _contiene_confirmacion(o,
       ["confirmar apagado", "confirmar apag", "confirmo", "confirma",
        "si apaga", "si"]):
        _estado["esperando_confirmar_apagado"] = False
        return _requiere_password("apagar")

    if _estado["esperando_confirmar_reinicio"] and _contiene_confirmacion(o,
       ["confirmar reinicio", "confirmo", "si reinicia"]):
        _estado["esperando_confirmar_reinicio"] = False
        return _requiere_password("reiniciar")

    if _estado["esperando_confirmar_borrar"]:
        if _contiene_confirmacion(o, ["si elimina", "confirmo", "si borra"]):
            nombre = _estado["archivo_pendiente_borrar"]
            _estado["esperando_confirmar_borrar"]  = False
            _estado["archivo_pendiente_borrar"]    = None
            return _requiere_password("borrar", nombre)
        else:
            _estado["esperando_confirmar_borrar"] = False
            _estado["archivo_pendiente_borrar"]   = None
            return "Entendido, no elimino nada."

    if _estado["esperando_confirmar_proceso"] and _estado["proceso_pendiente"]:
        if _contiene_confirmacion(o, ["si", "confirmo", "terminalo"]):
            nombre = _estado["proceso_pendiente"]
            _estado["esperando_confirmar_proceso"] = False
            _estado["proceso_pendiente"]           = None
            if es_proceso_critico(nombre):
                return f"No puedo terminar {nombre}, es critico para Windows."
            subprocess.run(
                ["taskkill", "/f", "/im", nombre],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            return f"Proceso {nombre} terminado."
        else:
            _estado["esperando_confirmar_proceso"] = False
            _estado["proceso_pendiente"]           = None
            return "Entendido, no lo termino."

    if _estado["ultimo_software_url"] and _contiene_confirmacion(o,
       ["si abre", "abre la descarga", "abre la pagina"]):
        url = _estado["ultimo_software_url"]
        _estado["ultimo_software_url"] = None
        webbrowser.open(url)
        return "Abriendo pagina de descarga. Tu decides si instalarlo."

    import sistema as _sis
    if _sis._estado.get("edge_preguntado") and _contiene_confirmacion(o, ["si", "yes", "cerralo", "cierra"]):
        _sis._estado["edge_preguntado"] = False
        subprocess.run(["taskkill", "/f", "/im", "msedge.exe"], capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return "Edge cerrado."

    # ==========================================
    #   INTENCION Y ACCION
    # ==========================================

    intencion = detectar_intencion(o)

    if intencion == "saludo":
        return f"Hola {PERFIL['propietario']}, lista para trabajar contigo."

    if intencion == "identidad":
        return ("Soy Ada, tu asistente personal y sistema inmune de tu PC. "
                "Mi prioridad es mantener tu RAM libre para que programes sin interrupciones.")

    if intencion == "estado_ada":
        return "Muy bien, monitoreando tu PC y lista para servirte."

    if intencion == "ayuda":
        return MENU

    if intencion == "cerrar_ada":
        hablar(f"Hasta luego {PERFIL['propietario']}, fue un placer cuidar tu PC.")
        time.sleep(2)
        os._exit(0)

    if intencion == "gracias":
        return "Con mucho gusto, para eso estoy."

    if intencion == "hora":
        return f"Son las {datetime.now().strftime('%I:%M %p')}."

    if intencion == "fecha":
        return f"Hoy es {datetime.now().strftime('%A %d de %B del %Y')}."

    if intencion == "resumen":
        return resumen_sesion()

    if intencion == "optimizar":
        return sistema.optimizar_sistema(silencioso=False)

    if intencion == "estado_pc":
        salud = sistema.indice_salud()
        return salud["voz"] + " " + sistema.estado_sistema()

    if intencion == "procesos":
        # Antes esto llamaba sistema.procesos_pesados(), que solo
        # ordenaba por % de RAM sin usar la base de procesos conocidos
        # (procesos.json). puntuacion.snapshot_procesos() ya existía,
        # completo y probado, pero nadie lo llamaba -- calcula score
        # real por proceso, distingue críticos de basura, y separa
        # top RAM de top CPU. Se conecta acá en vez de dejarlo sin uso.
        snap = puntuacion.snapshot_procesos()
        if not snap["top_ram"] and not snap["top_cpu"]:
            return "No hay procesos consumiendo demasiado ahora mismo."

        partes = []
        if snap["top_ram"]:
            top_ram_txt = ", ".join(f"{n} ({p}% RAM)" for n, p in snap["top_ram"][:4])
            partes.append(f"Los que más RAM consumen: {top_ram_txt}.")
        if snap["top_cpu"]:
            top_cpu_txt = ", ".join(f"{n} ({p}% CPU)" for n, p in snap["top_cpu"][:4])
            partes.append(f"Los que más CPU consumen: {top_cpu_txt}.")
        if snap["alertas"]:
            nombres_alerta = ", ".join(a["nombre"] for a in snap["alertas"][:3])
            partes.append(f"Con score bajo (revisar): {nombres_alerta}.")
        if snap["basura"]:
            partes.append(f"Detecté {len(snap['basura'])} proceso(s) de basura conocida activos.")

        return " ".join(partes)

    if intencion == "temperatura":
        return sistema.temperatura_cpu()

    if intencion == "nucleos_cpu":
        hablar("Revisando cada núcleo, dame un segundo.")
        return medico.presion_cpu_nucleos()["voz"]

    if intencion == "historial_opt":
        return resumen_optimizaciones()

    if intencion == "ram_ada":
        return sistema.ram_de_ada()

    if intencion == "sw_pesado":
        return sistema.software_pesado_pc()

    if intencion == "vs_code":
        return sistema.ram_vscode()

    if intencion == "bloquear":
        return seguridad.bloquear_equipo()

    if intencion == "suspender":
        return seguridad.suspender_equipo()

    if intencion == "modo_seguro":
        return seguridad.modo_seguro()

    if intencion == "guardar_nota":
        texto = o
        for p in ["anota", "toma nota", "guarda nota", "escribe esto"]:
            texto = texto.replace(p, "").strip()
        if texto:
            agregar_contexto(f"Nota: {texto[:50]}")
            return _guardar_nota(texto)
        return "Que deseas que anote?"

    if intencion == "leer_notas":
        return _leer_notas()

    if intencion == "vscode_pegar":
        hablar("Haz clic donde quieres pegarlo en VS Code y di listo.")
        _estado["esperando_pegar"] = True
        return ""

    if intencion == "vscode_guardar":
        return _accion_vscode(['ctrl', 's'], "Archivo guardado.", "No pude guardar.")

    if intencion == "vscode_ejecutar":
        return _accion_vscode(['ctrl', 'f5'], "Ejecutando.", "No pude ejecutar.")

    if intencion == "vscode_nuevo":
        return _accion_vscode(['ctrl', 'n'], "Archivo nuevo creado.", "No pude crear.")

    if intencion == "vscode_terminal":
        return _accion_vscode(['ctrl', '`'], "Terminal de VS Code abierta.", "No pude abrir.")

    if intencion == "vol_subir":    return _controlar_volumen('subir')
    if intencion == "vol_bajar":    return _controlar_volumen('bajar')
    if intencion == "vol_silencio": return _controlar_volumen('silenciar')

    if intencion == "captura":
        return _captura_pantalla()

    if intencion == "apagar":
        _estado["esperando_confirmar_apagado"] = True
        return "Confirmas el apagado? Di: confirmar apagado."

    if intencion == "reiniciar":
        _estado["esperando_confirmar_reinicio"] = True
        return "Confirmas el reinicio? Di: confirmar reinicio."

    if intencion == "buscar_google":
        termino = o
        for p in ["busca en google", "buscar en google", "googlea"]:
            termino = termino.replace(p, "").strip()
        if termino:
            webbrowser.open(f"https://www.google.com/search?q={termino}")
            return f"Buscando {termino} en Google."
        return "Dime que deseas buscar."

    if intencion == "recomendar_sw":
        tarea = o
        for p in ["recomienda software", "recomendar software", "que programa uso para",
                  "que usar para", "mejor programa para",
                  "software liviano", "aplicacion para",
                  "que instalo para", "programa para",
                  "herramienta para", "necesito algo para"]:
            tarea = tarea.replace(p, "").strip()
        if tarea:
            hablar("Buscando el mejor software liviano del mundo para tu PC.")
            resultado, url = recomendar_software_liviano(tarea)
            if url:
                _estado["ultimo_software_url"] = url
            return resultado
        return "Para que tarea necesitas software?"

    if intencion == "apps_instaladas":
        import json
        hablar("Consultando todas las aplicaciones instaladas. Dame un momento.")
        script = """
$progs1 = Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Where-Object { $_.DisplayName } | Select-Object -ExpandProperty DisplayName
$progs2 = Get-ItemProperty HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Where-Object { $_.DisplayName } | Select-Object -ExpandProperty DisplayName
$progs3 = Get-ItemProperty HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Where-Object { $_.DisplayName } | Select-Object -ExpandProperty DisplayName
$todos = ($progs1 + $progs2 + $progs3) | Sort-Object -Unique
$todos | ConvertTo-Json -Compress
        """
        r = subprocess.run(["powershell", "-Command", script], capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            apps = json.loads(r.stdout.strip())
            if isinstance(apps, str): apps = [apps]
            apps = sorted(set([a.strip() for a in apps if a and len(a.strip()) > 2]))
        except Exception:
            apps = sorted(set([l.strip() for l in r.stdout.split("\n") if l.strip() and len(l.strip()) > 2]))
        _estado["lista_apps"] = apps
        msg = f"Tienes {len(apps)} aplicaciones instaladas:\n"
        for i, nombre in enumerate(apps, 1):
            msg += f"  {i}. {nombre}\n"
        msg += "\nDi desinstala numero y los numeros separados por coma. Ejemplo: desinstala numero 3,7,12"
        return msg

    if intencion == "explorador_ver":
        return _explorador_ver(o)

    if intencion == "explorador_buscar":
        nombre = o
        for p in ["busca el archivo", "buscar archivo", "donde esta"]:
            nombre = nombre.replace(p, "").strip()
        if nombre:
            # Carpetas que se saltan al buscar: son de desarrollo y
            # pueden tener miles de archivos (node_modules en un solo
            # proyecto ya trae de sobra), generando coincidencias
            # basura por simple casualidad de substring (ej: "etb"
            # aparecía dentro de "getBoundingClientRect.js").
            IGNORAR_CARPETAS = {"node_modules", ".git", "__pycache__",
                                 ".venv", "venv", "dist", "build",
                                 ".next", "target", ".cache"}
            try:
                exactos  = []
                parciales = []
                nombre_low = nombre.lower()
                for raiz in [os.path.expanduser("~\\Documents"),
                             os.path.expanduser("~\\Downloads"),
                             os.path.expanduser("~\\Desktop")]:
                    for dirpath, dirnames, filenames in os.walk(raiz):
                        dirnames[:] = [d for d in dirnames if d.lower() not in IGNORAR_CARPETAS]
                        for item in dirnames + filenames:
                            item_low = item.lower()
                            ruta_completa = os.path.join(dirpath, item)
                            if item_low == nombre_low or os.path.splitext(item_low)[0] == nombre_low:
                                exactos.append(ruta_completa)
                            elif nombre_low in item_low:
                                parciales.append(ruta_completa)
                        if len(exactos) >= 3:
                            break
                    if len(exactos) >= 3:
                        break
                # Los exactos siempre van primero; solo se completa con
                # parciales si no hay suficientes exactos.
                encontrados = (exactos + parciales)[:3]
                if encontrados:
                    return f"Encontre: {', '.join(encontrados[:2])}."
                return f"No encontre ningun archivo con '{nombre}'."
            except Exception as e:
                return f"No pude buscar: {e}"
        return "Que archivo buscas?"

    if intencion == "explorador_borrar":
        nombre = o
        for p in ["borra el archivo", "elimina el archivo", "borrar archivo", "eliminar archivo",
                  "borra la carpeta", "elimina la carpeta"]:
            nombre = nombre.replace(p, "").strip()
        if nombre:
            _estado["esperando_confirmar_borrar"]  = True
            _estado["archivo_pendiente_borrar"]    = nombre
            return (f"Confirmas que quieres eliminar '{nombre}'? "
                    f"No se puede deshacer. Di: si elimina o no.")
        return "Que quieres eliminar?"

    if intencion == "explorador_abrir":
        mapeo = {
            "documentos": os.path.expanduser("~\\Documents"),
            "descargas":  os.path.expanduser("~\\Downloads"),
            "escritorio": os.path.expanduser("~\\Desktop"),
            "ada":        BASE_DIR,
        }
        for palabra, ruta in mapeo.items():
            if palabra in o:
                _abrir(f'explorer.exe "{ruta}"')
                return f"Abriendo {palabra}."
        _abrir("explorer.exe")
        return "Abriendo el explorador."

    if intencion == "abrir_programa":
        for claves, (cmd, msg) in PROGRAMAS_ABRIR.items():
            if any(k in o for k in claves):
                _abrir(cmd)
                return msg

    if intencion == "abrir_generico":
        objetivo = o
        for p in ["abre ", "abrir ", "abreme ", "ejecuta "]:
            if objetivo.startswith(p):
                objetivo = objetivo[len(p):].strip()
                break
        if not objetivo:
            return "Que quieres que abra?"
        hablar("Buscando en tus apps y archivos.")
        return _abrir_generico(objetivo)

    if intencion == "cerrar_programa":
        for claves, exes in PROGRAMAS_CERRAR.items():
            if any(k in o for k in claves):
                for exe in exes:
                    _cerrar(exe)
                return f"Cerrando {exes[0].replace('.exe','').replace('.EXE','')}."

    if intencion == "abrir_web":
        for claves, url in WEBS.items():
            if any(k in o for k in claves):
                webbrowser.open(url)
                return f"Abriendo {url.split('/')[2].replace('www.','')}."

    if intencion == "groq_directo":
        pregunta = o
        for p in ["preguntale a groq", "consulta con groq"]:
            pregunta = pregunta.replace(p, "").strip()
        if pregunta:
            hablar("Consultando.")
            # Antes obtener_contexto() existía pero nunca se conectaba
            # con preguntar_groq() — Ada guardaba tus notas recientes
            # y nunca las volvía a usar para nada. Ahora sí las pasa
            # como contexto, así que Groq puede tener en cuenta lo que
            # anotaste hace poco.
            contexto = ", ".join(obtener_contexto())
            return preguntar_groq(pregunta, contexto_extra=contexto)
        return "Que deseas preguntarle a Groq?"

    if intencion == "historial_medico":
        from memoria import diagnostico_tendencias
        return diagnostico_tendencias()

    if intencion == "diagnostico":
        hablar("Iniciando chequeo medico completo. Dame unos segundos.")
        return medico.diagnostico_completo()

    # ------------------------------------------
    #   MEDICO AUTONOMO
    # ------------------------------------------

    if intencion == "reparar_sistema":
        import auto_reparador
        motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()
        if motivo:
            auto_reparador.solicitar_reparacion_pendiente("reparar_archivos_sistema")
            return (f"No es buen momento: {motivo} La dejo pendiente -- la hago yo sola "
                    f"apenas se libere, no hace falta que la vuelvas a pedir.")
        hablar("Iniciando reparacion de archivos del sistema. Puede tomar varios minutos.")
        return auto_reparador.reparar_archivos_sistema()

    if intencion == "limpiar_winsxs":
        import auto_reparador
        motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()
        if motivo:
            auto_reparador.solicitar_reparacion_pendiente("limpiar_winsxs")
            return (f"No es buen momento: {motivo} La dejo pendiente -- la hago yo sola "
                    f"apenas se libere, no hace falta que la vuelvas a pedir.")
        hablar("Limpiando componentes internos de Windows.")
        return auto_reparador.limpiar_winsxs()

    if intencion == "limpiar_iconos":
        import auto_reparador
        return auto_reparador.limpiar_cache_iconos()

    if intencion == "confirmar_reparacion":
        import auto_reparador
        from memoria import confirmar_reparacion_revisada
        bloqueo = auto_reparador.ultimo_bloqueo()
        if not bloqueo:
            return "No tengo ninguna reparacion bloqueada pendiente de confirmar ahora mismo."
        accion      = bloqueo.get("accion")
        componente  = bloqueo.get("componente")
        confirmar_reparacion_revisada(accion, componente)
        auto_reparador.limpiar_ultimo_bloqueo()
        return (f"Listo, anotado. Reinicie el circuito de seguridad de '{accion}' para "
                f"'{componente}' -- la vuelvo a intentar sola si hace falta de nuevo.")

    if intencion == "desactivar_basura":
        import auto_reparador
        return auto_reparador.desactivar_servicios_basura()

    if intencion == "reparar_red":
        import auto_reparador
        return auto_reparador.reparar_red()

    if intencion == "bateria_salud":
        import auto_reparador
        r = auto_reparador.diagnostico_bateria()
        return r.get("voz", "No pude leer la bateria.")

    if intencion == "revisar_drivers":
        hablar("Revisando los drivers. Un momento.")
        import auto_reparador
        return auto_reparador.diagnostico_drivers().get("voz", "No pude leer los drivers.")

    if "desinstala numero" in o or "desinstala los numeros" in o:
        import re
        numeros = [int(n) for n in re.findall(r"\d+", o)]
        if not numeros or not _estado.get("lista_apps"):
            return "Primero di muestrame las aplicaciones instaladas para ver la lista."
        resultados = []
        for num in numeros:
            if num < 1 or num > len(_estado["lista_apps"]):
                resultados.append(f"Numero {num} no existe en la lista.")
                continue
            app = _estado["lista_apps"][num - 1]
            hablar(f"Desinstalando {app}.")
            buscar = subprocess.run(
                ["winget", "search", app, "--accept-source-agreements"],
                capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
            id_app = None
            for linea in buscar.stdout.split("\n"):
                partes = linea.split()
                if len(partes) >= 2 and app.lower() in linea.lower():
                    for parte in partes:
                        if "." in parte and len(parte) > 5:
                            id_app = parte
                            break
                if id_app:
                    break
            if id_app:
                r = subprocess.run(
                    ["winget", "uninstall", "--id", id_app, "--accept-source-agreements"],
                    capture_output=True, text=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode == 0:
                    resultados.append(f"{app} desinstalado.")
                    continue
            script_ps = f"""
$key = Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* -ErrorAction SilentlyContinue | Where-Object {{ $_.DisplayName -like '*{app}*' }} | Select-Object -First 1
if ($key.UninstallString) {{ $cmd = $key.UninstallString; Start-Process cmd -ArgumentList ('/c ' + $cmd + ' /quiet /norestart') -Wait -NoNewWindow }}
"""
            r2 = subprocess.run(["powershell", "-Command", script_ps], capture_output=True, text=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW)
            if r2.returncode == 0:
                resultados.append(f"{app} desinstalado correctamente.")
            else:
                resultados.append(f"No pude desinstalar {app} automaticamente. Hazlo desde Configuracion.")
        return " ".join(resultados)

    if intencion == "desinstalar_app":
        app = o
        for p in ["desinstala", "quita", "elimina la app", "desinstalar"]:
            app = app.replace(p, "").strip()
        if app:
            return _requiere_password("desinstalar", app)
        return "Que aplicacion quieres desinstalar?"

    if intencion == "actualizar_todo":
        # Actualizar de a un paquete por vez con winget puede tardar
        # varios minutos en total -- si esto corriera bloqueando acá,
        # Ada quedaría "congelada" sin responder nada más mientras
        # tanto. Se lanza en su propio hilo, igual que ya hace el
        # médico autónomo (_medico_ia_hilo) y la revisión de CPU.
        import auto_reparador
        import threading

        def _actualizar_en_segundo_plano():
            resultado = auto_reparador.actualizar_con_winget()
            hablar(resultado, prioridad=1)

        threading.Thread(target=_actualizar_en_segundo_plano, daemon=True).start()
        return "Actualizando en segundo plano. Puede tardar varios minutos -- te aviso cuando termine."

    if intencion == "modo_enfoque":
        import modo_enfoque
        return modo_enfoque.activar(hablar)

    if intencion == "modo_normal":
        # Antes esto también tocaba banderas de "voz activada/
        # desactivada" y "modo sordo" que nunca tuvieron efecto real
        # (Ada es 100% texto — voz.hablar() siempre imprime, sin
        # importar esas banderas). Se quitó esa parte teatral; lo
        # único que este comando hace de verdad es salir del modo
        # enfoque, así que eso es lo único que queda.
        import modo_enfoque
        if modo_enfoque.esta_activo():
            modo_enfoque.desactivar()
            return "Modo normal activado. Salí del modo enfoque."
        return "Ya estaba en modo normal."

    if intencion == "revisar_arranque":
        hablar("Analizando el arranque de Windows con Groq.")
        import monitor_arranque
        return monitor_arranque.analizar_con_groq(preguntar_groq)

    if intencion == "reporte_semanal":
        import auto_reparador
        return auto_reparador.reporte_semanal()

    if intencion == "decisiones_medico":
        from memoria import historial_decisiones_medico_ia
        filas = historial_decisiones_medico_ia(5)
        if not filas:
            return "Todavía no he tomado ninguna decisión médica autónoma."
        partes = []
        for fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito in filas:
            estado = "ejecuté" if ejecutada else "solo recomendé (riesgo alto, sin confirmar)"
            extra = f" [severidad {severidad}]" if severidad else ""
            if ejecutada and exito is not None:
                extra += " (funcionó)" if exito else " (no funcionó)"
            partes.append(f"{fecha}: {estado} {accion} ({razon}){extra}")
        return "Mis últimas decisiones: " + " | ".join(partes)

    if intencion == "cambios_tecnologicos":
        # Chequeo bajo demanda, con Groq -- a diferencia del chequeo
        # automático del scheduler (que corre cada 6h SIN Groq, para
        # no gastar API en cada ciclo), este comando manual sí pide
        # la estimación de Groq porque el usuario lo pidió a propósito.
        hablar("Revisando cambios tecnológicos.")
        import vigilante_tecnologico
        nuevo = vigilante_tecnologico.verificar_actualizacion_os(preguntar_groq_fn=preguntar_groq)
        if nuevo:
            return nuevo

        from memoria import historial_cambios_tecnologicos
        pendientes = historial_cambios_tecnologicos(limite=5, solo_pendientes=True)
        if not pendientes:
            return "No hay cambios tecnológicos pendientes de revisar -- Windows sigue en la misma versión de la última vez."
        partes = [f"{p['fecha']}: {p['version_anterior']} → {p['version_nueva']} (prioridad {p['prioridad']})"
                  for p in pendientes]
        return "Cambios tecnológicos pendientes de revisar: " + " | ".join(partes)

    # Fallback a Groq
    hablar("Consultando.")
    contexto = ", ".join(obtener_contexto())
    return preguntar_groq(orden, contexto_extra=contexto)
