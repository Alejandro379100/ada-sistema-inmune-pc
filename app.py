# ==========================================
#   app.py v5.0 - Corazón de Ada
#   + 100% modo texto (sin Vosk, sin micrófono)
#   + Al arrancar pregunta: terminal o invisible
#   + Logs con rotación de 5 días, solo lo importante
#   + Hibernación tras inactividad
#   + Arranque automático con Windows
# ==========================================

import os
import sys
import time
import ctypes
import locale
import logging
import logging.handlers
import threading
from dotenv import load_dotenv
from config import MINUTOS_HIBERNACION, LOG_ROTACION_DIAS, LOG_BACKUPS_MAXIMOS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
#   INSTANCIA ÚNICA — nunca dos Adas a la vez
#
#   La tarea programada "Ada - Sistema Inmune Personal" corre con
#   /SC ONLOGON, y Windows Task Scheduler permite instancias en
#   paralelo por defecto: si el evento de logon se dispara más de
#   una vez (reautenticación, desbloqueo contado como logon, etc.),
#   Ada se duplica sola sin que nadie haga nada raro. Cada copia
#   duplicada consume su propia RAM/CPU real — no es un problema de
#   diseño ni de "liviandad" del código, es este bug puntual.
#
#   Se usa un mutex nombrado de Windows (patrón estándar para
#   apps de instancia única): si ya existe, esta copia se cierra
#   de inmediato, ANTES de configurar logging ni tocar nada más.
# ==========================================
if os.name == "nt":
    _NOMBRE_MUTEX = "Global\\Ada_SistemaInmunePersonal_InstanciaUnica"
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, _NOMBRE_MUTEX)
    _ERROR_ALREADY_EXISTS = 183
    if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        try:
            with open(os.path.join(BASE_DIR, "ada_log.txt"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M')} - Ya hay una instancia de Ada corriendo. "
                        f"Esta copia se cierra sola para no duplicar el consumo de recursos.\n")
        except Exception:
            pass
        sys.exit(0)
    # El mutex se mantiene vivo mientras el proceso viva (Windows lo
    # libera solo al cerrarse) — no hace falta guardarlo en ningún
    # lado más que esta variable global, para que no lo recolecte
    # el garbage collector antes de tiempo.

# ==========================================
#   LOGGING — solo lo importante, y se
#   auto-limpia cada 5 días para no llenar
#   el disco de reportes viejos.
# ==========================================


class _FiltroAntiSpam(logging.Filter):
    """
    Si el mismo mensaje de error se repite muchas veces seguidas
    (como pasaba antes con el bug del scheduler), esto evita que
    se llene el log: deja pasar el primero, calla los siguientes
    durante 60 segundos y al final avisa cuántas veces se repitió.
    """

    def __init__(self, ventana_seg=60):
        super().__init__()
        self._ventana = ventana_seg
        self._ultimo_clave = None
        self._ultimo_texto = None
        self._ultimo_ts = 0.0
        self._contador = 0

    def filter(self, record: logging.LogRecord) -> bool:
        clave = f"{record.levelno}:{record.getMessage()[:80]}"
        ahora = time.time()
        if clave == self._ultimo_clave and (ahora - self._ultimo_ts) < self._ventana:
            self._contador += 1
            self._ultimo_ts = ahora
            return False
        # Se captura el texto limpio ANTES de mutar record.msg más abajo.
        # Bug real que esto corrige: antes se guardaba record.getMessage()
        # DESPUÉS de pegarle el prefijo "(el mensaje anterior...)" al
        # record.msg -- entonces la próxima vez el resumen citaba ese
        # prefijo como si fuera el mensaje original, y se anidaba dentro
        # de sí mismo cada vez más largo (visto en un ada_log.txt real:
        # 3 niveles de anidamiento en 20 minutos, siguiendo así para
        # siempre mientras el spam continuara).
        texto_actual = record.getMessage()[:80]
        if self._contador > 0:
            # El resumen se refiere al mensaje ANTERIOR (guardado en
            # self._ultimo_texto), no al mensaje actual que está
            # pasando ahora -- antes esto se pegaba sobre el mensaje
            # nuevo sin decir a cuál se refería, y hacía parecer que
            # el mensaje NUEVO era el que se había repetido, cuando en
            # realidad podía ser cualquier otro completamente distinto.
            record.msg = (f"(el mensaje anterior -- '{self._ultimo_texto}' -- "
                          f"se repitió {self._contador} veces más) {record.msg}")
        self._ultimo_clave = clave
        self._ultimo_texto = texto_actual
        self._ultimo_ts = ahora
        self._contador = 0
        return True


def _configurar_logging():
    ruta_log = os.path.join(BASE_DIR, "ada_log.txt")
    handler = logging.handlers.TimedRotatingFileHandler(
        ruta_log, when="D", interval=LOG_ROTACION_DIAS,
        backupCount=LOG_BACKUPS_MAXIMOS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    handler.addFilter(_FiltroAntiSpam())

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    # httpx/httpcore (los usa el cliente de Groq por dentro) logean
    # CADA request HTTP a nivel INFO -- "200 OK" cada vez que Ada le
    # pregunta algo a Groq, sin aportar nada útil para leer el log.
    # Se sube a WARNING solo para esas dos librerías: los errores reales
    # de conexión siguen apareciendo, pero el "200 OK" de rutina no.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logging.info("Ada v5.0 iniciando...")


_configurar_logging()

# --- Configuración ---
load_dotenv()

GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
CONTRASENA_SECRETA = os.getenv("CONTRASENA_SECRETA")
ADA_IA_DISPONIBLE  = bool(GROQ_API_KEY)

if not GROQ_API_KEY:
    print("⚠️  Falta GROQ_API_KEY — Ada funcionará sin IA.")
if not CONTRASENA_SECRETA:
    print("⚠️  Falta CONTRASENA_SECRETA — Ada sin seguridad por contraseña.")

# --- Módulos de Ada ---
import voz as voz_modulo
import sistema
import seguridad
from ia import (iniciar_groq, autoconocimiento_pc,
                consulta_interna, analizar_proceso_silencioso)
from comandos import procesar_orden
from memoria import inicializar_db

# Fecha en español
for loc in ['es_CO.UTF-8', 'Spanish_Colombia.1252', 'es_ES.UTF-8']:
    try:
        locale.setlocale(locale.LC_TIME, loc)
        break
    except Exception:
        continue


def hablar(texto, prioridad=1):
    voz_modulo.hablar(texto, prioridad)


# ==========================================
#   MODO INVISIBLE — ocultar la ventana
# ==========================================

def _ocultar_consola():
    """Esconde la ventana de la terminal en Windows (nivel dios: Ada
    corre sola en segundo plano sin que se vea nada)."""
    try:
        SW_HIDE = 0
        consola = ctypes.windll.kernel32.GetConsoleWindow()
        if consola:
            ctypes.windll.user32.ShowWindow(consola, SW_HIDE)
    except Exception as e:
        logging.warning(f"[INVISIBLE] No pude ocultar la ventana: {e}")


def _preguntar_modo_arranque() -> str:
    """
    Nivel dios: Ada pregunta al arrancar cómo quieres que corra.
    1) Terminal  -> conversación normal por texto
    2) Invisible -> Ada se esconde y arregla todo sola, sin pedir nada
    """
    print("=" * 52)
    print("   Ada v5.0 — Sistema Inmune Personal")
    print("=" * 52)
    print("  ¿Cómo quieres que arranque?")
    print("  [1] Con terminal   -> puedes escribirle órdenes")
    print("  [2] Invisible      -> corre sola en segundo plano,")
    print("                        optimizando y cuidando el PC")
    print("=" * 52)
    while True:
        try:
            opcion = input("  Elige 1 o 2: ").strip()
        except (EOFError, KeyboardInterrupt):
            opcion = "1"
        if opcion in ("1", "2"):
            return opcion
        print("  Opción inválida, escribe 1 o 2.")


# ==========================================
#   ARRANQUE
# ==========================================

_modo_invisible = "--invisible" in sys.argv
if not _modo_invisible and sys.stdin.isatty():
    _modo_invisible = _preguntar_modo_arranque() == "2"

if _modo_invisible:
    _ocultar_consola()
    logging.info("Ada arrancó en modo invisible (nivel dios, sin interacción).")
else:
    print(f"   Modo: TERMINAL (escribe para interactuar)")
    print("=" * 52)

# 1. Voz (ahora es solo texto — se conserva la función por compatibilidad)
voz_modulo.configurar_voz()
voz_modulo.iniciar_cola_voz()

# 2. SQLite
inicializar_db()

# 3. Groq
iniciar_groq(GROQ_API_KEY)

# 4. Seguridad
seguridad.configurar_seguridad(CONTRASENA_SECRETA)

# 5. Sistema inmune con función de inactividad
sistema.configurar_monitor(
    funcion_hablar       = hablar,
    fn_consulta_interna  = consulta_interna,
    fn_analizar_proceso  = analizar_proceso_silencioso,
    fn_inactividad       = voz_modulo.obtener_inactividad_segundos
)
sistema.iniciar_monitoreo()

# 6. Autoconocimiento
if not _modo_invisible:
    print("🔍 Ada conociendo tu PC...")
resumen_pc, info_pc = autoconocimiento_pc()

# ==========================================
#   HIBERNACIÓN AUTOMÁTICA
#   Ada se duerme tras inactividad para
#   liberar RAM — solo se apaga con el PC
# ==========================================

_hibernando = False


def _monitor_hibernacion():
    global _hibernando
    while True:
        time.sleep(60)
        try:
            inactividad_min = voz_modulo.obtener_inactividad_segundos() / 60
            if inactividad_min >= MINUTOS_HIBERNACION and not _hibernando:
                _hibernando = True
                if not _modo_invisible:
                    print(f"\n💤 Ada: hibernando tras {MINUTOS_HIBERNACION} minutos de inactividad.")
                    print("   Escribe cualquier cosa para despertar a Ada.")
                import gc
                gc.collect()
            elif inactividad_min < MINUTOS_HIBERNACION and _hibernando:
                _hibernando = False
                if not _modo_invisible:
                    print("\n✨ Ada: despertando...")
                    hablar("De vuelta, ¿en qué te ayudo?")
        except Exception:
            pass


threading.Thread(target=_monitor_hibernacion, daemon=True).start()

# ==========================================
#   CONFIGURAR ARRANQUE CON WINDOWS
# ==========================================


def configurar_arranque_windows():
    """Agrega Ada al arranque automático de Windows"""
    try:
        import winreg
        clave    = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
        bat_path = os.path.join(BASE_DIR, "iniciar_ada.bat")
        if not os.path.exists(bat_path):
            print("⚠️  iniciar_ada.bat no encontrado — Ada no quedará en el arranque de Windows.")
            print(f"   Créalo en: {BASE_DIR}")
            return
        reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(reg, "Ada", 0, winreg.REG_SZ, f'"{bat_path}"')
        winreg.CloseKey(reg)
        if not _modo_invisible:
            print("✅ Ada configurada para arrancar con Windows.")
    except Exception as e:
        logging.warning(f"[ARRANQUE] No pude configurar arranque automático: {e}")


configurar_arranque_windows()

# ==========================================
#   BUCLE PRINCIPAL
# ==========================================

# Optimización silenciosa al arrancar — pase lo que pase, Ada
# siempre deja el equipo limpio apenas prende.
resultado_opt = sistema.optimizar_sistema(silencioso=_modo_invisible)

if _modo_invisible:
    # Nivel dios extremo: sin ventana, sin preguntas, solo cuidando
    # el equipo en segundo plano para siempre.
    logging.info("Ada corriendo en modo invisible — cuidando el PC en segundo plano.")
    while True:
        time.sleep(1)
else:
    print("\n✨ Ada v5.0 lista.")
    print("   Escribe en la terminal para interactuar\n")
    hablar("Ada v5.0 lista. Escribo por terminal, sin voz.", prioridad=1)
    if resultado_opt:
        hablar(resultado_opt)
    hablar(resumen_pc)

    # Único modo de entrada: texto por terminal
    voz_modulo.escuchar_texto_emergencia(procesar_orden, hablar)

    # Mantener Ada viva mientras el hilo de texto conversa
    while True:
        time.sleep(1)
