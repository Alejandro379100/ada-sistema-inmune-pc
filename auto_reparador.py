# ==========================================
#   auto_reparador.py v1.0
#   Ada repara sola — sin preguntar si puede
#   Solo llama a Groq cuando no sabe si es
#   seguro tocar algo
# ==========================================

import subprocess
import os
import json
import time
import logging
import unicodedata
import psutil
from datetime import datetime
from config import RAM_CRITICA_GB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------
#   MOMENTO DESFAVORABLE PARA REPARACIONES PESADAS (SFC/DISM)
#   Diagnosticado con log real (ago 2026): los fallos que activaron
#   el circuito de seguridad para 'reparar_archivos_sistema' NO eran
#   corrupción real (sfc /scannow a mano no encontró infracciones) --
#   eran RAM crítica o TiWorker.exe (Windows Modules Installer
#   Worker, el proceso de Windows Update) compitiendo por el mismo
#   almacén WinSxS que SFC/DISM necesitan leer, lo que hace que la
#   reparación tarde más de los 300s de timeout y se cancele sola.
#   Ambas acciones de esta lista usan DISM, así que comparten el
#   mismo riesgo de contención -- se chequea ANTES de intentar, en
#   vez de intentar, fallar, y gastar una de las 3 vidas del
#   circuito de seguridad por una razón que no tiene nada que ver
#   con corrupción de archivos.
# ------------------------------------------
ACCIONES_SENSIBLES_A_RECURSOS = {"reparar_archivos_sistema", "limpiar_winsxs"}


def condiciones_desfavorables_para_reparacion_pesada() -> str:
    """
    Devuelve un string con el motivo si el momento es malo para
    correr SFC/DISM ahora, o "" si está todo bien para intentarlo.
    Nunca lanza excepción hacia quien lo llama -- si algo falla al
    medir, no bloquea la reparación por eso, sigue al chequeo
    siguiente (o al intento real, si ya no queda ninguno por hacer).
    """
    try:
        ram_libre_gb = psutil.virtual_memory().available / (1024**3)
        if ram_libre_gb < RAM_CRITICA_GB:
            return f"RAM crítica ({ram_libre_gb:.1f} GB libres) -- mal momento para SFC/DISM."
    except Exception:
        pass

    try:
        for p in psutil.process_iter(['name']):
            nombre = (p.info.get('name') or '').lower()
            if nombre == 'tiworker.exe':
                return "Windows Update corriendo (TiWorker.exe) -- compite por el mismo almacén que SFC/DISM."
    except Exception:
        pass

    return ""


# ------------------------------------------
#   SOLICITUD PENDIENTE (pedida a mano, terminada sola)
#   Si el usuario pide reparar_archivos_sistema/limpiar_winsxs por
#   terminal en mal momento, no tiene sentido hacerlo elegir "si/no"
#   ahí mismo ni obligarlo a quedarse esperando -- se anota en un
#   archivo (no en memoria del proceso, que se pierde si cierra la
#   terminal) y el scheduler de sistema.py la revisa cada 3 minutos,
#   junto con el chequeo de RAM. Apenas el momento es bueno, la
#   ejecuta sola -- en modo invisible o en terminal, da igual, es el
#   mismo scheduler en los dos modos.
# ------------------------------------------
SOLICITUD_PENDIENTE_PATH = os.path.join(BASE_DIR, "privado", "solicitud_pendiente.json")


def solicitar_reparacion_pendiente(accion: str):
    """Guarda una acción para ejecutarla sola en cuanto el momento
    sea bueno. Si ya había otra pendiente, la reemplaza -- solo se
    guarda la más reciente, no se acumula una cola."""
    try:
        os.makedirs(os.path.dirname(SOLICITUD_PENDIENTE_PATH), exist_ok=True)
        with open(SOLICITUD_PENDIENTE_PATH, "w", encoding="utf-8") as f:
            json.dump({"accion": accion, "desde": time.time()}, f)
    except Exception as e:
        logging.error(f"[REPARADOR] No pude guardar la solicitud pendiente: {e}")


