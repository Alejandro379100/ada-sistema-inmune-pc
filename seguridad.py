# ==========================================
#   seguridad.py v4.0 - Solo lo esencial
#   Bloqueo de pantalla + contraseña
#   Sin fotos, sin Pillow, sin basura
# ==========================================

import subprocess

_intentos_fallidos = 0
MAX_INTENTOS = 3
_contrasena = None

def configurar_seguridad(contrasena):
    global _contrasena
    _contrasena = contrasena

def hay_contrasena() -> bool:
    """True si Alejandro configuró CONTRASENA_SECRETA en el .env."""
    return bool(_contrasena)

def bloquear_pantalla():
    try:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"],
                        creationflags=subprocess.CREATE_NO_WINDOW)
        return "Pantalla bloqueada."
    except Exception as e:
        return f"No pude bloquear: {e}"

def intentos_restantes() -> int:
    return max(0, MAX_INTENTOS - _intentos_fallidos)

def verificar_contrasena(intento):
    """
    Devuelve una tupla (correcta, bloqueo_activado).
    bloqueo_activado es True solo en el intento exacto que hizo
    que Ada bloqueara la pantalla por demasiados fallos.
    """
    global _intentos_fallidos
    if not _contrasena:
        return True, False
    if intento == _contrasena:
        _intentos_fallidos = 0
        return True, False
    _intentos_fallidos += 1
    if _intentos_fallidos >= MAX_INTENTOS:
        bloquear_pantalla()
        _intentos_fallidos = 0
        return False, True
    return False, False

def bloquear_equipo():
    return bloquear_pantalla()

def suspender_equipo():
    try:
        subprocess.run(['rundll32.exe', 'powrprof.dll,SetSuspendState', '0,1,0'],
                        creationflags=subprocess.CREATE_NO_WINDOW)
        return 'Equipo suspendido.'
    except Exception as e:
        return f'No pude suspender: {e}'

def modo_seguro():
    return 'Modo seguro activado. Contrasena requerida para continuar.'

