# ==========================================
#   sistema.py v3.3 - Sistema Inmune de Ada
#   + Cierra Edge automáticamente
#   + Pregunta por WhatsApp
#   + Lista software pesado con descripción
#   + RAM de Ada en tiempo real
#   + Heartbeat del scheduler (para watchdog_ada.py)
# ==========================================
import os
import gc
import time
import shutil
import logging
import threading
import subprocess
import psutil
from pathlib import Path
from datetime import datetime
from perfil_pc import PERFIL
from config import (RAM_META_LIBRE_GB, RAM_ALERTA_PCT, RAM_CRITICA_GB,
                     CPU_ALERTA_PCT, DISCO_ALERTA_LIBRE_GB, DISCO_CRITICO_LIBRE_GB,
                     INTERVALO_MONITOREO_SEG, INTERVALO_ANALISIS_SEG,
                     INTERVALO_MEDICO_IA_SEG,
                     CERRAR_EDGE_AUTOMATICO, PREGUNTAR_WHATSAPP,
                     MINUTOS_INACTIVIDAD_WHATSAPP)
from nucleo_procesos import listar_procesos

# Unidad de disco principal — toma la del sistema en vez de tenerla fija,
# así Ada no se rompe si algún día corre desde otra unidad.
DISCO_RAIZ = os.environ.get("SystemDrive", "C:") + "\\"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------
#   HEARTBEAT DEL SCHEDULER
#   No mide si el proceso de Ada sigue vivo (eso ya lo garantiza el
#   mutex de instancia única en app.py) sino si el hilo del
#   scheduler sigue AVANZANDO. Un proceso puede quedar vivo, con el
#   mutex tomado, mientras ese hilo está trabado en una sola llamada
#   sin timeout (una lectura de archivo, de registro, de WMI) --
#   nada en Python garantiza timeout para eso, a diferencia de los
#   subprocess.run(timeout=...) que Ada ya usa en otros lados.
#   watchdog_ada.py (corrido aparte, por su propia tarea programada
#   de Windows) compara la antigüedad de este archivo contra un
#   umbral y reinicia a Ada si hace falta -- Ada nunca se reinicia
#   a sí misma por esto, porque si el hilo está trabado, tampoco
#   podría ejecutar su propio reinicio.
# ------------------------------------------
LATIDO_PATH = os.path.join(BASE_DIR, "privado", "latido.txt")

def _escribir_latido(ahora: float):
    """
    Se llama una vez por vuelta del bucle del scheduler (~cada 1s).
    Defensivo a propósito: si falla la escritura (disco lleno,
    permisos, ruta movida), no debe tumbar el scheduler por esto --
    ese es justo el tipo de fallo que el heartbeat existe para que
    algo de AFUERA lo note, no para que Ada se rompa detectándolo
    ella misma.
    """
    try:
        os.makedirs(os.path.dirname(LATIDO_PATH), exist_ok=True)
        with open(LATIDO_PATH, "w", encoding="utf-8") as f:
            f.write(str(ahora))
    except Exception:
        pass

_hablar = None
_consulta_interna = None
_analizar_proceso = None
_obtener_inactividad = None  # función de voz.py

_estado = {
    "modo": "normal",
    "ultima_limpieza": None,
    "optimizaciones_hoy": 0,
    "whatsapp_preguntado": False,
    "edge_preguntado": False,
}

def configurar_monitor(funcion_hablar, fn_consulta_interna=None,
                        fn_analizar_proceso=None, fn_inactividad=None):
    global _hablar, _consulta_interna, _analizar_proceso, _obtener_inactividad
    _hablar = funcion_hablar
    _consulta_interna = fn_consulta_interna
    _analizar_proceso = fn_analizar_proceso
    _obtener_inactividad = fn_inactividad