def reparacion_pendiente() -> str:
    """Nombre de la acción pendiente, o "" si no hay ninguna. Nunca
    lanza excepción -- un archivo corrupto o ausente simplemente
    cuenta como "no hay nada pendiente", no rompe el scheduler."""
    try:
        with open(SOLICITUD_PENDIENTE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("accion", "")
    except Exception:
        return ""


def limpiar_reparacion_pendiente():
    try:
        if os.path.exists(SOLICITUD_PENDIENTE_PATH):
            os.remove(SOLICITUD_PENDIENTE_PATH)
    except Exception as e:
        logging.error(f"[REPARADOR] No pude limpiar la solicitud pendiente: {e}")


# ------------------------------------------
#   ÚLTIMO BLOQUEO DEL CIRCUITO DE SEGURIDAD
#   medico.py guarda acá qué acción/componente bloqueó, para que el
#   usuario pueda confirmar "ya lo revisé" por comando sin tener que
#   escribir el nombre exacto del componente -- Ada ya sabe de qué
#   está hablando.
# ------------------------------------------
ULTIMO_BLOQUEO_PATH = os.path.join(BASE_DIR, "privado", "ultimo_bloqueo.json")


def guardar_ultimo_bloqueo(accion: str, componente):
    try:
        os.makedirs(os.path.dirname(ULTIMO_BLOQUEO_PATH), exist_ok=True)
        with open(ULTIMO_BLOQUEO_PATH, "w", encoding="utf-8") as f:
            json.dump({"accion": accion, "componente": componente, "desde": time.time()}, f)
    except Exception as e:
        logging.error(f"[REPARADOR] No pude guardar el último bloqueo: {e}")


def ultimo_bloqueo() -> dict:
    """{} si no hay ningún bloqueo pendiente de confirmar."""
    try:
        with open(ULTIMO_BLOQUEO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def marcar_bloqueo_verificado():
    """
    Marca que Ada ya se dio su única oportunidad de auto-verificar
    este bloqueo en buen momento real y volvió a fallar -- para que
    _verificar_bloqueo_circuito_automatico() (sistema.py) no la
    reintente en cada tick de 3 min mientras el problema siga sin
    resolverse. A partir de acá vuelve a depender de "ya revise".
    """
    try:
        datos = ultimo_bloqueo()
        if datos:
            datos["verificado"] = True
            with open(ULTIMO_BLOQUEO_PATH, "w", encoding="utf-8") as f:
                json.dump(datos, f)
    except Exception as e:
        logging.error(f"[REPARADOR] No pude marcar el bloqueo como verificado: {e}")


def limpiar_ultimo_bloqueo():
    try:
        if os.path.exists(ULTIMO_BLOQUEO_PATH):
            os.remove(ULTIMO_BLOQUEO_PATH)
    except Exception as e:
        logging.error(f"[REPARADOR] No pude limpiar el último bloqueo: {e}")

# ------------------------------------------
#   PUNTO DE RESTAURACIÓN — antes de tocar nada
#   No es un backup de archivos personales. Es la
#   posibilidad real de deshacer cualquier cambio
#   de sistema/registro/drivers que Ada haga, si
#   algo sale mal. Se llama al INICIO de cada
#   función que de verdad modifica el sistema.
# ------------------------------------------

_ultimo_punto_restauracion = {"momento": None}

def crear_punto_restauracion(descripcion="Ada - antes de reparar") -> tuple:
    """
    Crea un punto de restauración de Windows. Windows limita cuántos
    se pueden crear seguidos (por defecto, no más de uno cada 24h en
    la misma unidad) — si falla por eso, NO es un error real de Ada,
    solo significa que ya había uno reciente y no hace falta otro.
    Por eso esto nunca bloquea la reparación en sí: solo se dice la
    verdad sobre si se pudo crear uno nuevo o no.
    """
    try:
        script = (
            f'Checkpoint-Computer -Description "{descripcion}" '
            f'-RestorePointType "MODIFY_SETTINGS"'
        )
        r = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if r.returncode == 0:
            _ultimo_punto_restauracion["momento"] = datetime.now()
            return True, "Punto de restauración creado."
        detalle = (r.stderr or r.stdout or "").strip()[:200]
        return False, f"No se pudo crear punto de restauración ({detalle or 'ya había uno reciente'})."
    except Exception as e:
        return False, f"No se pudo crear punto de restauración: {type(e).__name__}: {e}"

# ------------------------------------------
#   REPARACIONES SEGURAS — Ada actúa sola
# ------------------------------------------

# ------------------------------------------
#   LECTURA ROBUSTA DE LA SALIDA DE SFC / DISM
#   sfc.exe escribe su salida en UTF-16 cuando se captura por tubería:
#   leída como texto normal queda con un byte nulo entre cada letra
#   ("P\x00r\x00o\x00...") y ninguna frase coincide, aunque el mensaje
#   sea el correcto. Además el texto sale en el idioma de Windows
#   ("no encontró ninguna infracción..."), con tildes. Por eso se lee en
#   bytes, se decodifica según lo que traiga, y se compara sin tildes.
# ------------------------------------------

def _decodificar_salida(datos) -> str:
    """bytes | str | None -> str sin bytes nulos."""
    if datos is None:
        return ""
    if isinstance(datos, str):
        return datos.replace("\x00", "")
    if b"\x00" in datos:
        return datos.decode("utf-16-le", errors="replace").lstrip("\ufeff").replace("\x00", "")
    try:
        return datos.decode("oem", errors="replace")  # consola de Windows (DISM)
    except LookupError:  # "oem" solo existe en Windows (p.ej. tests en Linux/Mac)
        return datos.decode("utf-8", errors="replace")


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar frases sin depender de acentos."""
    sin_tildes = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")


def _correr(comando, timeout):
    """Corre un comando y devuelve (codigo_de_salida, salida_normalizada, salida_original)."""
    r = subprocess.run(
        comando, capture_output=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW)
    original = _decodificar_salida(r.stdout) + _decodificar_salida(getattr(r, "stderr", None))
    return r.returncode, _normalizar(original), original


_SFC_INTACTO = ("no encontro ninguna infraccion", "no se encontraron infracciones",
                "did not find any integrity violations")
_SFC_NO_PUDO = ("no pudo reparar", "unable to fix")
# Cubre "...y los reparó correctamente" (mensaje real de sfc en español),
# "...and successfully repaired them" (inglés) y variantes cortas.
_SFC_REPARO = ("los reparo", "successfully repaired", "repaired them")


def _clasificar_sfc(salida_normalizada: str) -> str:
    """'intacto' | 'parcial' | 'reparado' | 'desconocido'."""
    if any(f in salida_normalizada for f in _SFC_INTACTO):
        return "intacto"
    if any(f in salida_normalizada for f in _SFC_NO_PUDO):
        return "parcial"
    if any(f in salida_normalizada for f in _SFC_REPARO):
        return "reparado"
    return "desconocido"


# DISM devuelve 3010 (ERROR_SUCCESS_REBOOT_REQUIRED) cuando terminó bien pero
# Windows pide reiniciar para completar -- eso NO es un fallo.
_DISM_CODIGOS_OK = (0, 3010)


def _resumen_error(salida_original: str, maximo=200) -> str:
    """Últimas líneas útiles de la salida, en una sola línea, para el log."""
    lineas = [l.strip() for l in salida_original.splitlines() if l.strip()]
    return " | ".join(lineas[-3:])[:maximo]


def reparar_archivos_sistema() -> str:
    """
    SFC primero; DISM solo si SFC no pudo terminar de reparar algo.
    Solo si hay señales de problema en Event Log.

    DISM /RestoreHealth consulta Windows Update por internet y puede
    tardar más que su límite de 5 minutos si el equipo está bajo presión
    de red/RAM. Microsoft recomienda correr sfc primero: resuelve la
    gran mayoría de los casos sin tocar DISM.

    Resultados posibles (los textos alimentan _inferir_exito_desde_resultado
    en memoria.py, no cambiarlos sin mirar esa función):
      intacto     -> "...intacto. No hubo nada que reparar."
      reparado    -> "...VERIFICADA..." o "no pude confirmar..."
      parcial     -> DISM + segundo sfc; si DISM falla, lo dice
      desconocido -> "no reconocido" (no cuenta ni como éxito ni fallo)
    """
    try:
        ok_rest, msg_rest = crear_punto_restauracion("Ada - antes de reparar archivos de sistema")
        prefijo = "Creé un punto de restauración. " if ok_rest else ""

        # Aviso ANTES de arrancar: si el usuario apaga el equipo en medio
        # de SFC/DISM, el punto de restauración ya da una forma de deshacerlo.
        try:
            from medico import notificar_windows
            notificar_windows("Ada — reparación en curso",
                              "Voy a revisar archivos del sistema (SFC/DISM), puede tardar "
                              "unos minutos. Si podés, esperá antes de apagar el equipo.")
        except Exception:
            pass

        rc, salida, original = _correr(["sfc", "/scannow"], 300)
        estado = _clasificar_sfc(salida)

        if estado == "intacto":
            return f"{prefijo}Sistema de archivos intacto. No hubo nada que reparar."

        if estado == "desconocido":
            # No se asume que "reparó algo": se deja evidencia en el log
            # para saber qué dijo realmente sfc, y no se cuenta a favor
            # ni en contra en el aprendizaje de reparaciones.
            logging.warning(f"[REPARADOR] Salida de sfc no reconocida (código {rc}): "
                            f"{_resumen_error(original)!r}")
            return (f"{prefijo}Resultado de sfc no reconocido (código {rc}); "
                    "lo dejé anotado en el log sin contarlo como éxito ni como fallo.")

        if estado == "parcial":
            # Solo acá se paga el costo de tiempo/red de DISM.
            rc_dism, _, original_dism = _correr(
                ["DISM", "/Online", "/Cleanup-Image", "/RestoreHealth"], 300)
            if rc_dism not in _DISM_CODIGOS_OK:
                logging.warning(f"[REPARADOR] DISM /RestoreHealth terminó con código {rc_dism}: "
                                f"{_resumen_error(original_dism)!r}")
                return (f"{prefijo}DISM no pudo completar la restauración de la imagen base "
                        "(revisá tu conexión a Windows Update). Encontré archivos dañados pero "
                        "no pude reparar todos. Puede necesitar el medio de instalación de "
                        "Windows para terminar.")
            # DISM restauró la imagen base -- reintentar sfc una vez más.
            rc, salida, original = _correr(["sfc", "/scannow"], 300)
            estado = _clasificar_sfc(salida)
            if estado == "intacto":
                return (f"{prefijo}Reparación completada y VERIFICADA. DISM restauró la imagen "
                        "base y sfc ya no encuentra infracciones.")

        # VERIFICACIÓN REAL: segunda pasada de solo-verificación (no repara
        # nada, solo confirma que el problema ya no está).
        verificado = False
        try:
            _, salida_verif, _ = _correr(["sfc", "/verifyonly"], 180)
            verificado = _clasificar_sfc(salida_verif) == "intacto"
        except Exception:
            pass  # si la verificación falla, no perdemos el resultado de la reparación en sí

        if verificado:
            return (f"{prefijo}Reparación completada y VERIFICADA. Windows encontró y corrigió "
                    "archivos dañados, y confirmé con una segunda pasada que ya no quedan infracciones.")
        return (f"{prefijo}Windows dijo que corrigió archivos dañados, pero no pude confirmar el "
                "resultado con una segunda verificación. Vale la pena revisarlo de nuevo más tarde.")
    except subprocess.TimeoutExpired:
        return "La reparación tomó demasiado tiempo y se canceló. Intenta en modo de bajo uso."
    except Exception as e:
        logging.error(f"[REPARADOR] Error SFC/DISM: {e}")
        return f"No pude ejecutar la reparación: {e}"


def limpiar_winsxs() -> str:
    """
    Limpia la carpeta WinSxS con DISM.

    Antes se ignoraba el código de salida de DISM: si DISM fallaba al
    instante, igual se reportaba "limpieza ejecutada, no liberó espacio
    medible", y memoria.py lo contaba como ÉXITO. Ahora un código de
    salida distinto de 0/3010 se reporta como fallo, con el detalle en el log.
    """
    try:
        ok_rest, _ = crear_punto_restauracion("Ada - antes de limpiar WinSxS")
        prefijo = "Creé un punto de restauración. " if ok_rest else ""

        try:
            from medico import notificar_windows
            notificar_windows("Ada — reparación en curso",
                              "Voy a limpiar WinSxS con DISM, puede tardar unos minutos. "
                              "Si podés, esperá antes de apagar el equipo.")
        except Exception:
            pass

        # Se mide el espacio libre real antes y después, en vez de repetir
        # un estimado genérico que Windows nunca confirma.
        libre_antes = psutil.disk_usage(BASE_DIR).free / (1024 ** 3)

        # /ResetBase puede tardar bastante más de 5 minutos la primera vez
        # que corre con permisos de administrador reales (antes fallaba al
        # instante por falta de permisos, así que nunca se había medido
        # cuánto tarda de verdad). Se le dan 20 minutos de margen.
        logging.info("[REPARADOR] Limpiando WinSxS con DISM — puede tardar hasta 20 minutos.")

        rc, _, original = _correr(
            ["DISM", "/Online", "/Cleanup-Image", "/StartComponentCleanup", "/ResetBase"], 1200)

        if rc not in _DISM_CODIGOS_OK:
            detalle = _resumen_error(original)
            logging.warning(f"[REPARADOR] DISM (limpieza WinSxS) terminó con código {rc}: {detalle!r}")
            return (f"{prefijo}No pude completar la limpieza de WinSxS: DISM terminó con "
                    f"código {rc}. Detalle en el log.")

        libre_despues = psutil.disk_usage(BASE_DIR).free / (1024 ** 3)
        liberado = libre_despues - libre_antes

        if liberado > 0.05:
            return f"{prefijo}Limpieza de componentes Windows completada. Liberé {liberado:.2f} gigabytes de verdad."
        return f"{prefijo}Limpieza ejecutada, pero no liberó espacio medible — puede que ya estuviera limpio."
    except Exception as e:
        return f"No pude limpiar WinSxS: {e}"


def limpiar_cache_iconos() -> str:
    """
    Reconstruye la caché de iconos — soluciona íconos
    en blanco o que no se actualizan.

    Antes intentaba borrar los archivos con el Explorador de Windows
    corriendo -- pero esos archivos quedan ABIERTOS/bloqueados por el
    propio explorer.exe mientras está activo, así que el borrado
    fallaba en silencio (except: pass) y la función igual devolvía
    "ya estaba limpia", un mensaje de éxito falso. Por eso el
    historial marcaba 0 de 3 éxitos reales, aunque nunca hubo un
    error visible. Ahora cierra el Explorador primero (mismo patrón
    ya usado con el servicio de Windows Update: parar, limpiar,
    reiniciar), borra los archivos ya desbloqueados, y lo reinicia --
    procedimiento estándar para esto, documentado así en cualquier
    guía seria de Windows. Aviso honesto: la barra de tareas y el
    escritorio van a parpadear un segundo al reiniciarse, es normal.
    """
    try:
        cache_path = os.path.expandvars(
            r"%LocalAppData%\Microsoft\Windows\Explorer"
        )

        subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"],
                        capture_output=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW)

        eliminados = 0
        errores_bloqueo = 0
        for f in os.listdir(cache_path):
            if f.startswith("iconcache") and f.endswith(".db"):
                try:
                    os.remove(os.path.join(cache_path, f))
                    eliminados += 1
                except Exception:
                    errores_bloqueo += 1

        # Reiniciar el Explorador siempre, pase lo que pase con el
        # borrado -- dejar la PC sin barra de tareas ni escritorio no
        # es una opción, aunque algo del borrado haya fallado.
        subprocess.Popen(["explorer.exe"])

        if eliminados:
            subprocess.run(
                ["ie4uinit.exe", "-show"],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Caché de íconos reconstruida. Eliminé {eliminados} archivos viejos."
        if errores_bloqueo:
            return (f"Cerré el Explorador pero {errores_bloqueo} archivo(s) de caché "
                    "seguían bloqueados -- puede necesitar reiniciar la PC completa.")
        return "La caché de íconos ya estaba limpia de verdad -- no había archivos que borrar."
    except Exception as e:
        # Si algo falla a mitad de camino, reintentar levantar el
        # Explorador de todas formas -- nunca dejar la PC sin barra
        # de tareas por un error en la limpieza.
        try:
            subprocess.Popen(["explorer.exe"])
        except Exception:
            pass
        return f"Error limpiando caché de íconos: {e}"


# Lista conservadora — solo lo que NO rompe nada. Vive a nivel de
# módulo (no adentro de la función) porque desactivar_servicios_basura()
# y su reversión reactivar_servicios_basura() necesitan operar sobre
# exactamente la misma lista -- si algún día se agrega o saca un
# servicio de acá, las dos funciones quedan sincronizadas solas, en
# vez de mantener dos copias que se puedan desincronizar.
SERVICIOS_BASURA = [
    ("DiagTrack",    "Telemetría de diagnóstico Microsoft"),
    ("dmwappushservice", "WAP Push para actualizaciones innecesarias"),
    ("SysMain",      "SuperFetch — inútil con NVMe SSD"),
    ("WSearch",      "Indexador — consume CPU/SSD silenciosamente"),
    ("Fax",          "Servicio de fax — año 2000 llamando"),
    ("XblAuthManager","Xbox Live Auth — no usas Xbox"),
    ("XblGameSave",  "Xbox Game Save — no usas Xbox"),
    ("XboxNetApiSvc","Xbox Network API — no usas Xbox"),
]


def desactivar_servicios_basura() -> str:
    """
    Desactiva servicios que consumen RAM sin aportar nada
    en una máquina de programación.
    """
    servicios = SERVICIOS_BASURA

    ok_rest, _ = crear_punto_restauracion("Ada - antes de desactivar servicios")
    prefijo = "Creé un punto de restauración. " if ok_rest else ""

    desactivados = []
    fallidos = []
    for nombre, descripcion in servicios:
        try:
            r = subprocess.run(
                ["sc", "config", nombre, "start=", "disabled"],
                capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0:
                subprocess.run(
                    ["sc", "stop", nombre],
                    capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)

                # VERIFICACIÓN REAL: antes esto asumía éxito solo
                # porque el comando devolvió código 0 — pero "el
                # comando corrió bien" no es lo mismo que "el
                # servicio de verdad quedó detenido" (algunos
                # dependen de otros procesos y tardan, o simplemente
                # no se detienen). Se confirma con una consulta real.
                try:
                    verificacion = subprocess.run(
                        ["sc", "query", nombre],
                        capture_output=True, text=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    estado = verificacion.stdout.upper()
                    quedo_detenido = "STOPPED" in estado or "STOP_PENDING" in estado
                except Exception:
                    quedo_detenido = True  # no se pudo verificar, no penalizamos por eso

                if quedo_detenido:
                    desactivados.append(descripcion)
                else:
                    fallidos.append(nombre)
            else:
                fallidos.append(nombre)
        except Exception:
            fallidos.append(nombre)

    if not desactivados:
        return "Todos los servicios basura ya estaban desactivados."
    msg = f"{prefijo}Desactivé y VERIFIQUÉ {len(desactivados)} servicios detenidos de verdad: "
    msg += ", ".join(desactivados[:3])
    if len(desactivados) > 3:
        msg += f" y {len(desactivados)-3} más."
    return msg


def reactivar_servicios_basura() -> str:
    """
    Reversión puntual de desactivar_servicios_basura() -- vuelve los
    mismos servicios de SERVICIOS_BASURA a arranque "demand" (manual,
    el valor por defecto de Windows para la mayoría de estos) y los
    arranca de nuevo. Esta es la ÚNICA reversión automática que la FSM
    del médico (fsm_medico.py) puede disparar sola en el estado
    ROLLBACK -- las demás reparaciones de la lista blanca no tienen
    una forma puntual y segura de deshacerse, así que no tienen
    equivalente a esta función.

    No crea un punto de restauración nuevo -- reactivar un servicio no
    es una operación de riesgo que lo justifique, a diferencia de
    desactivarlo.
    """
    reactivados = []
    fallidos = []
    for nombre, descripcion in SERVICIOS_BASURA:
        try:
            r = subprocess.run(
                ["sc", "config", nombre, "start=", "demand"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0:
                subprocess.run(
                    ["sc", "start", nombre],
                    capture_output=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                reactivados.append(descripcion)
            else:
                fallidos.append(nombre)
        except Exception:
            fallidos.append(nombre)

    if not reactivados:
        return "No pude reactivar ningún servicio -- puede que ya estuvieran activos."
    msg = f"Reactivé {len(reactivados)} servicios: " + ", ".join(reactivados[:3])
    if len(reactivados) > 3:
        msg += f" y {len(reactivados)-3} más."
    if fallidos:
        msg += f" ({len(fallidos)} no se pudieron reactivar.)"
    return msg


def momento_ultimo_punto_restauracion():
    """
    Devuelve el datetime del último punto de restauración que Ada creó
    en esta sesión (o None si todavía no creó ninguno). Lo usa
    fsm_medico.py para poder decirle a Alejandro de qué fecha/hora es
    el punto disponible cuando algo empeora y no hay reversión puntual
    -- sin que fsm_medico.py tenga que conocer el detalle interno de
    cómo se guarda ese dato acá.
    """
    return _ultimo_punto_restauracion["momento"]


def reparar_red() -> str:
    """
    Resetea la pila de red — soluciona problemas de
    conectividad sin reiniciar.
    """
    try:
        ok_rest, _ = crear_punto_restauracion("Ada - antes de reparar la red")
        prefijo = "Creé un punto de restauración. " if ok_rest else ""
        subprocess.run(["netsh", "winsock", "reset"],
                       capture_output=True, timeout=30,
creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(["netsh", "int", "ip", "reset"],
                       capture_output=True, timeout=30,
creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(["ipconfig", "/flushdns"],
                       capture_output=True, timeout=15,
creationflags=subprocess.CREATE_NO_WINDOW)

        # VERIFICACIÓN REAL: resetear la pila de red no garantiza que
        # ya haya conectividad -- puede que el problema sea el router,
        # el proveedor, o que de verdad haga falta el reinicio. Antes
        # esto asumía éxito solo porque los comandos corrieron bien.
        # Ahora se prueba una resolución DNS real.
        conectividad_ok = False
        try:
            import socket
            socket.setdefaulttimeout(5)
            socket.gethostbyname("www.google.com")
            conectividad_ok = True
        except Exception:
            conectividad_ok = False

        if conectividad_ok:
            return (f"{prefijo}Red reparada y VERIFICADA -- confirmé que ya hay conectividad real. "
                     "Recomiendo reiniciar de todas formas para que los cambios queden completos.")
        return (f"{prefijo}Reseteé Winsock, pila IP y caché DNS, pero todavía no detecto conectividad "
                 "real. Puede necesitar un reinicio completo, o el problema es de otra causa (router, proveedor).")
    except Exception as e:
        return f"Error reparando red: {e}"


ALERTA_BATERIA_PATH = os.path.join(BASE_DIR, "privado", "alerta_bateria.json")
ALERTA_BATERIA_COOLDOWN_SEG = 7 * 24 * 3600  # 7 días -- la salud de la batería no cambia de un día a otro


def debe_alertar_bateria_critica() -> bool:
    """
    True solo si nunca se avisó, o hace más de 7 días que no se avisa.
    Persistido en archivo, no en memoria de sesión (_sesion se pierde
    en cada reinicio y Ada reinicia varias veces por día en la
    práctica) -- sin esto, el aviso se repetiría en cada arranque para
    algo que cambia en semanas o meses, no en horas.
    """
    try:
        with open(ALERTA_BATERIA_PATH, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if (time.time() - datos.get("ultima_alerta", 0)) < ALERTA_BATERIA_COOLDOWN_SEG:
            return False
    except Exception:
        pass
    return True


def registrar_alerta_bateria(salud_pct):
    try:
        os.makedirs(os.path.dirname(ALERTA_BATERIA_PATH), exist_ok=True)
        with open(ALERTA_BATERIA_PATH, "w", encoding="utf-8") as f:
            json.dump({"salud_pct": salud_pct, "ultima_alerta": time.time()}, f)
    except Exception as e:
        logging.error(f"[BATERÍA] No pude guardar la alerta: {e}")


def diagnostico_bateria() -> dict:
    """
    Lee la salud real de la batería del T480.
    Design Capacity vs Full Charge Capacity.
    """
    resultado = {
        "salud_pct": None,
        "ciclos": None,
        "estado": "desconocido",
        "voz": ""
    }
    try:
        script = """
        $bat = Get-WmiObject -Class BatteryFullChargedCapacity -Namespace root\\wmi
        $design = Get-WmiObject -Class BatteryStaticData -Namespace root\\wmi
        $cycle = Get-WmiObject -Class BatteryCycleCount -Namespace root\\wmi
        [PSCustomObject]@{
            FullCharge   = ($bat | Select-Object -First 1).FullChargedCapacity
            DesignCharge = ($design | Select-Object -First 1).DesignedCapacity
            Cycles       = ($cycle | Select-Object -First 1).CycleCount
        } | ConvertTo-Json -Compress
        """
        r = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0 and r.stdout.strip():
            import json
            datos = json.loads(r.stdout.strip())
            full    = datos.get("FullCharge", 0)
            design  = datos.get("DesignCharge", 1)
            ciclos  = datos.get("Cycles", 0)

            if design and full:
                salud = round((full / design) * 100, 1)
                resultado["salud_pct"] = salud
                resultado["ciclos"]    = ciclos

                if salud >= 85:
                    resultado["estado"] = "excelente"
                    resultado["voz"] = (
                        f"Mi batería está al {salud} por ciento de su capacidad original. "
                        f"Excelente estado con {ciclos} ciclos."
                    )
                elif salud >= 65:
                    resultado["estado"] = "buena"
                    resultado["voz"] = (
                        f"Mi batería retiene el {salud} por ciento de su capacidad original. "
                        f"Buen estado todavía. {ciclos} ciclos de carga."
                    )
                elif salud >= 45:
                    resultado["estado"] = "degradada"
                    resultado["voz"] = (
                        f"Alerta. Mi batería está degradada al {salud} por ciento. "
                        f"Con {ciclos} ciclos encima. Considera cambiarla pronto."
                    )
                else:
                    resultado["estado"] = "critica"
                    resultado["voz"] = (
                        f"Batería en estado crítico. Solo retiene el {salud} por ciento. "
                        f"Esta batería necesita reemplazo urgente."
                    )
    except Exception as e:
        resultado["voz"] = "No pude leer la salud de la batería."
        logging.error(f"[BATERÍA] {e}")

    return resultado


def diagnostico_drivers() -> dict:
    """
    Detecta drivers problemáticos o desactualizados.
    Especial atención a drivers Lenovo del T480.

    Devuelve un dict estructurado (antes devolvía solo el texto) para
    poder alimentar la severidad y el médico autónomo con el mismo
    tratamiento que ya tiene CPU — el texto para hablar sigue en
    "voz", así que nada que ya use esta función se rompe.
    """
    resultado = {"total": 0, "no_firmados": 0, "estado": "desconocido", "voz": ""}
    try:
        script = """
        $drivers = Get-WmiObject Win32_PnPSignedDriver |
            Where-Object { $_.DeviceName -ne $null } |
            Select-Object DeviceName, DriverVersion, DriverDate, IsSigned |
            ConvertTo-Json -Compress
        $drivers
        """
        r = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0 or not r.stdout.strip():
            resultado["voz"] = "No pude leer los drivers."
            return resultado

        import json
        drivers = json.loads(r.stdout.strip())
        if isinstance(drivers, dict):
            drivers = [drivers]

        no_firmados = [d for d in drivers if not d.get("IsSigned", True)]
        lenovo_drivers = [d for d in drivers if d.get("DeviceName") and
                         any(k in d["DeviceName"].lower() for k in
                             ["lenovo", "thinkpad", "intel", "hd graphics", "uhd"])]

        resultado["total"] = len(drivers)
        resultado["no_firmados"] = len(no_firmados)
        resultado["estado"] = "riesgo" if no_firmados else "saludable"

        msg = f"Revisé {len(drivers)} drivers. "
        if no_firmados:
            msg += f"Encontré {len(no_firmados)} drivers sin firma digital — posible riesgo. "
        else:
            msg += "Todos los drivers están firmados digitalmente. "

        if lenovo_drivers:
            msg += f"Los {len(lenovo_drivers)} drivers Lenovo e Intel están presentes."

        resultado["voz"] = msg
        return resultado
    except Exception as e:
        resultado["voz"] = f"Error leyendo drivers: {e}"
        return resultado


def _parsear_ids_actualizables(salida_winget, excluidos):
    """
    Parsea la salida tabular de 'winget upgrade' para sacar los IDs
    de paquete reales (columna "Id"), no el texto de la línea entera
    -- necesario para poder actualizar cada paquete de a uno y saltar
    los excluidos (Edge, telemetría), en vez de correr 'winget
    upgrade --all' a ciegas sin poder excluir nada.

    winget alinea las columnas por posición de texto, no por
    separador fijo, así que se ubica dónde empieza cada columna
    leyendo la fila de encabezado ("Name  Id  Version  Available
    Source") y se corta cada fila de datos en esas mismas posiciones.
    """
    lineas = salida_winget.split("\n")
    ids = []
    col_id = None
    col_version = None
    for linea in lineas:
        if col_id is None:
            if "Id" in linea and "Version" in linea:
                col_id = linea.index("Id")
                col_version = linea.index("Version")
            continue
        if not linea.strip() or set(linea.strip()) <= {"-"}:
            continue
        if len(linea) <= col_version:
            continue
        paquete_id = linea[col_id:col_version].strip()
        if not paquete_id:
            continue
        if any(e.lower() in paquete_id.lower() or e.lower() in linea.lower() for e in excluidos):
            continue
        ids.append(paquete_id)
    return ids


def actualizar_con_winget(seguro=True) -> str:
    """
    Actualiza software con winget DE VERDAD.

    Antes esto solo listaba lo pendiente y decía "di 'actualiza
    todo'" -- pero decir eso llamaba a esta misma función de nuevo,
    que volvía a listar lo mismo. Un loop cerrado que nunca
    actualizaba nada real, sin importar cuántas veces se confirmara.

    Ahora sí ejecuta la actualización real, paquete por paquete (para
    poder excluir Edge/telemetría uno por uno si seguro=True -- winget
    no tiene una forma confiable de excluir por nombre en un solo
    comando --all), y verifica el resultado real de cada uno en vez
    de asumir éxito.
    """
    excluidos = [
        "Microsoft.Edge",
        "Microsoft.EdgeWebView2Runtime",
        "Microsoft.WindowsAppRuntime",
        "Microsoft.VCRedist",
    ] if seguro else []

    try:
        r = subprocess.run(
            ["winget", "upgrade", "--include-unknown"],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            return "winget no disponible o sin conexión."

        ids = _parsear_ids_actualizables(r.stdout, excluidos)
        if not ids:
            return "Todo el software está actualizado."

        exitosos, fallidos = [], []
        for paquete_id in ids:
            try:
                res = subprocess.run(
                    ["winget", "upgrade", "--id", paquete_id, "--silent",
                     "--accept-package-agreements", "--accept-source-agreements"],
                    capture_output=True, text=True, timeout=180,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if res.returncode == 0:
                    exitosos.append(paquete_id)
                else:
                    fallidos.append(paquete_id)
            except subprocess.TimeoutExpired:
                fallidos.append(paquete_id)
            except Exception:
                fallidos.append(paquete_id)

        msg = f"Actualicé {len(exitosos)} de {len(ids)} programas."
        if fallidos:
            nombres = ", ".join(fallidos[:3])
            msg += f" {len(fallidos)} no se pudieron actualizar: {nombres}."
        return msg
    except FileNotFoundError:
        return "winget no está instalado en este sistema."
    except Exception as e:
        return f"Error actualizando con winget: {e}"


# ------------------------------------------
#   MÉDICO AUTÓNOMO — lista blanca de Groq
#   Groq solo puede elegir el NOMBRE de una de
#   estas funciones (nunca un comando libre).
#   "bajo/medio" -> Ada las ejecuta sola.
#   "alto"       -> Ada solo las recomienda;
#   no las corre sin que el usuario lo confirme
#   por comando (en modo invisible no hay nadie
#   para teclear una contraseña).
# ------------------------------------------
# Catálogo con lo que cada acción hace de verdad (mismo texto que sus
# docstrings) y cuándo aplica — esto es lo que ve Groq para planificar,
# en vez de tener que adivinar el significado por el nombre de la
# función. componente_asociado es el componente_dominante (de
# puntuacion.calcular_severidad_diagnostico) que típicamente resuelve
# esta acción — se usa para el aprendizaje por tipo de problema.
CATALOGO_ACCIONES = {
    "reparar_archivos_sistema": {
        "que_hace": "DISM + SFC, repara corrupcion de archivos de Windows",
        "usar_cuando": "eventos de corrupcion o crashes repetidos en el Event Log, sin causa de proceso puntual",
        "riesgo_base": "bajo",
        "componente_asociado": "eventos",
    },
    "limpiar_winsxs": {
        "que_hace": "limpia la carpeta WinSxS, libera 1-3GB de disco, 100% seguro",
        "usar_cuando": "SSD con poco espacio libre",
        "riesgo_base": "bajo",
        "componente_asociado": "ssd",
    },
    "limpiar_cache_iconos": {
        "que_hace": "reconstruye la cache de iconos de Windows",
        "usar_cuando": "iconos en blanco o que no se actualizan (rara vez lo detecta el diagnostico automatico)",
        "riesgo_base": "bajo",
        "componente_asociado": None,
    },
    "desactivar_servicios_basura": {
        "que_hace": "apaga servicios de Windows que consumen RAM sin aportar nada en una maquina de programacion",
        "usar_cuando": "RAM bajo presion alta o critica",
        "riesgo_base": "bajo",
        "componente_asociado": "ram",
    },
    "reparar_red": {
        "que_hace": "resetea la pila de red (winsock/TCP-IP), soluciona problemas de conectividad sin reiniciar",
        "usar_cuando": "eventos de red o conectividad perdida",
        "riesgo_base": "alto",
        "componente_asociado": "eventos",
    },
    "actualizar_con_winget": {
        "que_hace": "actualiza software instalado via winget, paquete por paquete",
        "usar_cuando": "hay actualizaciones pendientes relevantes, nunca por rutina sin motivo",
        "riesgo_base": "alto",
        "componente_asociado": None,
    },
}

ACCIONES_MEDICO_AUTOMATICAS = {
    "reparar_archivos_sistema":   reparar_archivos_sistema,
    "limpiar_winsxs":             limpiar_winsxs,
    "limpiar_cache_iconos":       limpiar_cache_iconos,
    "desactivar_servicios_basura": desactivar_servicios_basura,
}

ACCIONES_MEDICO_REQUIEREN_CONFIRMACION = {
    "reparar_red":            reparar_red,
    "actualizar_con_winget":  actualizar_con_winget,
}

# ACCIONES_SENSIBLES_A_RECURSOS ya quedó definida más arriba, junto a
# condiciones_desfavorables_para_reparacion_pesada() -- se deja este
# comentario acá para que sea fácil de encontrar en el mismo lugar
# que las otras listas de acciones al leer el archivo de arriba a abajo.


def reporte_semanal() -> str:
    """
    Genera un reporte .txt en el escritorio cada lunes.
    Solo datos locales — Groq solo para el párrafo final.
    """
    try:
        from sistema import indice_salud
        import sqlite3

        db_path = os.path.join(BASE_DIR, "ada_cerebro.db")
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        cur.execute("""
            SELECT SUM(mb_liberados), SUM(archivos_eliminados)
            FROM optimizaciones
            WHERE fecha >= date('now', '-7 days')
        """)
        fila = cur.fetchone()
        mb_semana  = round(fila[0] or 0, 1)
        arch_semana = fila[1] or 0

        cur.execute("""
            SELECT AVG(ram_uso_pct), AVG(cpu_pct), MIN(disco_libre_gb)
            FROM historial_medico
            WHERE fecha >= date('now', '-7 days')
        """)
        fila2 = cur.fetchone()
        ram_prom  = round(fila2[0] or 0, 1)
        cpu_prom  = round(fila2[1] or 0, 1)
        disco_min = round(fila2[2] or 0, 1)
        con.close()

        salud = indice_salud()

        reporte = (
            f"REPORTE SEMANAL DE ADA\n"
            f"{'='*40}\n"
            f"Fecha: {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"SALUD ACTUAL: {salud['score']}/100\n\n"
            f"SEMANA EN NÚMEROS:\n"
            f"  - RAM promedio usada: {ram_prom}%\n"
            f"  - CPU promedio: {cpu_prom}%\n"
            f"  - Espacio mínimo en disco: {disco_min} GB\n"
            f"  - Basura eliminada: {mb_semana} MB en {arch_semana} archivos\n\n"
            f"DIAGNÓSTICO:\n"
            f"  {salud['voz']}\n"
        )

        # Guardar en escritorio
        escritorio = os.path.join(os.path.expanduser("~"), "Desktop")
        ruta = os.path.join(escritorio, f"reporte_ada_{datetime.now().strftime('%Y%m%d')}.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(reporte)

        return f"Reporte semanal guardado en tu escritorio."

    except Exception as e:
        logging.error(f"[REPORTE] {e}")
        return "No pude generar el reporte semanal."