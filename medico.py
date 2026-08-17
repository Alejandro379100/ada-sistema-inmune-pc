# ==========================================
#   medico.py v1.0 - Médico Real de Ada
#   Ada lee sus propios síntomas profundos:
#   - Eventos ocultos de Windows
#   - Salud real del SSD con SMART
#   - Presión real de RAM
#   - Predicción de fallos
# ==========================================

import subprocess
import psutil
import json
import os
import logging
from datetime import datetime, timedelta
from config import DISCO_ALERTA_LIBRE_GB, DISCO_CRITICO_LIBRE_GB, \
                    NUCLEO_SATURADO_PCT, NUCLEO_DESBALANCE_PROMEDIO_MAX, CPU_ALERTA_PCT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------
#   NOTIFICACIÓN NATIVA DE WINDOWS
#   Aviso al usuario cuando el médico bloquea
#   o no puede completar una reparación sola
# ------------------------------------------

def _escapar_para_powershell(texto: str, largo_maximo: int = 200) -> str:
    """
    El texto que se manda a notificar (razón de Groq, nombre de
    acción) es texto libre, no controlado por el usuario -- antes de
    meterlo dentro de un string de PowerShell hay que escapar backtick,
    comillas dobles y '$' (interpolación de variables), o un texto con
    esos caracteres puede romper el script o, en el peor caso,
    inyectar código. También se recorta la longitud y se quitan saltos
    de línea, que igual no tienen sentido en una notificación corta.
    """
    if not texto:
        return ""
    texto = texto.replace("`", "``").replace('"', '`"').replace("$", "`$")
    texto = texto.replace("\n", " ").replace("\r", " ")
    return texto[:largo_maximo]

