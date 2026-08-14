# ==========================================
# seguridad.py v4.1 - Solo lo esencial
# Bloqueo de pantalla + contraseña
# Sin fotos, sin Pillow, sin basura
# ==========================================

import subprocess
import hashlib
import hmac
import secrets

_intentos_fallidos = 0
MAX_INTENTOS = 3
_hash_contrasena = None
_sal = None


def configurar_seguridad(contrasena):
    """
    Guarda la contraseña como hash (SHA-256 + sal aleatoria), nunca en
    texto plano -- ni siquiera en memoria mientras Ada corre. Antes se
    guardaba tal cual venía del .env y se comparaba con == (ni hash,
    ni tiempo constante). Con esto, aunque alguien consiguiera un
    volcado de memoria del proceso, no encontraría la contraseña
    real, solo su hash -- de ahí no se puede volver para atrás.
    """
    global _hash_contrasena, _sal
    if contrasena:
        _sal = secrets.token_bytes(16)
        _hash_contrasena = hashlib.sha256(_sal + contrasena.encode("utf-8")).digest()
    else:
        _sal = None
        _hash_contrasena = None


def hay_contrasena() -> bool:
    """True si Alejandro configuró CONTRASENA_SECRETA en el .env."""
    return bool(_hash_contrasena)


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

    Compara hashes con hmac.compare_digest (tiempo constante) en vez
    de == -- así el tiempo que tarda la comparación no revela por
    cuántos caracteres coincide el intento, que es la forma clásica
    de ir adivinando una contraseña midiendo microsegundos de más.
    """
    global _intentos_fallidos
    if not _hash_contrasena:
        return True, False

    hash_intento = hashlib.sha256(_sal + intento.encode("utf-8")).digest()
    if hmac.compare_digest(hash_intento, _hash_contrasena):
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
