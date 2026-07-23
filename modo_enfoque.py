# ==========================================
#   modo_enfoque.py v1.0
#   Pomodoro + sin distracciones
#   Ada desactiva notificaciones y cierra
#   Edge/WhatsApp para que programes en paz
# ==========================================

import subprocess
import threading
import time
import logging

_timer_activo   = False
_hilo_pomodoro  = None
_hablar_fn      = None
DURACION_MIN    = 25
DESCANSO_MIN    = 5

def configurar(hablar_fn):
    global _hablar_fn
    _hablar_fn = hablar_fn

def _desactivar_notificaciones():
    try:
        script = """
        $path = 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings'
        Set-ItemProperty -Path $path -Name 'NOC_GLOBAL_SETTING_TOASTS_ENABLED' -Value 0 -Type DWord -Force
        """
        subprocess.run(["powershell", "-Command", script],
                      capture_output=True, timeout=10,
                      creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        logging.error(f"[ENFOQUE] No pude desactivar notificaciones: {e}")

def _activar_notificaciones():
    try:
        script = """
        $path = 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings'
        Set-ItemProperty -Path $path -Name 'NOC_GLOBAL_SETTING_TOASTS_ENABLED' -Value 1 -Type DWord -Force
        """
        subprocess.run(["powershell", "-Command", script],
                      capture_output=True, timeout=10,
                      creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        logging.error(f"[ENFOQUE] No pude activar notificaciones: {e}")

def _cerrar_distracciones():
    distracciones = ["msedge.exe", "WhatsApp.exe", "Spotify.exe"]
    for exe in distracciones:
        subprocess.run(["taskkill", "/f", "/im", exe],
                      capture_output=True, timeout=5,
                      creationflags=subprocess.CREATE_NO_WINDOW)

def _bucle_pomodoro():
    global _timer_activo
    ciclo = 1
    while _timer_activo:
        if _hablar_fn:
            _hablar_fn(
                f"Ciclo {ciclo} iniciado. Tienes {DURACION_MIN} minutos para programar. "
                f"Yo te aviso cuando descansar."
            )
        # Esperar duracion del pomodoro
        for _ in range(DURACION_MIN * 60):
            if not _timer_activo:
                return
            time.sleep(1)

        if not _timer_activo:
            return

        if _hablar_fn:
            _hablar_fn(
                f"Ciclo {ciclo} completado. Descansa {DESCANSO_MIN} minutos. "
                f"Alejate de la pantalla, estira los ojos."
            )
        # Esperar descanso
        for _ in range(DESCANSO_MIN * 60):
            if not _timer_activo:
                return
            time.sleep(1)

        ciclo += 1

def activar(hablar_fn=None) -> str:
    global _timer_activo, _hilo_pomodoro, _hablar_fn
    if hablar_fn:
        _hablar_fn = hablar_fn
    if _timer_activo:
        return "El modo enfoque ya esta activo."

    _timer_activo = True
    _desactivar_notificaciones()
    _cerrar_distracciones()

    _hilo_pomodoro = threading.Thread(target=_bucle_pomodoro, daemon=True)
    _hilo_pomodoro.start()

    return (
        "Modo enfoque activado. Cerre Edge, WhatsApp y Spotify. "
        "Desactive las notificaciones de Windows. "
        f"Tienes {DURACION_MIN} minutos de enfoque puro. Yo te aviso cuando descansar. "
        "Di modo normal para salir."
    )

def desactivar() -> str:
    global _timer_activo
    if not _timer_activo:
        return "El modo enfoque no estaba activo."
    _timer_activo = False
    _activar_notificaciones()
    return "Modo normal activado. Notificaciones restauradas. Buen trabajo."

def esta_activo() -> bool:
    return _timer_activo

def estado() -> str:
    if _timer_activo:
        return f"Modo enfoque activo. Ciclos Pomodoro de {DURACION_MIN} minutos corriendo."
    return "Modo normal. Sin enfoque activo."
