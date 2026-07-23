# ==========================================
#   voz.py v5.0 - Voz de Ada = Terminal de texto
#
#   ANTES: Ada intentaba escuchar por micrófono con Vosk.
#   Vosk (el modelo de reconocimiento de voz en español)
#   fallaba todo el tiempo entendiendo el acento, por eso
#   se quitó por completo. Ada ahora solo funciona por
#   texto — ni escucha ni habla con audio real, todo pasa
#   por la terminal. Esto además la hace más liviana:
#   ya no depende de sounddevice, vosk ni pywin32/SAPI.
#
#   Este archivo se mantiene con el nombre "voz.py" para
#   no romper los imports del resto del proyecto, pero su
#   única función ahora es imprimir en pantalla y llevar
#   el control de actividad/inactividad (usado por el
#   modo enfoque y el aviso de WhatsApp inactivo).
# ==========================================

import time
import queue
import threading

from perfil_pc import PERFIL

# ------------------------------------------
#   ESTADO GLOBAL
# ------------------------------------------
_ada_activa        = True
_ultima_actividad  = time.time()
_print_lock        = threading.Lock()

# Cola de mensajes con prioridad — se conserva por si en el futuro
# Ada evoluciona a tener varias salidas (texto + notificaciones, etc).
_cola_voz         = queue.PriorityQueue()


def configurar_voz():
    """Ya no hay voz real (SAPI) — se conserva la función para no romper app.py."""
    return None


def hablar(texto, prioridad=1):
    """
    Ada 'habla' = Ada escribe en la terminal. Se conserva el
    nombre hablar() porque todo el resto del código (sistema.py,
    comandos.py, medico.py, etc.) lo llama así.

    Usa un candado porque más de un hilo puede llamar a esto al
    mismo tiempo (el scheduler en segundo plano vigilando RAM/CPU/
    Edge/procesos, y la conversación principal por texto) — sin el
    candado, dos mensajes impresos a la vez pueden mezclarse en la
    misma línea de la terminal.
    """
    global _ultima_actividad
    _ultima_actividad = time.time()
    with _print_lock:
        print(f"👩 Ada: {texto}")


def iniciar_cola_voz():
    """No hay hilo de audio que iniciar; se deja como no-operación."""
    pass


def obtener_inactividad_segundos():
    return time.time() - _ultima_actividad


# ------------------------------------------
#   MODO TEXTO — la única forma de hablar con Ada
# ------------------------------------------

def escuchar_texto_emergencia(procesar_orden_fn, hablar_fn):
    """
    El bucle principal de conversación por terminal.
    Se llama 'emergencia' por el nombre histórico, pero
    ahora es el ÚNICO modo de entrada de Ada.
    """
    def _bucle():
        global _ultima_actividad
        print("\n" + "=" * 55)
        print("  ADA v5.0 - Médico autónomo de tu PC (modo texto)")
        print("=" * 55)
        print("  SISTEMA:")
        print("  'como te sientes'     -> salud 0-100")
        print("  'optimiza'            -> limpia RAM y disco")
        print("  'diagnostico'         -> chequeo médico completo")
        print("  'procesos pesados'    -> qué consume más")
        print("  'cuanta ram consume vs code' -> RAM y CPU de VS Code, y por qué")
        print("  'temperatura'         -> calor del procesador")
        print("  PROGRAMAS:")
        print("  'abre chrome'         -> abre Chrome")
        print("  'abre vs code'        -> abre VS Code")
        print("  'cierra edge'         -> cierra Edge")
        print("  CONTROL:")
        print("  'apaga'               -> apaga el PC")
        print("  'salir'               -> cierra Ada")
        print("=" * 55 + "\n")

        while _ada_activa:
            try:
                texto = input("✍️  Tú: ").strip()
                if not texto:
                    continue
                _ultima_actividad = time.time()
                if texto.lower() == "salir":
                    hablar_fn(f"Hasta luego {PERFIL['propietario']}.")
                    import sys
                    sys.exit()
                respuesta = procesar_orden_fn(texto, hablar_fn)
                if respuesta:
                    hablar_fn(respuesta)
            except (EOFError, KeyboardInterrupt):
                break
            except Exception as e:
                print(f"[TEXTO ERROR] {type(e).__name__}: {e}")

    t = threading.Thread(target=_bucle, daemon=True)
    t.start()