def notificar_windows(titulo: str, mensaje: str):
    """
    Aviso nativo de Windows -- sin instalar ningún paquete de Python
    nuevo. Se usa cuando el médico autónomo bloquea o no logra
    completar una reparación, para que el usuario se entere sin tener
    que revisar ada_log.txt a mano.

    Antes usaba un toast (Windows.UI.Notifications), pero esa técnica
    necesita que "Ada" esté registrada como app con un AUMID válido --
    sin eso, Windows lo descarta en silencio, sin mostrar nada y sin
    error. Un cuadro de diálogo (System.Windows.Forms.MessageBox) no
    tiene esa dependencia: siempre aparece, y se queda en pantalla
    hasta que el usuario lo cierra a mano -- justo lo que hace falta
    para no perderse un aviso importante del PC.

    Lanzado con Popen (no se espera a que termine) para que Ada NO se
    quede congelada mientras el cuadro sigue abierto esperando un
    clic -- el médico tiene que poder seguir revisando el resto del
    sistema aunque este aviso puntual siga sin cerrarse.

    Defensivo a propósito: si el aviso falla (PowerShell bloqueado
    por política, sesión sin escritorio, etc.) NO debe tumbar el
    ciclo del médico -- se registra en el log y Ada sigue funcionando
    igual, el aviso es un extra, no una dependencia crítica.
    """
    try:
        titulo_seguro = _escapar_para_powershell(titulo, largo_maximo=60)
        mensaje_seguro = _escapar_para_powershell(mensaje, largo_maximo=200)
        script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "{mensaje_seguro}", "{titulo_seguro}",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
        """
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        logging.warning(f"[MÉDICO] No pude mandar notificación de Windows: {e}")

# ------------------------------------------
#   EVENTOS OCULTOS DE WINDOWS
#   Ada lee errores que el usuario nunca ve
# ------------------------------------------

def leer_eventos_criticos(horas=24) -> list:
    """
    Lee eventos de error y advertencia de Windows
    de las últimas X horas.
    Retorna lista de eventos importantes.
    """
    try:
        script = f"""
        $eventos = Get-WinEvent -FilterHashtable @{{
            LogName   = 'System','Application'
            Level     = 1,2,3
            StartTime = (Get-Date).AddHours(-{horas})
        }} -MaxEvents 50 -ErrorAction SilentlyContinue

        $resultado = @()
        foreach ($e in $eventos) {{
            $resultado += @{{
                tiempo      = $e.TimeCreated.ToString('yyyy-MM-dd HH:mm')
                nivel       = [int]$e.Level
                nivel_texto = $e.LevelDisplayName
                fuente      = $e.ProviderName
                mensaje     = $e.Message.Substring(0, [Math]::Min(120, $e.Message.Length))
            }}
        }}
        $resultado | ConvertTo-Json -Compress
        """
        resultado = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if resultado.returncode != 0 or not resultado.stdout.strip():
            return []

        datos = json.loads(resultado.stdout.strip())
        if isinstance(datos, dict):
            datos = [datos]
        return datos if isinstance(datos, list) else []

    except Exception as e:
        print(f"[MÉDICO] Error leyendo eventos: {e}")
        return []

def resumir_eventos(eventos: list) -> str:
    """Ada habla de sus propios eventos en primera persona"""
    if not eventos:
        return "No encontré errores ocultos en mis registros recientes. Estoy limpia."

    # Clasificar por el NÚMERO de nivel de Windows (1=Crítico, 2=Error,
    # 3=Advertencia), no por el texto — el texto cambia según el idioma
    # de Windows ("Advertencia" vs "Warning"). Antes, si el sistema
    # alguna vez devolvía el nivel en inglés, Ada dejaba de contar
    # advertencias sin ningún error visible y reportaba "estoy limpia"
    # cuando no lo estaba.
    criticos     = [e for e in eventos if e.get("nivel") in (1, 2)]
    advertencias = [e for e in eventos if e.get("nivel") == 3]

    msg = ""
    if criticos:
        msg += f"Encontré {len(criticos)} errores en mis registros internos. "
        # Mencionar los más recientes, sin repetir la misma línea si dos
        # eventos comparten hora y fuente (System Restore, por ejemplo,
        # suele generar varios eventos relacionados en el mismo minuto).
        vistos = set()
        unicos = []
        for e in criticos:
            clave = (e.get("tiempo"), e.get("fuente"))
            if clave not in vistos:
                vistos.add(clave)
                unicos.append(e)
        for e in unicos[:2]:
            msg += f"A las {e.get('tiempo','?')}: {e.get('fuente','?')} reportó un problema. "

    if advertencias:
        msg += f"También hay {len(advertencias)} advertencias. "

    if not criticos and advertencias:
        msg += f"Solo advertencias menores — {len(advertencias)} en total. Nada crítico."

    return msg.strip()

def correlacionar_eventos(eventos: list) -> str:
    """
    Cruza cada evento del Event Log con el estado real del equipo en
    ese momento (RAM/CPU del historial médico ya corregido) y, si el
    evento acaba de pasar hace poco, con el proceso que más consumía
    justo entonces. No mide nada nuevo — solo cruza datos que Ada ya
    recolecta. Acumulado en el tiempo, esto permite detectar si un
    proceso se repite cerca de varios problemas: la diferencia entre
    reportar síntomas y señalar una causa probable.
    """
    if not eventos:
        return ""

    from memoria import registrar_contexto_evento, patron_procesos_conflictivos

    ahora = datetime.now()
    vistos = set()

    for e in eventos:
        clave = (e.get("tiempo"), e.get("fuente"))
        if clave in vistos:
            continue
        vistos.add(clave)

        proceso_culpable = None
        pct_culpable = None
        try:
            tiempo_evento = datetime.strptime(e.get("tiempo", ""), "%Y-%m-%d %H:%M")
            # Solo intentamos identificar al proceso culpable si el
            # evento pasó hace muy poco. Si ya pasaron horas, el
            # proceso que lo causó puede ni seguir corriendo, y
            # adivinar con lo que corre ahora sería inventar un
            # culpable falso en vez de dejarlo sin identificar.
            if (ahora - tiempo_evento) <= timedelta(minutes=15):
                from nucleo_procesos import listar_procesos
                procesos = listar_procesos(['name', 'memory_percent', 'cpu_percent'])
                top = max(
                    procesos,
                    key=lambda p: (p.get('memory_percent') or 0) + (p.get('cpu_percent') or 0),
                    default=None
                )
                if top:
                    proceso_culpable = top.get('name')
                    pct_culpable = round(top.get('memory_percent') or 0, 1)
        except (ValueError, TypeError):
            pass

        registrar_contexto_evento(e, proceso_culpable, pct_culpable)

    patrones = patron_procesos_conflictivos(minimo=3)
    if not patrones:
        return ""

    proceso, veces, pct_prom = patrones[0]
    return (
        f"Algo más: {proceso} ha estado presente cerca de {veces} de mis "
        f"eventos recientes, con un consumo promedio de {pct_prom:.1f} por ciento "
        f"de RAM. Podría ser la causa raíz — vale la pena revisarlo."
    )

# ------------------------------------------
#   SALUD REAL DEL SSD
#   Ada conoce su propio disco en profundidad
# ------------------------------------------

def salud_ssd_completa() -> dict:
    """
    Lee la salud real del SSD Intel NVMe.
    Combina SMART de Windows + espacio + tendencia.
    """
    resultado = {
        "estado":        "desconocido",
        "health_status": "desconocido",
        "libre_gb":      0,
        "total_gb":      0,
        "usado_pct":     0,
        "temperatura_c": None,
        "voz":           "",
        "alerta":        False,
    }

    try:
        # Estado SMART del disco
        script_smart = """
        $disk = Get-PhysicalDisk | Select-Object FriendlyName, HealthStatus, OperationalStatus
        $disk | ConvertTo-Json -Compress
        """
        r = subprocess.run(
            ["powershell", "-Command", script_smart],
            capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0 and r.stdout.strip():
            datos = json.loads(r.stdout.strip())
            if isinstance(datos, list):
                datos = datos[0]
            resultado["health_status"]    = datos.get("HealthStatus", "desconocido")
            resultado["operational_status"] = datos.get("OperationalStatus", "desconocido")

    except Exception as e:
        print(f"[MÉDICO SSD] Error SMART: {e}")

    try:
        # Espacio en disco
        disco = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        resultado["libre_gb"]  = round(disco.free  / (1024**3), 1)
        resultado["total_gb"]  = round(disco.total / (1024**3), 1)
        resultado["usado_pct"] = round(disco.percent, 1)

    except Exception as e:
        print(f"[MÉDICO SSD] Error espacio: {e}")

    # Determinar estado final
    health = resultado["health_status"]
    libre  = resultado["libre_gb"]

    if health == "Healthy" and libre >= DISCO_ALERTA_LIBRE_GB:
        resultado["estado"] = "saludable"
        resultado["voz"]    = (
            f"Mi SSD Intel está en perfecto estado. "
            f"Tengo {libre} gigabytes libres de {resultado['total_gb']}. "
            f"Salud SMART: óptima."
        )
    elif health == "Healthy" and libre >= DISCO_CRITICO_LIBRE_GB:
        resultado["estado"]  = "advertencia"
        resultado["alerta"]  = True
        resultado["voz"]     = (
            f"Mi SSD está funcionando bien pero me queda poco espacio: "
            f"{libre} gigabytes libres. Necesito que liberes espacio pronto."
        )
    elif health == "Healthy":
        resultado["estado"]  = "critico"
        resultado["alerta"]  = True
        resultado["voz"]     = (
            f"Disco casi lleno. Solo {libre} gigabytes libres. "
            f"No puedo trabajar bien así."
        )
    elif health == "desconocido":
        # Antes esto caía en la rama de "alerta crítica" de abajo —
        # un simple timeout de PowerShell (Get-PhysicalDisk puede
        # tardar más de 10s en algunos equipos) hacía que Ada dijera
        # "mi disco puede estar fallando, haz un backup ahora" cuando
        # en realidad solo no pudo consultarlo esta vez. "No sé" y
        # "está mal" son cosas muy distintas — ahora se distinguen.
        if libre < DISCO_CRITICO_LIBRE_GB:
            resultado["estado"] = "critico"
            resultado["alerta"] = True
            resultado["voz"]    = (
                f"Disco casi lleno: solo {libre} gigabytes libres. "
                f"Además no pude verificar el estado SMART esta vez."
            )
        else:
            resultado["estado"] = "desconocido"
            resultado["alerta"] = False
            resultado["voz"]    = (
                f"No pude verificar el estado SMART de mi disco esta vez "
                f"(el chequeo tardó demasiado). El espacio está bien: "
                f"{libre} gigabytes libres. Lo reviso de nuevo más tarde."
            )
    else:
        # Aquí sí llegó un HealthStatus real de Windows distinto de
        # "Healthy" (Warning, Unhealthy, etc.) — esta es la única
        # rama que debería sonar como alerta crítica de verdad.
        resultado["estado"]  = "critico"
        resultado["alerta"]  = True
        resultado["voz"]     = (
            f"Alerta crítica. Mi SSD reporta estado {health}. "
            f"Esto puede significar fallo inminente. Haz un backup ahora."
        )

    return resultado

# ------------------------------------------
#   PRESIÓN REAL DE RAM
#   Más profundo que solo el porcentaje
# ------------------------------------------

def presion_ram() -> dict:
    """
    Analiza la presión real de RAM —
    no solo el porcentaje sino si Windows
    está comprimiendo o usando pagefile.
    """
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()

    libre_gb   = round(ram.available / (1024**3), 1)
    total_gb   = round(ram.total     / (1024**3), 1)
    usado_pct  = round(ram.percent,  1)
    swap_gb    = round(swap.used     / (1024**3), 2)

    # Detectar MemCompression activo
    mem_compression = False
    try:
        for info in listar_procesos(['name']):
            nombre = info.get('name')
            if nombre and 'memcompression' in nombre.lower():
                mem_compression = True
                break
    except Exception:
        pass

    # Determinar presión real
    if libre_gb >= 6 and swap_gb < 0.5:
        estado = "saludable"
        voz    = f"Mi RAM está bien. Tengo {libre_gb} gigabytes libres y sin presión."
    elif libre_gb >= 4 and swap_gb < 1:
        estado = "moderada"
        voz    = (
            f"Siento algo de presión en mi memoria. "
            f"{libre_gb} gigabytes libres. "
            + ("Estoy comprimiendo datos para ahorrar espacio. " if mem_compression else "")
        )
    elif libre_gb >= 2:
        estado = "alta"
        voz    = (
            f"Mi RAM está bajo presión: solo {libre_gb} gigabytes libres. "
            f"{'Estoy comprimiendo activamente. ' if mem_compression else ''}"
            f"VS Code puede volverse lento."
        )
    else:
        estado = "critica"
        voz    = (
            f"RAM crítica. Solo {libre_gb} gigabytes libres. "
            f"Estoy usando {swap_gb} gigabytes de disco como RAM virtual. "
            f"Necesito que cierres programas ahora."
        )

    return {
        "estado":          estado,
        "libre_gb":        libre_gb,
        "total_gb":        total_gb,
        "usado_pct":       usado_pct,
        "swap_gb":         swap_gb,
        "mem_compression": mem_compression,
        "voz":             voz,
    }

# ------------------------------------------
#   PRESIÓN REAL DE CPU — NÚCLEO POR NÚCLEO
#   Un promedio general del 40% puede esconder
#   un núcleo al 100% mientras los demás están
#   en 10% — eso el promedio nunca lo muestra.
# ------------------------------------------

def presion_cpu_nucleos() -> dict:
    """
    Revisa el uso de CPU núcleo por núcleo, no solo el promedio
    general. Distingue dos situaciones muy distintas que el promedio
    mezcla en una sola cifra:

      - Desbalance: uno o pocos núcleos saturados mientras el
        promedio general se mantiene bajo -- la firma típica de un
        proceso de un solo hilo acaparando un núcleo (software mal
        optimizado, un bucle infinito, mala afinidad), NO carga real
        del sistema.
      - Saturación real: todos los núcleos trabajando parejo y alto
        -- eso sí es carga real, y ahí el remedio es distinto
        (cerrar procesos pesados, no revisar un solo culpable).

    OJO: usa psutil.cpu_percent(interval=1, percpu=True), que
    BLOQUEA 1 segundo real. Por diseño solo se llama desde
    diagnostico_completo() y autodiagnostico_y_reparacion() — ambas
    ya corren fuera del hilo del scheduler central, así que este
    segundo de espera no congela nada más (mismo principio que ya
    aplicamos al arreglar el bloqueo de _evaluar_cpu).
    """
    resultado = {
        "estado":            "desconocido",
        "nucleos_pct":       [],
        "nucleos_saturados": 0,
        "proceso_culpable":  None,
        "voz":               "",
        "alerta":            False,
    }
    try:
        nucleos = psutil.cpu_percent(interval=1, percpu=True)
        if not nucleos:
            resultado["voz"] = "No pude leer el uso por núcleo esta vez."
            return resultado

        resultado["nucleos_pct"] = nucleos
        total_nucleos = len(nucleos)
        saturados = [i for i, pct in enumerate(nucleos) if pct >= NUCLEO_SATURADO_PCT]
        resultado["nucleos_saturados"] = len(saturados)
        promedio_general = sum(nucleos) / total_nucleos

        if saturados and promedio_general < NUCLEO_DESBALANCE_PROMEDIO_MAX:
            # Desbalance real: algo acapara un núcleo mientras el
            # resto del sistema está tranquilo.
            culpable = None
            try:
                from nucleo_procesos import listar_procesos
                procesos = listar_procesos(["name", "cpu_percent"])
                top = max(procesos, key=lambda p: p.get("cpu_percent") or 0, default=None)
                culpable = top.get("name") if top else None
            except Exception:
                pass

            resultado["proceso_culpable"] = culpable
            resultado["estado"] = "desbalanceado"
            resultado["alerta"] = True
            nombre = culpable or "un proceso"
            resultado["voz"] = (
                f"Tengo {len(saturados)} de {total_nucleos} núcleos saturados mientras "
                f"el resto está tranquilo -- promedio general solo {promedio_general:.0f}%. "
                f"Esto suena a {nombre} acaparando un solo núcleo, no carga real del sistema."
            )
        elif promedio_general >= CPU_ALERTA_PCT:
            resultado["estado"] = "saturado"
            resultado["alerta"] = True
            resultado["voz"] = (
                f"Mis {total_nucleos} núcleos están trabajando parejo y fuerte -- "
                f"promedio {promedio_general:.0f}%. Esto sí es carga real del sistema."
            )
        else:
            resultado["estado"] = "saludable"
            resultado["voz"] = (
                f"Mis {total_nucleos} núcleos están balanceados y con espacio de sobra -- "
                f"promedio {promedio_general:.0f}%."
            )
    except Exception as e:
        print(f"[MÉDICO CPU] Error: {type(e).__name__}: {e}")
        resultado["voz"] = "No pude revisar los núcleos individualmente esta vez."

    return resultado

# ------------------------------------------
#   VERIFICACIÓN REAL POST-EJECUCIÓN
#   Antes Ada asumía que una reparación
#   funcionó por el texto que devolvía la
#   función. Ahora, para el problema que
#   motivó la PRIMERA acción del plan, puede
#   volver a medir el sensor real y saber de
#   verdad si sigue mal.
# ------------------------------------------

# Por cada componente verificable: nombre de la función que lo mide
# (como string, no la referencia directa -- así el lookup es dinámico
# vía globals() y respeta cualquier monkeypatch sobre estas funciones,
# igual que el resto del código de Ada), y qué "estado" cuenta como
# sano. Cualquier otro valor de "estado" cuenta como "el problema
# sigue ahí" -- EXCEPTO los estados ambiguos ("desconocido": el
# sensor no pudo leer esta vez), que se tratan como "no se pudo
# verificar", nunca como "sigue mal".
COMPONENTES_VERIFICABLES = {
    "ssd": ("salud_ssd_completa",  {"saludable"}, {"desconocido"}),
    "ram": ("presion_ram",         {"saludable"}, set()),
    "cpu": ("presion_cpu_nucleos", {"saludable"}, {"desconocido"}),
}

def _problema_sigue_presente(componente):
    """
    Vuelve a medir el sensor real del componente después de ejecutar
    una reparación, para saber si el problema que la motivó sigue
    presente -- en vez de asumirlo por el texto que devolvió la
    función de reparación.

    Solo sabe verificar ssd/ram/cpu: son los únicos con un sensor
    directo y rápido de re-consultar en el mismo ciclo. Para batería,
    drivers o eventos de Windows no hay una forma confiable de
    re-medir al instante, así que se trata igual que un componente
    desconocido: "no se pudo verificar".

    Retorna True (el problema sigue), False (se resolvió), o None
    (no se pudo verificar -- y ante la duda, NUNCA se encadena una
    alternativa a ciegas).
    """
    par = COMPONENTES_VERIFICABLES.get(componente)
    if not par:
        return None
    nombre_funcion, estados_ok, estados_ambiguos = par
    try:
        funcion = globals()[nombre_funcion]
        estado = funcion().get("estado")
    except Exception:
        return None
    if not estado or estado in estados_ambiguos:
        return None
    return estado not in estados_ok

def _intentar_alternativa(alternativa: dict, severidad: dict, componente: str, accion_principal: str,
                           trace_id: str = None) -> str:
    """
    Ejecuta el plan B de una acción cuya verificación mostró que el
    problema seguía presente. Más simple que el camino normal: como ya
    hay evidencia FRESCA y directa (se acaba de re-medir el sensor) de
    que el problema sigue ahí, no hace falta esperar la confirmación
    por persistencia entre ciclos -- esa regla existe para no
    reaccionar a un pico puntual, y acá ya se confirmó que no fue un
    pico puntual, es ahora mismo.

    Lo que SÍ se respeta igual, sin excepción:
      - Riesgo alto nunca se ejecuta sola -- se recomienda y queda
        pendiente de un humano, igual que en el camino normal.
      - Cooldown de 24h -- si el plan B ya se usó hoy, no se repite.
      - Tasa de éxito aprendida PARA ESTE COMPONENTE -- una
        alternativa con mal historial no se ejecuta solo porque el
        problema persista ahora.
    """
    from auto_reparador import (ACCIONES_MEDICO_AUTOMATICAS, ACCIONES_MEDICO_REQUIEREN_CONFIRMACION,
                                 ACCIONES_SENSIBLES_A_RECURSOS, condiciones_desfavorables_para_reparacion_pesada,
                                 guardar_ultimo_bloqueo)
    from memoria import (registrar_decision_medico_ia, accion_ejecutada_recientemente,
                          tasa_exito_reparacion_por_componente, fallos_consecutivos)
    from config import (REPARACION_MINIMO_INTENTOS_PARA_EVALUAR, REPARACION_UMBRAL_TASA_EXITO_MINIMA,
                         REPARACION_LIMITE_FALLOS_CONSECUTIVOS)
    from manual_playbook import texto_sugerido
    import telemetria

    accion = alternativa["accion"]
    riesgo = alternativa.get("riesgo", "medio")
    razon  = alternativa.get("razon", "")

    # CIRCUITO DE SEGURIDAD: mismo límite duro que la acción principal.
    # El plan B es, ni más ni menos, otra acción que Ada va a ejecutar
    # sola -- no tiene ningún motivo para estar exenta del límite.
    if accion in ACCIONES_MEDICO_AUTOMATICAS:
        consecutivos = fallos_consecutivos(accion, componente)
        if consecutivos >= REPARACION_LIMITE_FALLOS_CONSECUTIVOS:
            registrar_decision_medico_ia(
                accion, riesgo, razon, ejecutada=False,
                resultado=(f"CIRCUITO DE SEGURIDAD ACTIVADO (plan B): {consecutivos} fallos "
                           f"seguidos. Bloqueada hasta revisión humana."),
                severidad=severidad["categoria"], componente=componente,
            )
            telemetria.evento_circuito_seguridad(trace_id, accion, componente, consecutivos)
            guardar_ultimo_bloqueo(accion, componente)
            logging.error(f"[MÉDICO] CIRCUITO DE SEGURIDAD: plan B '{accion}' lleva "
                          f"{consecutivos} fallos seguidos para '{componente}' -- bloqueado.")
            comando = texto_sugerido(accion)
            notificar_windows("Ada — plan B bloqueado",
                              f"{accion} (plan B) lleva {consecutivos} fallos seguidos "
                              f"({componente}).{comando or ' Revisa el log.'}")
            return (f"verifiqué y el problema seguía, pero el plan B ({accion}) lleva "
                    f"{consecutivos} fallos seguidos -- no lo intento más sin que lo revises."
                    f"{comando}")

    if accion in ACCIONES_MEDICO_REQUIEREN_CONFIRMACION:
        registrar_decision_medico_ia(
            accion, riesgo, razon, ejecutada=False,
            resultado=f"Plan B tras verificar que '{accion_principal}' no resolvió, "
                      f"pero es riesgo alto -- pendiente de confirmación humana.",
            severidad=severidad["categoria"], componente=componente,
        )
        logging.info(f"[MÉDICO] Verifiqué y '{accion_principal}' no resolvió. Plan B "
                     f"'{accion}' es riesgo alto -- queda pendiente de confirmación.")
        return (f"verifiqué y el problema seguía. Como plan B propongo {accion} ({razon}), "
                f"pero es riesgo alto -- no la ejecuto sola. Dímelo por comando si querés."
                f"{texto_sugerido(accion)}")

    if accion not in ACCIONES_MEDICO_AUTOMATICAS:
        return ""  # no debería pasar (ya validado en ia.py), pero por seguridad no ejecuta nada

    if accion_ejecutada_recientemente(accion, horas=24):
        registrar_decision_medico_ia(
            accion, riesgo, razon, ejecutada=False,
            resultado="Plan B ya se ejecutó en las últimas 24h -- no se repite.",
            severidad=severidad["categoria"], componente=componente,
        )
        logging.info(f"[MÉDICO] Plan B '{accion}' en cooldown de 24h -- no se repite.")
        return ""

    if accion in ACCIONES_SENSIBLES_A_RECURSOS:
        motivo_mal_momento = condiciones_desfavorables_para_reparacion_pesada()
        if motivo_mal_momento:
            registrar_decision_medico_ia(
                accion, riesgo, razon, ejecutada=False,
                resultado=f"Plan B diferido, mal momento: {motivo_mal_momento}",
                severidad=severidad["categoria"], componente=componente,
            )
            logging.info(f"[MÉDICO] Plan B '{accion}' diferido -- {motivo_mal_momento}")
            return (f"verifiqué y el problema seguía, pero no es buen momento para {accion}: "
                    f"{motivo_mal_momento}")

    tasa = tasa_exito_reparacion_por_componente(accion, componente, ultimas=5)
    if (tasa["intentos"] >= REPARACION_MINIMO_INTENTOS_PARA_EVALUAR and
            tasa["porcentaje"] is not None and
            tasa["porcentaje"] < REPARACION_UMBRAL_TASA_EXITO_MINIMA):
        registrar_decision_medico_ia(
            accion, riesgo, razon, ejecutada=False,
            resultado=(f"Plan B no ejecutado: solo {tasa['exitos']}/{tasa['intentos']} "
                       f"éxitos para este componente."),
            severidad=severidad["categoria"], componente=componente,
        )
        logging.warning(f"[MÉDICO] Plan B '{accion}' bloqueado por mal historial en "
                        f"este componente: {tasa['exitos']}/{tasa['intentos']}.")
        notificar_windows("Ada — plan B bloqueado",
                          f"{accion} (plan B) bloqueado por mal historial "
                          f"({tasa['exitos']}/{tasa['intentos']}). Revisa el log.")
        return ""

    try:
        resultado_accion = ACCIONES_MEDICO_AUTOMATICAS[accion]()
    except Exception as e:
        resultado_accion = f"Error ejecutando {accion}: {e}"
    registrar_decision_medico_ia(accion, riesgo, razon, ejecutada=True,
                                  resultado=resultado_accion, severidad=severidad["categoria"],
                                  componente=componente)
    telemetria.evento_decision(trace_id, origen="plan_b", accion=accion, riesgo=riesgo,
                                razon=razon, ejecutada=True, resultado=resultado_accion,
                                componente=componente)
    logging.info(f"[MÉDICO] Verifiqué y '{accion_principal}' no resolvió. Ejecuté plan B "
                 f"'{accion}'. Resultado: {resultado_accion} [trace_id={trace_id}]")
    return f"verifiqué y el problema seguía -- probé {accion} como plan B. {resultado_accion}"

def predecir_fallos() -> list:
    """
    Ada analiza tendencias y predice problemas.
    Retorna lista de predicciones con solución.
    """
    predicciones = []

    try:
        from memoria import obtener_promedios_diarios

        # Misma fuente de verdad que memoria.diagnostico_tendencias() —
        # antes esta función tenía su propio SQL duplicado (y con el bug
        # de "1 sola muestra por día"), y encima importaba
        # diagnostico_tendencias sin usarla nunca. Ahora ambas beben del
        # mismo promedio diario real, así que nunca pueden contradecirse.
        filas = obtener_promedios_diarios(dias=7)

        if len(filas) >= 3:
            # filas viene del más reciente al más antiguo:
            # (fecha, ram_libre_prom, disco_libre_prom, cpu_prom, muestras)
            reciente_disco = filas[0][2]
            antiguo_disco  = filas[-1][2]
            dias           = len(filas)
            perdida_dia    = (antiguo_disco - reciente_disco) / dias

            if perdida_dia > 0.5:
                dias_restantes = int(reciente_disco / perdida_dia) if perdida_dia else 0
                predicciones.append({
                    "tipo":     "disco",
                    "urgencia": "alta" if dias_restantes < 10 else "media",
                    "voz": (
                        f"Estoy perdiendo {perdida_dia:.1f} gigabytes de disco por día. "
                        f"A este ritmo, en {dias_restantes} días no podré trabajar bien. "
                        f"Recomiendo limpiar descargas y temporales ahora."
                    ),
                    "solucion": "optimizar"
                })

            reciente_ram = filas[0][1]
            antiguo_ram  = filas[-1][1]
            perdida_ram  = (antiguo_ram - reciente_ram) / dias

            if perdida_ram > 0.3:
                predicciones.append({
                    "tipo":     "ram",
                    "urgencia": "alta",
                    "voz": (
                        f"Mi RAM libre ha bajado {perdida_ram:.1f} gigabytes por día esta semana. "
                        f"Probablemente instalaste software que arranca automáticamente. "
                        f"Recomiendo revisar los programas de inicio."
                    ),
                    "solucion": "revisar_inicio"
                })

            # Antes el predictor solo miraba disco y RAM — el dato de
            # CPU se guardaba en cada muestra pero nadie lo analizaba
            # para tendencias. Ahora también avisa si el uso promedio
            # de CPU viene subiendo con el tiempo, señal de que algo
            # nuevo se quedó corriendo de fondo (no un pico puntual).
            reciente_cpu = filas[0][3]
            antiguo_cpu  = filas[-1][3]
            subida_cpu   = reciente_cpu - antiguo_cpu

            if subida_cpu > 15:
                predicciones.append({
                    "tipo":     "cpu",
                    "urgencia": "media",
                    "voz": (
                        f"Mi uso promedio de CPU subió {subida_cpu:.0f} puntos esta semana, "
                        f"de {antiguo_cpu:.0f}% a {reciente_cpu:.0f}%. Algo nuevo se está "
                        f"quedando corriendo de fondo. Vale la pena revisar el arranque."
                    ),
                    "solucion": "revisar_inicio"
                })

    except Exception as e:
        print(f"[PREDICTOR] Error: {e}")

    # Memoria por proceso a largo plazo: a diferencia de todo lo de
    # arriba (que compara promedios diarios de RAM/CPU/disco en
    # general), esto mira proceso por proceso si alguno viene
    # subiendo de forma sostenida durante días — la fuga de memoria
    # real que un pico puntual no puede mostrar.
    try:
        from memoria import detectar_fugas_memoria
        for fuga in detectar_fugas_memoria(dias=14):
            predicciones.append({
                "tipo": "fuga_memoria",
                "urgencia": "alta" if fuga["memoria_actual_pct"] >= 15 else "media",
                "voz": fuga["voz"],
                "solucion": "revisar_proceso",
            })
    except Exception as e:
        print(f"[PREDICTOR FUGAS] Error: {e}")

    # Memoria de tendencias por tiempo: a diferencia de todo lo de
    # arriba (que mira SI algo está empeorando), esto mira CUÁNDO
    # aparecen los problemas -- si se concentran en un día de la
    # semana o una franja horaria específica, en vez de estar
    # distribuidos parejo. No dispara ninguna reparación por sí solo
    # (no hay una acción segura para "es martes a la tarde"), solo
    # informa -- pero es justo el tipo de reconocimiento de patrón
    # que un sistema inmune real hace y un catálogo fijo no.
    try:
        from memoria import detectar_patrones_temporales
        for patron in detectar_patrones_temporales(dias_atras=30):
            predicciones.append({
                "tipo": "patron_temporal",
                "urgencia": "media",
                "voz": patron["voz"],
                "solucion": "ninguna",
            })
    except Exception as e:
        print(f"[PREDICTOR PATRONES] Error: {e}")

    return predicciones

# ------------------------------------------
#   DIAGNÓSTICO COMPLETO
#   Ada se examina entera y habla en primera persona
# ------------------------------------------

def diagnostico_completo() -> str:
    """
    Ada hace un chequeo médico completo de sí misma.
    Habla en primera persona con soluciones reales.
    """
    from sistema import indice_salud
    from puntuacion import calcular_severidad_diagnostico

    salud    = indice_salud()
    ssd      = salud_ssd_completa()
    ram      = presion_ram()
    cpu      = presion_cpu_nucleos()
    eventos  = leer_eventos_criticos(horas=24)
    resumen_eventos = resumir_eventos(eventos)
    correlacion     = correlacionar_eventos(eventos)
    predicciones    = predecir_fallos()
    bateria, drivers = _leer_bateria_y_drivers()
    severidad       = calcular_severidad_diagnostico(ssd, ram, cpu, eventos, predicciones,
                                                      bateria=bateria, drivers=drivers)

    msg = f"Diagnóstico completo. {severidad['voz']} {salud['voz']} "
    msg += f"{ssd['voz']} "
    msg += f"{ram['voz']} "
    msg += f"{cpu['voz']} "
    msg += f"{resumen_eventos} "

    if bateria and bateria.get("voz"):
        msg += f"{bateria['voz']} "
    if drivers and drivers.get("voz"):
        msg += f"{drivers['voz']} "

    if correlacion:
        msg += f"{correlacion} "

    if predicciones:
        msg += "Predicciones: "
        for p in predicciones:
            msg += p["voz"] + " "

    return msg.strip()

# ------------------------------------------
#   MÉDICO AUTÓNOMO — Groq elige, Ada ejecuta
#   Groq nunca manda un comando libre, solo una
#   palabra de la lista blanca en auto_reparador.py.
# ------------------------------------------

def _leer_bateria_y_drivers():
    """
    Batería y drivers, mismo tratamiento que ya tiene CPU: se leen
    una vez por ciclo y entran a la severidad y al resumen que ve
    Groq. Ninguno de los dos dispara una reparación automática nueva
    (no hay ninguna en la lista blanca para esto) — solo informan.

    Respeta perfil_pc.PERFIL["bateria"]["tiene_bateria"] para no
    gastar tiempo leyendo batería en un equipo de escritorio.
    Si algo falla, no rompe el diagnóstico entero — simplemente
    Ada sigue sin ese dato, como ya hace con el resto de las lecturas.
    """
    from auto_reparador import diagnostico_bateria, diagnostico_drivers

    bateria = None
    try:
        from perfil_pc import PERFIL
        if PERFIL.get("bateria", {}).get("tiene_bateria", True):
            bateria = diagnostico_bateria()
    except Exception as e:
        print(f"[BATERÍA] Error: {e}")

    drivers = None
    try:
        drivers = diagnostico_drivers()
    except Exception as e:
        print(f"[DRIVERS] Error: {e}")

    return bateria, drivers


def autodiagnostico_y_reparacion() -> str:
    """
    El médico autónomo trabajando solo: arma un resumen factual del
    estado del equipo, le pregunta a Groq qué acción de la LISTA
    BLANCA de auto_reparador.py aplica, y según el riesgo:

      - riesgo bajo/medio -> Ada la ejecuta sola (son reparaciones
        que ya existen y ya están probadas).
      - riesgo alto -> Ada NO la ejecuta sola. Solo la recomienda y
        la deja anotada, porque en modo invisible no hay nadie
        despierto para confirmar con contraseña.

    Groq nunca manda un comando libre — solo elige una palabra de la
    lista blanca, y esa lista la controla el código, no el modelo.
    Cada decisión (se haya ejecutado o no) queda registrada para que
    puedas revisar el historial completo.
    """
    from ia import diagnosticar_y_recomendar
    from auto_reparador import (ACCIONES_MEDICO_AUTOMATICAS, ACCIONES_MEDICO_REQUIEREN_CONFIRMACION,
                                 guardar_ultimo_bloqueo)
    from memoria import (registrar_decision_medico_ia, accion_ejecutada_recientemente,
                          tasa_exito_reparacion, tasa_exito_reparacion_por_componente,
                          necesita_confirmacion_por_persistencia, decision_local_confiable,
                          fallos_consecutivos)
    from manual_playbook import texto_sugerido
    from puntuacion import calcular_severidad_diagnostico, listar_anomalias
    from config import (REPARACION_MINIMO_INTENTOS_PARA_EVALUAR, REPARACION_UMBRAL_TASA_EXITO_MINIMA,
                         REPARACION_LIMITE_FALLOS_CONSECUTIVOS)
    import telemetria

    ssd          = salud_ssd_completa()
    ram          = presion_ram()
    cpu          = presion_cpu_nucleos()
    eventos      = leer_eventos_criticos(horas=24)
    correlacion  = correlacionar_eventos(eventos)
    predicciones = predecir_fallos()
    bateria, drivers = _leer_bateria_y_drivers()

    # Severidad: calculada con reglas fijas, ANTES de preguntarle nada
    # a Groq. No es Groq quien decide qué tan grave es la situación —
    # eso necesita ser reproducible y auditable, no depender de un
    # LLM. Groq recibe este dato ya resuelto para razonar mejor su
    # elección dentro de la lista blanca.
    severidad = calcular_severidad_diagnostico(ssd, ram, cpu, eventos, predicciones,
                                                bateria=bateria, drivers=drivers)

    # A partir de acá, TODO este ciclo (decisión local, plan de Groq,
    # circuito de seguridad, verificación) comparte el mismo trace_id
    # en ada_telemetria.jsonl -- es lo que permite reconstruir un
    # ciclo completo después, filtrando por este único campo.
    trace_id = telemetria.nuevo_trace_id()
    metricas_antes = telemetria.snapshot_metricas(ssd=ssd, ram=ram, cpu=cpu)

    # El objetivo final del aprendizaje: que Ada deje de necesitar a
    # Groq para problemas que ya conoce bien. Si el componente que
    # domina esta severidad ya tiene una acción con suficiente
    # historial y una tasa de éxito muy alta en este equipo, Ada
    # decide sola acá mismo — no gasta la llamada a Groq.
    componente = severidad.get("componente_dominante")
    if componente and componente != "ninguno":
        local = decision_local_confiable(componente)
        if local and local["accion"] in ACCIONES_MEDICO_AUTOMATICAS:
            accion, riesgo, razon = local["accion"], local["riesgo"], local["razon"]

            # Red de seguridad redundante: decision_local_confiable ya
            # exige una tasa de éxito muy alta (90%+), así que en la
            # práctica esto casi nunca se dispara acá -- pero un
            # circuito de seguridad que dependa de "no debería pasar
            # nunca" no es un límite duro de verdad. Se revisa igual.
            consecutivos = fallos_consecutivos(accion, componente)
            if consecutivos >= REPARACION_LIMITE_FALLOS_CONSECUTIVOS:
                registrar_decision_medico_ia(
                    accion, riesgo, razon, ejecutada=False,
                    resultado=(f"CIRCUITO DE SEGURIDAD ACTIVADO (decisión local): "
                               f"{consecutivos} fallos seguidos. Bloqueada."),
                    severidad=severidad["categoria"], componente=componente,
                )
                telemetria.evento_circuito_seguridad(trace_id, accion, componente, consecutivos)
                guardar_ultimo_bloqueo(accion, componente)
                logging.error(f"[MÉDICO] CIRCUITO DE SEGURIDAD: '{accion}' (decisión local) "
                              f"lleva {consecutivos} fallos seguidos -- bloqueada.")
                comando = texto_sugerido(accion)
                notificar_windows("Ada — reparación bloqueada",
                                  f"{accion} (decisión local) lleva {consecutivos} fallos "
                                  f"seguidos ({componente}).{comando or ' Revisa el log.'}")
                return (f"Detuve {accion}: lleva {consecutivos} fallos seguidos para este "
                        f"problema, aunque mi tasa histórica decía que confiara en ella. "
                        f"Necesito que la revises antes de seguir."
                        f"{comando}")

            if accion_ejecutada_recientemente(accion, horas=24):
                registrar_decision_medico_ia(
                    accion, riesgo, razon, ejecutada=False,
                    resultado="Ya se ejecutó en las últimas 24h — no se repite sin necesidad",
                    severidad=severidad["categoria"], componente=componente,
                )
                logging.info(f"[MÉDICO] Decisión local para '{componente}' ({accion}) "
                             f"en cooldown de 24h — no se repite.")
                return ""
            try:
                resultado_accion = ACCIONES_MEDICO_AUTOMATICAS[accion]()
            except Exception as e:
                resultado_accion = f"Error ejecutando {accion}: {e}"
            registrar_decision_medico_ia(accion, riesgo, razon, ejecutada=True,
                                          resultado=resultado_accion, severidad=severidad["categoria"],
                                          componente=componente)
            telemetria.evento_decision(trace_id, origen="local", accion=accion, riesgo=riesgo,
                                        razon=razon, ejecutada=True, resultado=resultado_accion,
                                        componente=componente)
            logging.info(f"[MÉDICO] Decisión LOCAL (sin Groq): {local['razon']}. "
                         f"Ejecuté {accion}. {resultado_accion}")
            return f"Decidí sola sin Groq -- {local['razon']}. Ejecuté {accion}. {resultado_accion}"

    # Triage: SOLO lo que está mal, con números reales — nada de
    # "RAM: sin problemas" cuando RAM está perfecta. Menos ruido para
    # Groq, más señal.
    anomalias = listar_anomalias(ssd, ram, cpu, eventos, predicciones,
                                  bateria=bateria, drivers=drivers)
    if correlacion:
        anomalias.append(correlacion.strip())
    if predicciones:
        anomalias.extend(p["voz"] for p in predicciones)

    if not anomalias:
        return ""  # todo bien, no hay nada que decidir ni que preguntarle a Groq

    telemetria.evento_ciclo_iniciado(trace_id, severidad["categoria"], componente,
                                      len(anomalias), metricas_antes)

    logging.info(f"[MÉDICO] Ciclo de diagnóstico: severidad {severidad['categoria']} "
                 f"(componente dominante: {componente}). {len(anomalias)} anomalía(s) detectada(s). "
                 f"[trace_id={trace_id}]")
    resumen = f"{severidad['voz']} Problemas detectados: " + " | ".join(anomalias)

    # Historial estructurado por acción, con el estado de cooldown
    # pegado — esto reemplaza el párrafo suelto de antes. Se arma acá
    # y se le pasa a ia.py ya estructurado, no como texto libre.
    #
    # v2: la tasa que se muestra es POR COMPONENTE (este mismo tipo
    # de problema: ssd/ram/cpu/...), no global. Una acción puede tener
    # buen historial global pero haber fallado justo para este tipo
    # de problema (o viceversa) -- mezclarlo todo le escondía a Groq
    # la evidencia relevante. Si todavía no hay historial específico
    # para este componente, se usa la tasa global como respaldo (mejor
    # algo de contexto que nada), mostrando explícitamente cuál de las
    # dos es.
    historial_por_accion = {}
    for nombre_accion in ACCIONES_MEDICO_AUTOMATICAS:
        tasa_componente = tasa_exito_reparacion_por_componente(nombre_accion, componente, ultimas=5)
        if tasa_componente["intentos"] > 0:
            tasa = tasa_componente
            especifico = True
        else:
            tasa = tasa_exito_reparacion(nombre_accion, ultimas=5)
            especifico = False
        historial_por_accion[nombre_accion] = {
            "intentos": tasa["intentos"],
            "exitos": tasa["exitos"],
            "especifico_de_este_componente": especifico,
            "en_cooldown": accion_ejecutada_recientemente(nombre_accion, horas=24),
        }

    resultado = diagnosticar_y_recomendar(resumen, historial_por_accion=historial_por_accion,
                                           componente=componente)
    plan = resultado.get("plan", [])
    nivel_ia = resultado.get("nivel_ia", "desconocido")

    if nivel_ia != "groq_70b":
        # Cualquier cosa distinta al camino normal queda anotada en
        # el log real y en la telemetría -- si Ada terminó actuando
        # con el modelo rápido o sin ningún modelo, eso tiene que ser
        # visible, no un detalle escondido dentro de ia.py.
        logging.warning(f"[MÉDICO] Nivel de IA usado este ciclo: {nivel_ia} "
                        f"(no fue el camino normal Groq 70B). [trace_id={trace_id}]")
    telemetria.evento_decision(trace_id, origen="nivel_ia", accion="(meta)", riesgo="",
                                razon=resultado.get("razonamiento", ""), ejecutada=False,
                                resultado=nivel_ia, componente=componente)

    if not plan:
        logging.info("[MÉDICO] Groq no recomendó ninguna acción para las anomalías detectadas.")
        return ""

    logging.info(f"[MÉDICO] Groq propuso un plan de {len(plan)} acción(es): "
                 + ", ".join(f"{p['accion']} ({p['riesgo']})" for p in plan))

    mensajes = []
    for i, item in enumerate(plan):
        mensaje = _procesar_accion_medico(item, severidad, componente, verificar=(i == 0),
                                           historial_por_accion=historial_por_accion,
                                           trace_id=trace_id, metricas_antes=metricas_antes)
        if mensaje:
            mensajes.append(mensaje)

    telemetria.evento_ciclo_cerrado(trace_id, len(mensajes))
    return " || ".join(mensajes)


def _procesar_accion_medico(item: dict, severidad: dict, componente: str, verificar: bool = False,
                             historial_por_accion: dict = None, trace_id: str = None,
                             metricas_antes: dict = None) -> str:
    """
    Aplica a UNA acción del plan las mismas reglas de seguridad que
    antes se aplicaban a la única acción que devolvía Groq: cooldown
    de 24h, tasa de éxito aprendida, confirmación por persistencia
    para riesgo medio, y riesgo alto siempre pendiente de un humano.
    Se llama una vez por cada entrada del plan (máximo 2), en orden —
    así que si la primera acción falla o queda bloqueada, la segunda
    igual se evalúa por su cuenta, no se cancela en cadena.

    verificar=True (solo para la primera acción del plan, la única
    con componente_dominante conocido): después de ejecutar con
    éxito, vuelve a medir el sensor real del componente. Si el
    problema sigue presente y esta acción trajo una 'alternativa'
    (plan B), la intenta -- en vez de asumir, como antes, que
    ejecutar la acción alcanzó.

    historial_por_accion: el mismo diccionario que ya se le pasó a
    Groq para decidir. Se usa acá para que el mensaje final cite la
    evidencia real que Ada tiene (intentos/éxitos), no solo la razón
    corta que escribió Groq -- "por qué elegí esto" con números
    propios, no solo la palabra de Groq.
    """
    from auto_reparador import (ACCIONES_MEDICO_AUTOMATICAS, ACCIONES_MEDICO_REQUIEREN_CONFIRMACION,
                                 ACCIONES_SENSIBLES_A_RECURSOS, condiciones_desfavorables_para_reparacion_pesada,
                                 guardar_ultimo_bloqueo)
    from memoria import (registrar_decision_medico_ia, accion_ejecutada_recientemente,
                          tasa_exito_reparacion, necesita_confirmacion_por_persistencia,
                          fallos_consecutivos)
    from config import (REPARACION_MINIMO_INTENTOS_PARA_EVALUAR, REPARACION_UMBRAL_TASA_EXITO_MINIMA,
                         REPARACION_LIMITE_FALLOS_CONSECUTIVOS)
    from manual_playbook import texto_sugerido
    import telemetria

    accion = item["accion"]
    riesgo = item.get("riesgo", "medio")
    razon  = item.get("razon", "")

    if accion in ACCIONES_MEDICO_AUTOMATICAS:
        # CIRCUITO DE SEGURIDAD contra bucles infinitos -- se revisa
        # ANTES que cualquier otra cosa, incluso antes del cooldown.
        # A diferencia de la tasa de éxito (que necesita una muestra
        # grande para opinar), esto corta de inmediato apenas se
        # acumulan N fallos SEGUIDOS para este componente, sin
        # importar cuántos intentos totales haya en la historia. Es
        # el límite duro que evita que Ada quede atrapada intentando
        # arreglar su propio error sin ningún tope.
        consecutivos = fallos_consecutivos(accion, componente)
        if consecutivos >= REPARACION_LIMITE_FALLOS_CONSECUTIVOS:
            registrar_decision_medico_ia(
                accion, riesgo, razon, ejecutada=False,
                resultado=(f"CIRCUITO DE SEGURIDAD ACTIVADO: {consecutivos} fallos seguidos. "
                           f"Bloqueada hasta revisión humana."),
                severidad=severidad["categoria"], componente=componente,
            )
            telemetria.evento_circuito_seguridad(trace_id, accion, componente, consecutivos)
            guardar_ultimo_bloqueo(accion, componente)
            logging.error(f"[MÉDICO] CIRCUITO DE SEGURIDAD: '{accion}' lleva {consecutivos} "
                          f"fallos seguidos para '{componente}' -- bloqueada, no se reintenta sola.")
            comando = texto_sugerido(accion)
            notificar_windows("Ada — reparación bloqueada",
                              f"{accion} lleva {consecutivos} fallos seguidos ({componente})."
                              f"{comando or ' Revisa el log.'}")
            return (
                f"Detuve {accion}: lleva {consecutivos} fallos seguidos para este problema. "
                f"No la vuelvo a intentar sola -- necesito que la revises vos antes de seguir."
                f"{comando}"
            )

        # Antes esto se ejecutaba en CADA ciclo (cada 3 horas) mientras
        # el mismo evento viejo siguiera dentro de la ventana de 24h
        # del Event Log — así que Ada terminaba corriendo DISM/SFC
        # completo una y otra vez para el mismo problema ya resuelto.
        # Ahora, si ya ejecutó esta misma acción en las últimas 24h,
        # no la repite: la anota como "ya hecha" y no vuelve a gastar
        # los minutos de DISM/SFC (o la reparación que sea) sin
        # ninguna necesidad real.
        if accion_ejecutada_recientemente(accion, horas=24):
            registrar_decision_medico_ia(
                accion, riesgo, razon, ejecutada=False,
                resultado="Ya se ejecutó en las últimas 24h — no se repite sin necesidad",
                severidad=severidad["categoria"], componente=componente,
            )
            logging.info(f"[MÉDICO] '{accion}' ya se ejecutó en las últimas 24h — no se repite.")
            return ""

        # MOMENTO DESFAVORABLE (SFC/DISM): diagnosticado con log real
        # que los fallos de 'reparar_archivos_sistema' no eran
        # corrupción, eran RAM crítica o TiWorker.exe compitiendo por
        # el mismo almacén WinSxS -- ver el comentario junto a
        # ACCIONES_SENSIBLES_A_RECURSOS en auto_reparador.py. Se
        # chequea ANTES de intentar, así un mal momento no gasta una
        # de las 3 vidas del circuito de seguridad por una razón que
        # no tiene nada que ver con corrupción de archivos real.
        if accion in ACCIONES_SENSIBLES_A_RECURSOS:
            motivo_mal_momento = condiciones_desfavorables_para_reparacion_pesada()
            if motivo_mal_momento:
                registrar_decision_medico_ia(
                    accion, riesgo, razon, ejecutada=False,
                    resultado=f"Diferida, mal momento: {motivo_mal_momento}",
                    severidad=severidad["categoria"], componente=componente,
                )
                logging.info(f"[MÉDICO] '{accion}' diferida -- {motivo_mal_momento}")
                return (
                    f"Groq recomienda {accion} ({razon}), pero no es buen momento: "
                    f"{motivo_mal_momento} La reintento sola en el próximo ciclo."
                )

        # Red de seguridad de aprendizaje: si esta acción ya se probó
        # suficientes veces y le fue mal la mayoría, no se repite sola
        # aunque Groq y la lista blanca digan riesgo bajo/medio —
        # se baja a "solo recomendar" hasta que un humano la revise.
        tasa = tasa_exito_reparacion(accion, ultimas=5)
        if (tasa["intentos"] >= REPARACION_MINIMO_INTENTOS_PARA_EVALUAR and
                tasa["porcentaje"] is not None and
                tasa["porcentaje"] < REPARACION_UMBRAL_TASA_EXITO_MINIMA):
            registrar_decision_medico_ia(
                accion, riesgo, razon, ejecutada=False,
                resultado=(f"No se ejecutó sola: solo {tasa['exitos']}/{tasa['intentos']} "
                           f"éxitos recientes, por debajo del umbral de confianza."),
                severidad=severidad["categoria"], componente=componente,
            )
            logging.warning(f"[MÉDICO] '{accion}' bloqueada por mal historial: "
                            f"{tasa['exitos']}/{tasa['intentos']} éxitos recientes.")
            comando = texto_sugerido(accion)
            notificar_windows("Ada — reparación bloqueada",
                              f"{accion} bloqueada por mal historial "
                              f"({tasa['exitos']}/{tasa['intentos']} éxitos)."
                              f"{comando or ' Revisa el log.'}")
            return (
                f"Groq recomienda {accion} ({razon}), pero esta reparación solo tuvo "
                f"{tasa['exitos']} de {tasa['intentos']} éxitos las últimas veces en tu equipo — "
                f"no la ejecuto sola. Dímelo por comando si querés que la intente de todas formas."
                f"{comando}"
            )

        # Nivel de confirmación intermedio: riesgo "bajo" se ejecuta
        # de inmediato (como siempre), pero riesgo "medio" necesita
        # verse confirmado en dos ciclos seguidos antes de ejecutarse
        # sola — así un pico puntual no dispara una reparación real
        # a la primera lectura.
        if riesgo == "medio" and not necesita_confirmacion_por_persistencia(accion, horas=48):
            registrar_decision_medico_ia(
                accion, riesgo, razon, ejecutada=False,
                resultado=("Pendiente confirmación por persistencia — si el problema sigue "
                           "en el próximo diagnóstico, la ejecuto sola."),
                severidad=severidad["categoria"], componente=componente,
            )
            logging.info(f"[MÉDICO] '{accion}' riesgo medio, primera vez — esperando "
                         f"confirmación por persistencia antes de ejecutar.")
            return (
                f"Groq recomienda {accion} ({razon}), riesgo medio. Todavía no la ejecuto — "
                f"si el problema sigue en el próximo diagnóstico, la confirmo y la hago sola."
            )

        try:
            resultado_accion = ACCIONES_MEDICO_AUTOMATICAS[accion]()
        except Exception as e:
            resultado_accion = f"Error ejecutando {accion}: {e}"
        registrar_decision_medico_ia(accion, riesgo, razon, ejecutada=True,
                                      resultado=resultado_accion, severidad=severidad["categoria"],
                                      componente=componente)
        telemetria.evento_decision(trace_id, origen="groq", accion=accion, riesgo=riesgo,
                                    razon=razon, ejecutada=True, resultado=resultado_accion,
                                    componente=componente)
        logging.info(f"[MÉDICO] Ejecuté '{accion}' sola (riesgo {riesgo}). Resultado: {resultado_accion} "
                     f"[trace_id={trace_id}]")
        mensaje = f"Groq recomendó {razon}. Ejecuté {accion} sola (riesgo {riesgo}). {resultado_accion}"

        # Evidencia real de Ada, no solo la palabra de Groq: si ya
        # hay historial (propio o global) para esta acción, se cita
        # con números -- "por qué elegí esto" respaldado en datos,
        # no una afirmación sin sustento.
        h = (historial_por_accion or {}).get(accion)
        if h and h.get("intentos", 0) > 0:
            tipo = "para este mismo tipo de problema" if h.get("especifico_de_este_componente") else "en general"
            mensaje += f" (mi historial {tipo}: {h['exitos']}/{h['intentos']} éxitos)."

        # Verificación real: solo se intenta para la primera acción
        # del plan (la única con componente_dominante conocido), y
        # solo si trajo una alternativa para este caso.
        alternativa = item.get("alternativa") if verificar else None
        if alternativa:
            import fsm_medico

            sigue_mal = _problema_sigue_presente(componente)

            # Snapshot DESPUÉS solo para el componente verificado -- es
            # el mismo sensor que ya se acaba de re-consultar arriba
            # (ssd/ram/cpu), así que reusarlo acá no cuesta una medición
            # extra. Esto es lo que permite comparar de verdad el vector
            # ANTES vs DESPUÉS, no solo asumir por el texto.
            metricas_despues = {}
            try:
                if componente == "ssd":
                    metricas_despues = telemetria.snapshot_metricas(ssd=salud_ssd_completa())
                elif componente == "ram":
                    metricas_despues = telemetria.snapshot_metricas(ram=presion_ram())
                elif componente == "cpu":
                    metricas_despues = telemetria.snapshot_metricas(cpu=presion_cpu_nucleos())
            except Exception:
                metricas_despues = {}

            decision_fsm = fsm_medico.decidir_tras_verificacion(
                trace_id, accion, componente, sigue_mal, metricas_antes, metricas_despues
            )
            estado = decision_fsm["estado"]

            if estado == fsm_medico.Estado.ROLLBACK:
                # Empeoró Y hay una reversión puntual segura conocida
                # para esta acción -- la FSM la ejecuta sola. Nunca
                # dispara una restauración completa del sistema.
                mensaje += " " + fsm_medico.ejecutar_rollback(
                    trace_id, accion, componente,
                    decision_fsm["accion_reversion"], severidad["categoria"]
                )
            elif estado == fsm_medico.Estado.CIRCUIT_BROKEN:
                # Empeoró y NO hay reversión puntual segura conocida --
                # se bloquea, se avisa del punto de restauración
                # disponible, y Ada nunca reinicia el equipo sola.
                mensaje += " " + fsm_medico.circuito_roto_sin_rollback(
                    trace_id, accion, componente, severidad["categoria"]
                )
            elif estado == fsm_medico.Estado.RESUELTO:
                logging.info(f"[MÉDICO] Verifiqué '{accion}' -- el problema en '{componente}' "
                             f"ya se resolvió. [trace_id={trace_id}]")
                mensaje += " Verifiqué después: el problema ya se resolvió."
            else:  # SIGUE_IGUAL -- sigue mal, pero no empeoró (o no se pudo verificar)
                logging.info(f"[MÉDICO] Verifiqué '{accion}' -- el problema en '{componente}' "
                             f"sigue presente (sin empeorar). Evaluando plan B. [trace_id={trace_id}]")
                mensaje_alt = _intentar_alternativa(alternativa, severidad, componente,
                                                     accion_principal=accion, trace_id=trace_id)
                if mensaje_alt:
                    mensaje += f" Además, {mensaje_alt}"
                else:
                    mensaje += (" Verifiqué después: el problema seguía, pero el plan B "
                                "quedó bloqueado (cooldown o mal historial) — no lo ejecuté.")

        return mensaje

    if accion in ACCIONES_MEDICO_REQUIEREN_CONFIRMACION:
        registrar_decision_medico_ia(accion, riesgo, razon, ejecutada=False,
                                       resultado="Pendiente de confirmación del usuario",
                                       severidad=severidad["categoria"], componente=componente)
        logging.info(f"[MÉDICO] '{accion}' es riesgo alto — queda pendiente de confirmación humana.")
        return (
            f"Groq recomienda {accion} ({razon}), pero es de riesgo alto — "
            f"no la ejecuto sola. Dímelo por comando cuando quieras que la haga."
            f"{texto_sugerido(accion)}"
        )

    # Groq devolvió algo fuera de las dos listas — no debería pasar
    # nunca porque diagnosticar_y_recomendar() ya filtra esto, pero
    # por seguridad no se ejecuta nada de todas formas.
    logging.warning(f"[MÉDICO] Groq recomendó '{accion}', fuera de ambas listas blancas — ignorado.")
    return ""