# ------------------------------------------
#   LIMPIEZA
# ------------------------------------------
def _ruta_esta_protegida(ruta: str) -> bool:
    """
    Guardrail real: nunca tocar nada dentro de rutas_protegidas
    (Documents, Desktop, Program Files, etc.), sin importar qué
    le pidan a Ada. Antes esta lista existía pero no la usaba nadie.
    """
    try:
        ruta_norm = os.path.normcase(os.path.abspath(ruta))
        for protegida in PERFIL.get("rutas_protegidas", []):
            protegida_norm = os.path.normcase(os.path.abspath(os.path.expandvars(protegida)))
            if ruta_norm == protegida_norm or ruta_norm.startswith(protegida_norm + os.sep):
                return True
    except Exception:
        return True  # ante la duda, proteger
    return False

def limpiar_temporales():
    eliminados = 0
    bytes_liberados = 0
    rutas = [os.path.expandvars(r) for r in PERFIL["rutas_limpieza_segura"]]
    for ruta in rutas:
        if not ruta or not os.path.exists(ruta):
            continue
        if _ruta_esta_protegida(ruta):
            logging.warning(f"[GUARDRAIL] Ruta protegida, no se limpia: {ruta}")
            continue
        try:
            for item in Path(ruta).iterdir():
                try:
                    if item.is_file():
                        if time.time() - item.stat().st_mtime < 300:
                            continue
                        tam = item.stat().st_size
                        item.unlink()
                        eliminados += 1
                        bytes_liberados += tam
                    elif item.is_dir() and item.name not in ["Microsoft", "Windows", "System32"]:
                        tam = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                        shutil.rmtree(item, ignore_errors=True)
                        eliminados += 1
                        bytes_liberados += tam
                except (PermissionError, OSError):
                    continue
        except Exception:
            continue
    return eliminados, bytes_liberados

def optimizar_sistema(silencioso=False):
    from memoria import registrar_optimizacion
    ram_antes = psutil.virtual_memory()
    eliminados, bytes_lib = limpiar_temporales()

    try:
        subprocess.run(
            ["powershell", "-Command",
             "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass

    gc.collect()
    ram_despues = psutil.virtual_memory()
    disco = psutil.disk_usage(DISCO_RAIZ)
    mb_lib = bytes_lib / (1024**2)

    registrar_optimizacion(eliminados, mb_lib, ram_antes.percent, ram_despues.percent)
    _estado["ultima_limpieza"] = datetime.now().strftime("%H:%M")
    _estado["optimizaciones_hoy"] += 1

    if silencioso:
        return

    ram_libre_gb = round(ram_despues.available / (1024**3), 1)
    disco_gb = disco.free // (1024**3)
    return (
        f"Optimización completa. "
        f"Eliminé {eliminados} archivos, {mb_lib:.0f} megabytes de basura. "
        f"RAM libre: {ram_libre_gb} gigabytes. "
        f"Disco libre: {disco_gb} gigabytes."
    )

# ------------------------------------------
#   ESTADO Y DIAGNÓSTICO
# ------------------------------------------
def indice_salud() -> dict:
    """
    Ada calcula su propio índice de salud 0-100.
    Habla en primera persona como el PC vivo.
    """
    ram = psutil.virtual_memory()
    disco = psutil.disk_usage(DISCO_RAIZ)
    cpu = psutil.cpu_percent(interval=1)
    bat = psutil.sensors_battery()

    ram_libre_gb = ram.available / (1024**3)
    if ram_libre_gb >= 8:
        score_ram = 100
    elif ram_libre_gb >= 6:
        score_ram = 85
    elif ram_libre_gb >= 4:
        score_ram = 60
    elif ram_libre_gb >= 2:
        score_ram = 35
    else:
        score_ram = 10

    if cpu <= 20:
        score_cpu = 100
    elif cpu <= 40:
        score_cpu = 80
    elif cpu <= 60:
        score_cpu = 55
    elif cpu <= 80:
        score_cpu = 30
    else:
        score_cpu = 10

    disco_libre_gb = disco.free / (1024**3)
    if disco_libre_gb >= 50:
        score_disco = 100
    elif disco_libre_gb >= 30:
        score_disco = 80
    elif disco_libre_gb >= 15:
        score_disco = 55
    elif disco_libre_gb >= 8:
        score_disco = 25
    else:
        score_disco = 5

    score_bat = 100
    if bat:
        if bat.percent >= 50 or bat.power_plugged:
            score_bat = 100
        elif bat.percent >= 30:
            score_bat = 70
        elif bat.percent >= 20:
            score_bat = 40
        else:
            score_bat = 10

    score_final = int(
        score_ram * 0.35 +
        score_cpu * 0.25 +
        score_disco * 0.25 +
        score_bat * 0.15
    )

    if score_final >= 85:
        estado = "excelente"
        voz = f"Mi salud está en {score_final} de 100. Me siento en perfecto estado."
    elif score_final >= 70:
        estado = "bueno"
        voz = f"Mi salud está en {score_final} de 100. Estoy bien pero hay margen de mejora."
    elif score_final >= 50:
        estado = "regular"
        voz = f"Mi salud está en {score_final} de 100. Siento algo de presión en mis recursos."
    elif score_final >= 30:
        estado = "malo"
        voz = f"Mi salud bajó a {score_final} de 100. Necesito atención pronto."
    else:
        estado = "critico"
        voz = f"Alerta. Mi salud está en {score_final} de 100. Estoy en estado crítico."

    return {
        "score": score_final,
        "estado": estado,
        "voz": voz,
        "score_ram": score_ram,
        "score_cpu": score_cpu,
        "score_disco": score_disco,
        "score_bat": score_bat,
        "ram_libre_gb": round(ram_libre_gb, 1),
        "cpu_pct": round(cpu, 1),
        "disco_libre_gb": round(disco_libre_gb, 1),
    }

def estado_sistema():
    ram = psutil.virtual_memory()
    disco = psutil.disk_usage(DISCO_RAIZ)
    cpu = psutil.cpu_percent(interval=1)
    bat = psutil.sensors_battery()

    ram_libre_gb = round(ram.available / (1024**3), 1)
    disco_gb = disco.free // (1024**3)

    msg = (
        f"CPU al {cpu:.0f} por ciento. "
        f"RAM al {ram.percent:.0f} por ciento, {ram_libre_gb} gigabytes libres. "
        f"Disco C: {disco_gb} gigabytes libres."
    )
    if bat:
        estado = "cargando" if bat.power_plugged else "descargando"
        msg += f" Batería al {int(bat.percent)} por ciento, {estado}."

    if ram_libre_gb < RAM_META_LIBRE_GB:
        msg += " Atención: RAM justa para programar."
    if cpu > CPU_ALERTA_PCT:
        msg += " Atención: CPU muy alta."
    if disco_gb < DISCO_ALERTA_LIBRE_GB:
        msg += f" Atención: disco casi lleno."

    return msg

def temperatura_cpu():
    try:
        import wmi  # type: ignore
        w = wmi.WMI(namespace="root\\wmi")  # type: ignore
        temp = w.MSAcpi_ThermalZoneTemperature()[0].CurrentTemperature
        grados = (temp / 10) - 273.15
        if grados > 85:
            return f"Procesador muy caliente: {grados:.1f} grados. Descansa el equipo."
        elif grados > 65:
            return f"Procesador a {grados:.1f} grados. Temperatura moderada."
        return f"Procesador a {grados:.1f} grados. Temperatura saludable."
    except Exception as e:
        print(f"[TEMPERATURA] {type(e).__name__}: {e}")
        return "Temperatura no disponible en este equipo. Usa Lenovo Vantage para revisarla."

# ------------------------------------------
#   RAM DE ADA EN TIEMPO REAL
# ------------------------------------------
def ram_de_ada():
    """Cuánta RAM consume Ada misma en este momento"""
    try:
        proceso = psutil.Process(os.getpid())
        mb = proceso.memory_info().rss / (1024**2)
        pct = proceso.memory_percent()
        return (
            f"Yo misma estoy consumiendo {mb:.0f} megabytes de RAM, "
            f"que es el {pct:.1f} por ciento de tu memoria total. "
            f"Soy bastante liviana."
        )
    except Exception:
        return "No pude medir mi propio consumo de RAM."

def ram_vscode():
    """
    Cuánta RAM y CPU consume VS Code en total, y por qué.
    """
    try:
        procesos = [p for p in listar_procesos(['name', 'memory_info', 'cpu_percent'])
                    if (p.get('name') or '').lower() in ('code.exe', 'code - insiders.exe')]
        if not procesos:
            return "No detecté VS Code corriendo ahora mismo."

        total_mb = sum((p['memory_info'].rss / (1024**2)) for p in procesos
                       if p.get('memory_info'))
        total_cpu = sum((p.get('cpu_percent') or 0) for p in procesos)
        cantidad = len(procesos)

        return (
            f"VS Code está usando {total_mb:.0f} MB de RAM y {total_cpu:.1f}% de CPU "
            f"en total, repartidos en {cantidad} proceso(s) -- así arma Electron cada "
            f"ventana y el motor de extensiones (Extension Host, donde corren Pylance, "
            f"ESLint, Prettier, etc, todas juntas). No puedo desglosar cuánto usa cada "
            f"extensión por separado, ni de RAM ni de CPU, porque todas comparten ese "
            f"mismo proceso y no hay forma honesta de medirlo desde afuera. Si querés el "
            f"detalle por ventana y por extensión, el propio VS Code lo tiene: "
            f"Ctrl+Shift+P y buscá 'Developer: Open Process Explorer'."
        )
    except Exception as e:
        return f"No pude medir VS Code: {e}"

# ------------------------------------------
#   SOFTWARE PESADO DEL PC
# ------------------------------------------
_descripciones_software = {
    "chrome.exe": "Navegador web Google Chrome — muy popular pero consume mucha RAM.",
    "code.exe": "Visual Studio Code — editor de código de Microsoft, esencial para programar.",
    "msedge.exe": "Microsoft Edge — navegador de Windows, viene instalado por defecto, no lo usas.",
    "whatsapp.exe": "WhatsApp de escritorio — mensajería, lo manejas más en el celular.",
    "spotify.exe": "Spotify — reproductor de música en streaming, consume RAM en segundo plano.",
    "onedrive.exe": "OneDrive — sincronización de archivos con la nube de Microsoft.",
    "teams.exe": "Microsoft Teams — videoconferencias y chat empresarial.",
    "discord.exe": "Discord — chat de voz y texto, popular en comunidades de programación.",
    "slack.exe": "Slack — mensajería para equipos de trabajo.",
    "zoom.exe": "Zoom — videollamadas, solo consume RAM cuando está activo.",
    "postman.exe": "Postman — herramienta para probar APIs REST, útil para desarrollo.",
    "mongodcompass.exe": "MongoDB Compass — interfaz visual para bases de datos MongoDB.",
    "git.exe": "Git — control de versiones, esencial para programar.",
    "python.exe": "Python — intérprete del lenguaje, lo necesitas para Ada y tus proyectos.",
    "msmpeng.exe": "Windows Defender — antivirus de Windows, proceso crítico de seguridad.",
    "antimalware": "Windows Defender — protección antimalware, no lo cierres.",
    "svchost.exe": "Servicio del sistema Windows — proceso crítico, nunca cerrarlo.",
    "explorer.exe": "Explorador de Windows — gestiona el escritorio y las carpetas.",
    "searchindexer.exe": "Indexador de búsqueda de Windows — útil pero consume recursos.",
    "runtimebroker.exe": "Intermediario de aplicaciones de Windows Store — proceso del sistema.",
    "cortana.exe": "Cortana — asistente de Microsoft, puedes desactivarlo si no lo usas.",
    "yourphone.exe": "Tu Teléfono — sincronización de Android con Windows.",
    "gamebarft.exe": "Xbox Game Bar — grabación de pantalla, puedes desactivarlo.",
    "wslhost.exe": "Subsistema de Linux para Windows — útil si programas con Linux.",
    "node.exe": "Node.js — entorno de ejecución JavaScript, útil para desarrollo web.",
    "npm.exe": "NPM — gestor de paquetes de Node.js.",
}

def software_pesado_pc():
    """Lista el software más pesado con descripción de para qué sirve"""
    try:
        procs = {}
        for info in listar_procesos(['name', 'memory_info', 'memory_percent']):
            nombre_raw = info.get('name')
            mem_info = info.get('memory_info')
            if not nombre_raw or not mem_info:
                continue
            nombre = nombre_raw.lower()
            mb = mem_info.rss / (1024**2)
            if mb < 50:
                continue
            procs[nombre] = procs.get(nombre, 0) + mb

        ordenados = sorted(procs.items(), key=lambda x: x[1], reverse=True)[:8]
        if not ordenados:
            return "No encontré programas pesados activos ahora mismo."

        msg = "Los programas más pesados en tu PC ahora son:\n"
        for nombre, mb in ordenados:
            desc = ""
            for clave, descripcion in _descripciones_software.items():
                if clave in nombre:
                    desc = descripcion
                    break
            if not desc:
                desc = "Programa activo — consulta a Groq si quieres saber más."
            msg += f" {nombre}: {mb:.0f} MB — {desc}\n"
        return msg
    except Exception as e:
        return f"No pude listar el software: {e}"

# ------------------------------------------
#   EDGE AUTOMÁTICO — el scheduler llama esto
# ------------------------------------------
def _vigilar_edge_tick():
    """El scheduler llama esto cada 30 segundos"""
    if not CERRAR_EDGE_AUTOMATICO:
        return
    for info in listar_procesos(["name"]):
        nombre = info.get("name")
        if nombre and "msedge" in nombre.lower():
            print("🔒 Ada: Edge detectado — cerrando automaticamente.")
            import subprocess as _sp
            _sp.run(["taskkill", "/f", "/im", "msedge.exe"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if _hablar:
                _hablar("Cerre Edge automaticamente.", prioridad=1)
            return
    _estado["edge_preguntado"] = False

# ------------------------------------------
#   WHATSAPP — el scheduler llama esto
# ------------------------------------------
def _vigilar_whatsapp_tick():
    """El scheduler llama esto cada 60 segundos"""
    if not PREGUNTAR_WHATSAPP:
        return
    whatsapp_activo = any(
        'whatsapp' in (info.get('name') or '').lower()
        and 'root' not in (info.get('name') or '').lower()
        for info in listar_procesos(['name'])
    )
    if not whatsapp_activo:
        _estado["whatsapp_preguntado"] = False
        return

    if _obtener_inactividad:
        inactividad_min = _obtener_inactividad() / 60
        if (inactividad_min > MINUTOS_INACTIVIDAD_WHATSAPP
                and not _estado["whatsapp_preguntado"]):
            _estado["whatsapp_preguntado"] = True
            if _hablar:
                _hablar(
                    "WhatsApp lleva abierto sin que lo uses. "
                    "¿Quieres que lo cierre para liberar RAM?",
                    prioridad=1
                )

# ------------------------------------------
#   SISTEMA INMUNE — MONITOREO CONTINUO
# ------------------------------------------
def _pids_con_ventana_visible() -> set:
    """
    PIDs de todo proceso que tiene ahora mismo al menos una ventana
    visible en pantalla -- API nativa de Windows (user32 vía ctypes,
    sin librería nueva).
    """
    pids = set()
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

        def _callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pids.add(pid.value)
            return True

        user32.EnumWindows(EnumWindowsProc(_callback), 0)
    except Exception as e:
        logging.warning(f"[SISTEMA] No pude leer ventanas visibles, limpio sin esta barrera extra: {e}")
    return pids

def _limpiar_basura_autonomo() -> float:
    from puntuacion import calcular_score_proceso

    BASURA_AUTONOMA = [
        "msedge.exe", "gamebar.exe", "gamebarft.exe",
        "xboxgamingoverlay.exe", "widgets.exe",
        "cortana.exe", "bingweather.exe", "msedgewebview2.exe",
    ]

    mb_antes = psutil.virtual_memory().available / (1024**2)
    ventanas_visibles = _pids_con_ventana_visible()
    pid_propio = os.getpid()

    for info in listar_procesos(['pid', 'name', 'memory_percent']):
        try:
            pid = info.get('pid')
            nombre = info.get('name') or ""
            if pid == pid_propio:
                continue
            if any(b.lower() in nombre.lower() for b in BASURA_AUTONOMA):
                psutil.Process(pid).kill()
                continue
            if pid in ventanas_visibles:
                continue
            mem = info.get('memory_percent') or 0
            if mem > 3.0:
                resultado = calcular_score_proceso(nombre, mem, 0)
                if resultado["score"] < 20 and not resultado["critico"]:
                    psutil.Process(pid).kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue

    gc.collect()
    mb_despues = psutil.virtual_memory().available / (1024**2)
    return max(0, mb_despues - mb_antes)

def _procesar_solicitud_pendiente():
    """
    Si quedó una reparación pesada pendiente (pedida a mano por
    terminal cuando TiWorker o la RAM crítica lo impedían), la
    ejecuta sola en cuanto el momento sea bueno -- sin que el
    usuario tenga que volver a pedirla ni quedarse con la terminal
    abierta esperando. Corre en cualquier modo (invisible o
    terminal), porque este scheduler es el mismo en los dos.
    """
    import auto_reparador
    accion = auto_reparador.reparacion_pendiente()
    if not accion or accion not in auto_reparador.ACCIONES_SENSIBLES_A_RECURSOS:
        return

    motivo = auto_reparador.condiciones_desfavorables_para_reparacion_pesada()
    if motivo:
        return  # sigue mal momento -- se vuelve a revisar en 3 minutos

    auto_reparador.limpiar_reparacion_pendiente()
    try:
        resultado = auto_reparador.ACCIONES_MEDICO_AUTOMATICAS[accion]()
    except Exception as e:
        resultado = f"no pude terminarla: {e}"
    logging.info(f"[SISTEMA] Solicitud pendiente '{accion}' ejecutada sola. {resultado}")
    if _hablar:
        _hablar(f"Ya se liberó lo que estaba ocupado. Terminé lo que me pediste: {resultado}", prioridad=1)

def _evaluar_ram():
    from memoria import estado_salud_ssd
    ram = psutil.virtual_memory()
    ram_libre_gb = ram.available / (1024**3)

    alerta_ssd = estado_salud_ssd()
    if alerta_ssd and _hablar:
        _hablar(alerta_ssd, prioridad=0)

    if ram_libre_gb < RAM_CRITICA_GB:
        _estado["modo"] = "critico"
        _limpiar_basura_autonomo()
        optimizar_sistema(silencioso=True)
        nueva = round(psutil.virtual_memory().available / (1024**3), 1)
        if _hablar:
            _hablar(
                f"RAM crítica. Actué sola: liberé recursos. "
                f"Ahora tengo {nueva} gigabytes libres.",
                prioridad=0
            )
        return

    if ram.percent >= RAM_ALERTA_PCT:
        ahora = time.time()
        ultimo_aviso = _estado.get("ultimo_aviso_ram_pct", 0)
        if ahora - ultimo_aviso >= 3600 and _hablar:
            _hablar(
                f"Aviso: RAM al {ram.percent:.0f}%, por encima del {RAM_ALERTA_PCT}%. "
                f"Todavía no es crítico, pero está para vigilar.",
                prioridad=2
            )
            _estado["ultimo_aviso_ram_pct"] = ahora

    if ram_libre_gb < RAM_META_LIBRE_GB:
        _estado["modo"] = "alerta"
        _limpiar_basura_autonomo()
        nueva = round(psutil.virtual_memory().available / (1024**3), 1)
        if nueva >= RAM_META_LIBRE_GB:
            return
        if _hablar:
            _hablar(
                f"RAM al {ram.percent:.0f}%. Limpié lo que pude. "
                f"Tengo {nueva} gigabytes libres. Cierra programas si puedes.",
                prioridad=1
            )
        return

    _estado["modo"] = "normal"
    try:
        from memoria import registrar_historial_medico
        _disco = psutil.disk_usage(DISCO_RAIZ)
        _procs = len(psutil.pids())
        registrar_historial_medico(
            ram_libre_gb,
            ram.percent,
            psutil.cpu_percent(interval=0.5),
            _disco.free / (1024**3),
            _procs
        )
    except Exception:
        pass

_cpu_revision_en_curso = threading.Event()

def _evaluar_cpu():
    cpu1 = psutil.cpu_percent(interval=5)
    if cpu1 > CPU_ALERTA_PCT:
        time.sleep(25)
        cpu2 = psutil.cpu_percent(interval=5)
        if cpu2 > CPU_ALERTA_PCT and _hablar:
            procesos = listar_procesos(['name', 'cpu_percent'])
            top = max(procesos, key=lambda i: i.get('cpu_percent', 0) or 0, default=None)
            culpable = (top.get('name') if top else None) or "proceso desconocido"
            _hablar(
                f"CPU al {cpu2:.0f} por ciento sostenido. "
                f"{culpable} está trabajando mucho. ¿Quieres que lo revise?",
                prioridad=1
            )

def _evaluar_cpu_hilo():
    if _cpu_revision_en_curso.is_set():
        return
    _cpu_revision_en_curso.set()
    try:
        _evaluar_cpu()
    finally:
        _cpu_revision_en_curso.clear()

_medico_ia_en_curso = threading.Event()

def _medico_ia_hilo():
    if _medico_ia_en_curso.is_set():
        return
    _medico_ia_en_curso.set()
    try:
        import medico
        resultado = medico.autodiagnostico_y_reparacion()
        if resultado and _hablar:
            _hablar(resultado, prioridad=0)
    except Exception as e:
        logging.warning(f"[MÉDICO IA] {e}")
    finally:
        _medico_ia_en_curso.clear()

def _evaluar_disco():
    try:
        disco = psutil.disk_usage(DISCO_RAIZ)
        libre_gb = disco.free / (1024**3)
        if libre_gb < DISCO_CRITICO_LIBRE_GB and _hablar:
            _hablar(
                f"Disco casi lleno. Solo {libre_gb:.0f} gigabytes libres. Necesitas liberar espacio urgente.",
                prioridad=0
            )
        elif libre_gb < DISCO_ALERTA_LIBRE_GB and _hablar:
            _hablar(
                f"El disco tiene solo {libre_gb:.0f} gigabytes libres. Te recomiendo limpiar pronto.",
                prioridad=1
            )
    except Exception:
        pass

def _analisis_profundo_procesos():
    if not _analizar_proceso:
        return
    from config import MEMORIA_PROCESO_MIN_PCT_PARA_RASTREAR
    from memoria import (registrar_proceso_sospechoso, es_proceso_conocido_sospechoso,
                          registrar_muestra_proceso)

    sospechosos = []
    for info in listar_procesos(['pid', 'name', 'memory_percent', 'cpu_percent']):
        try:
            nombre = info.get('name') or ""
            mem = info.get('memory_percent') or 0
            cpu = info.get('cpu_percent') or 0
            if not nombre or (mem < 0.5 and cpu < 5):
                continue

            if mem >= MEMORIA_PROCESO_MIN_PCT_PARA_RASTREAR:
                try:
                    registrar_muestra_proceso(nombre, mem)
                except Exception:
                    pass

            if any(c in nombre.lower() for c in PERFIL["procesos_criticos"]):
                continue

            analisis = _analizar_proceso(nombre, mem, cpu)
            if analisis.get("amenaza") or analisis.get("tipo") in ["malware", "basura"]:
                registrar_proceso_sospechoso(nombre, mem, cpu)
                veces = es_proceso_conocido_sospechoso(nombre)
                if veces >= 2 and analisis.get("riesgo") in ["alto", "medio"]:
                    sospechosos.append(nombre)
        except Exception:
            continue

    if sospechosos and _hablar:
        import comandos
        primero = sospechosos[0]
        comandos._estado["esperando_confirmar_proceso"] = True
        comandos._estado["proceso_pendiente"] = primero
        nombres = ", ".join(set(sospechosos[:2]))
        _hablar(
            f"Sistema inmune: detecté actividad sospechosa en {nombres}. "
            f"¿Quieres que lo cierre?",
            prioridad=0
        )

def _scheduler():
    """Scheduler central — reemplaza todos los hilos de monitoreo"""
    _t: dict[str, float] = {
        "ram": 0.0,
        "cpu": 0.0,
        "edge": 0.0,
        "whatsapp": 0.0,
        "procesos": 0.0,
        "medico_ia": 0.0,
        "arranque": 0.0,
        "vigilante_tecnologico": 0.0,
    }
    while True:
        try:
            time.sleep(1)
            ahora = time.time()

            # Heartbeat: se escribe SIEMPRE, antes de cualquier chequeo,
            # una sola vez por vuelta. Si algo más abajo se traba, esta
            # línea deja de renovarse y watchdog_ada.py lo detecta desde
            # afuera -- ver comentario junto a _escribir_latido().
            _escribir_latido(ahora)

            if ahora - _t["ram"] >= INTERVALO_MONITOREO_SEG:
                _t["ram"] = ahora
                try:
                    _evaluar_ram()
                    _evaluar_disco()
                    _procesar_solicitud_pendiente()
                except Exception as e:
                    logging.warning(f"[SCHEDULER RAM] {e}")

            if ahora - _t["cpu"] >= 60:
                _t["cpu"] = ahora
                try:
                    threading.Thread(
                        target=_evaluar_cpu_hilo,
                        daemon=True
                    ).start()
                except Exception as e:
                    logging.warning(f"[SCHEDULER CPU] {e}")

            if ahora - _t["arranque"] >= 21600:
                _t["arranque"] = ahora
                try:
                    import monitor_arranque
                    resultado = monitor_arranque.verificar_arranque()
                    if resultado and _hablar:
                        _hablar(resultado, prioridad=0)
                except Exception as e:
                    logging.warning(f"[SCHEDULER ARRANQUE] {e}")

            if ahora - _t["vigilante_tecnologico"] >= 21600:
                _t["vigilante_tecnologico"] = ahora
                try:
                    import vigilante_tecnologico
                    resultado = vigilante_tecnologico.verificar_actualizacion_os()
                    if resultado and _hablar:
                        _hablar(resultado, prioridad=0)
                except Exception as e:
                    logging.warning(f"[SCHEDULER VIGILANTE TECNOLÓGICO] {e}")

            if ahora - _t["edge"] >= 1800:
                _t["edge"] = ahora
                try:
                    _vigilar_edge_tick()
                except Exception as e:
                    logging.warning(f"[SCHEDULER EDGE] {e}")

            if ahora - _t["whatsapp"] >= 60:
                _t["whatsapp"] = ahora
                try:
                    _vigilar_whatsapp_tick()
                except Exception as e:
                    logging.warning(f"[SCHEDULER WHATSAPP] {e}")

            if ahora - _t["procesos"] >= INTERVALO_ANALISIS_SEG:
                _t["procesos"] = ahora
                try:
                    threading.Thread(
                        target=_analisis_profundo_procesos,
                        daemon=True
                    ).start()
                except Exception as e:
                    logging.warning(f"[SCHEDULER PROCESOS] {e}")

            if ahora - _t["medico_ia"] >= INTERVALO_MEDICO_IA_SEG:
                _t["medico_ia"] = ahora
                try:
                    threading.Thread(
                        target=_medico_ia_hilo,
                        daemon=True
                    ).start()
                except Exception as e:
                    logging.warning(f"[SCHEDULER MEDICO IA] {e}")

        except Exception as e:
            logging.exception(f"[SCHEDULER ERROR] {type(e).__name__}: {e}")

def iniciar_monitoreo():
    import monitor_arranque
    monitor_arranque.inicializar()
    import vigilante_tecnologico
    vigilante_tecnologico.inicializar()
    threading.Thread(target=_scheduler, daemon=True).start()
    print("✅ Sistema inmune activo — scheduler central corriendo.")
