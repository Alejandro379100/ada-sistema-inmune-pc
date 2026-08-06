# ==========================================
#   memoria.py v3.1 - Memoria Real de Ada
#   SQLite para cosas que la hacen inteligente
#   Solo guarda lo extremadamente importante
#   Todo lo temporal se borra al arrancar
# ==========================================

import os
import sqlite3
import json
import time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "ada_cerebro.db")

# RAM — se borra al cerrar Ada
_sesion = {
    "inicio": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "ordenes_dadas": 0,
    "ultima_orden": "",
    "contexto_reciente": [],
    "alertas_emitidas": 0,
    "optimizaciones_sesion": 0
}

# ------------------------------------------
#   INICIALIZAR BASE DE DATOS
#   Solo 4 tablas — nada más
# ------------------------------------------

def inicializar_db():
    """Crea las tablas si no existen y limpia lo temporal al arrancar"""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # 1. Procesos sospechosos — sistema inmune
    cur.execute("""
        CREATE TABLE IF NOT EXISTS procesos_sospechosos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            veces_visto INTEGER DEFAULT 1,
            ram_promedio REAL,
            cpu_promedio REAL,
            primera_vez TEXT,
            ultima_vez TEXT
        )
    """)

    # 2. Historial de optimizaciones — Ada aprende cuándo vale la pena
    cur.execute("""
        CREATE TABLE IF NOT EXISTS optimizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            archivos_eliminados INTEGER,
            mb_liberados REAL,
            ram_antes_pct REAL,
            ram_despues_pct REAL
        )
    """)

    # 3. Caché de Groq — respuestas frecuentes para no gastar API
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cache_groq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pregunta_clave TEXT UNIQUE,
            respuesta TEXT,
            veces_usada INTEGER DEFAULT 1,
            fecha TEXT
        )
    """)

    # 4. Historial médico — UNA fila por cada lectura real, no una por
    #    día. Antes "fecha" era UNIQUE y con INSERT OR IGNORE, así que
    #    solo la primera lectura del día quedaba guardada y el resto se
    #    descartaba en silencio (bug real, resuelto aquí). Ahora
    #    "fecha_hora" es la marca de tiempo única de cada muestra y
    #    "fecha" (solo el día) se usa para agrupar y promediar.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS historial_medico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT,
            fecha TEXT,
            ram_libre_gb REAL,
            ram_uso_pct REAL,
            cpu_pct REAL,
            disco_libre_gb REAL,
            procesos_activos INTEGER
        )
    """)
    con.commit()
    _migrar_historial_medico(cur, con)

    # Índice ÚNICO sobre fecha_hora: reemplaza el UNIQUE que antes iba
    # en la definición de la columna (que no sirve de nada si la tabla
    # ya existía de una instalación anterior — CREATE TABLE IF NOT
    # EXISTS no la toca). Este índice sí se crea siempre, exista o no
    # la tabla de antes, y de paso hace instantánea la búsqueda de "la
    # muestra más cercana a este momento" sin importar cuántas filas
    # acumule con el tiempo.
    try:
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_historial_fecha_hora
            ON historial_medico(fecha_hora)
        """)
    except sqlite3.IntegrityError:
        # Caso raro: si ya hay valores de fecha_hora duplicados (datos
        # tocados a mano, por ejemplo), no vale la pena tumbar el
        # arranque de Ada por esto — nos quedamos con un índice normal,
        # que igual hace rápidas las búsquedas aunque no sea único.
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_historial_fecha_hora
            ON historial_medico(fecha_hora)
        """)
    con.commit()

    # 5. Contexto de eventos — correlaciona cada evento crítico/advertencia
    #    del Event Log con el estado real del equipo (RAM/CPU) en ese
    #    momento, y si el evento es reciente, con el proceso que más
    #    consumía justo entonces. No mide nada nuevo: solo cruza datos
    #    que Ada ya recolecta (historial médico + eventos + procesos).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS eventos_contexto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_tiempo TEXT,
            evento_fuente TEXT,
            ram_libre_gb REAL,
            cpu_pct REAL,
            proceso_culpable TEXT,
            proceso_culpable_pct REAL,
            registrado_en TEXT,
            UNIQUE(evento_tiempo, evento_fuente)
        )
    """)
    con.commit()

    # 5. Salud del SSD — Intel NVMe del Lenovo
    cur.execute("""
        CREATE TABLE IF NOT EXISTS salud_ssd (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            disco_libre_gb REAL,
            disco_total_gb REAL,
            escrituras_sesion_mb REAL
        )
    """)

    con.commit()

    # 6. Decisiones del médico autónomo — auditoría de qué recomendó
    #    Groq y qué hizo Ada realmente (para poder revisar el
    #    historial completo de decisiones automáticas).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS decisiones_medico_ia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            accion TEXT,
            riesgo TEXT,
            razon TEXT,
            ejecutada INTEGER,
            resultado TEXT
        )
    """)
    con.commit()
    _migrar_decisiones_medico_ia(cur, con)

    # 7. Memoria por proceso a largo plazo — perfil histórico por
    #    proceso para detectar fugas de memoria reales (crecimiento
    #    sostenido durante días/semanas), no solo picos puntuales.
    #    Se guarda por deltas (ver registrar_muestra_proceso), no
    #    cada lectura cruda, para no inflar la base de datos.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memoria_por_proceso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            fecha TEXT,
            memoria_pct REAL
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_memoria_proceso_nombre
        ON memoria_por_proceso(nombre)
    """)
    con.commit()

    # 8. Cambios tecnológicos — lo que detecta VigilanteTecnologico
    #    cuando Windows se actualiza (nueva build/versión). Registra
    #    qué cambió, qué módulos de Ada podrían verse afectados, y con
    #    qué prioridad -- para que revisar y actualizar Ada después de
    #    una actualización de Windows sea un vistazo a esta tabla, no
    #    adivinar desde cero.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cambios_tecnologicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            tipo TEXT,
            version_anterior TEXT,
            version_nueva TEXT,
            prioridad TEXT,
            razon TEXT,
            modulos_afectados TEXT,
            revisado INTEGER DEFAULT 0
        )
    """)
    con.commit()

    # 9. Conocimiento confiable a largo plazo — a diferencia de
    #    decisiones_medico_ia (que guarda TODO, éxito y fracaso, y
    #    decae/se purga con el tiempo -- necesario para que el
    #    circuito de seguridad siga contando fallos reales), esta
    #    tabla es la memoria destilada: una fila por cada combinación
    #    (accion, componente) que alguna vez quedó VERIFICADA como
    #    reparación efectiva de verdad (mismo criterio estricto que ya
    #    usa _inferir_exito_desde_resultado -- no "corrió sin error",
    #    sino "se confirmó que sirvió"). No decae ni se recorta por
    #    tamaño (no está en _limpiar_temporal ni en
    #    _verificar_tamano_maximo) porque no crece con el tiempo: solo
    #    hay una fila por combinación posible de acción+componente, se
    #    actualiza (UPSERT), nunca se acumula. Así es "más espacio",
    #    pero solo para lo que realmente importa conservar.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reparaciones_confiables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accion TEXT NOT NULL,
            componente TEXT,
            veces_confirmado INTEGER DEFAULT 0,
            primera_vez TEXT,
            ultima_vez TEXT,
            ultimo_resultado TEXT,
            UNIQUE(accion, componente)
        )
    """)
    con.commit()

    # LIMPIAR AL ARRANCAR — borra todo lo que no importa guardar
    _limpiar_temporal(cur, con)

    # RED DE SEGURIDAD FINAL — pase lo que pase, ada_cerebro.db nunca
    # crece sin límite. La limpieza de arriba borra por antigüedad,
    # pero esto revisa el peso REAL del archivo en disco por si algo
    # (un bug futuro, un pico de actividad) hace que crezca más rápido
    # de lo esperado.
    _verificar_tamano_maximo(cur, con)

    con.close()
    print("✅ Cerebro SQLite iniciado — memoria inteligente lista.")

def _migrar_historial_medico(cur, con):
    """
    Ada ya llevaba tiempo corriendo antes de este fix, así que
    instalaciones existentes tienen historial_medico con el esquema
    viejo (sin la columna fecha_hora). CREATE TABLE IF NOT EXISTS NO
    toca una tabla que ya existe, así que hay que revisar con PRAGMA
    y agregar la columna a mano con ALTER TABLE si hace falta — si no,
    cualquier índice o consulta sobre fecha_hora revienta al arrancar
    (esto es justo lo que pasó: "no such column: fecha_hora").
    """
    try:
        cur.execute("PRAGMA table_info(historial_medico)")
        columnas = [fila[1] for fila in cur.fetchall()]

        if "fecha_hora" not in columnas:
            cur.execute("ALTER TABLE historial_medico ADD COLUMN fecha_hora TEXT")
            con.commit()

        # Rellenar fecha_hora en filas viejas que no la tengan (de antes
        # del fix, cuando "fecha" era la única columna de tiempo).
        cur.execute("""
            UPDATE historial_medico
            SET fecha_hora = fecha || ' 00:00:00'
            WHERE fecha_hora IS NULL AND fecha IS NOT NULL
        """)
        con.commit()
    except Exception as e:
        print(f"[DB MIGRACIÓN] {type(e).__name__}: {e}")

def _migrar_decisiones_medico_ia(cur, con):
    """
    Instalaciones existentes tienen decisiones_medico_ia sin las
    columnas 'severidad' y 'exito' (agregadas para el aprendizaje de
    reparaciones y la priorización por severidad). Mismo patrón que
    _migrar_historial_medico: CREATE TABLE IF NOT EXISTS no toca una
    tabla que ya existe, así que hay que revisar con PRAGMA y agregar
    las columnas a mano si hace falta.
    """
    try:
        cur.execute("PRAGMA table_info(decisiones_medico_ia)")
        columnas = [fila[1] for fila in cur.fetchall()]

        if "severidad" not in columnas:
            cur.execute("ALTER TABLE decisiones_medico_ia ADD COLUMN severidad TEXT")
        if "exito" not in columnas:
            # NULL = no se pudo determinar (no ejecutada, o resultado
            # ambiguo) — 1 = éxito, 0 = fracaso. NULL nunca cuenta ni
            # a favor ni en contra en tasa_exito_reparacion().
            cur.execute("ALTER TABLE decisiones_medico_ia ADD COLUMN exito INTEGER")
        if "componente" not in columnas:
            # Qué parte del equipo motivó la decisión (ssd/ram/cpu/
            # bateria/drivers/eventos) — viene de "componente_dominante"
            # en puntuacion.calcular_severidad_diagnostico(). Permite
            # aprender por TIPO de problema, no solo por acción suelta,
            # para que Ada eventualmente pueda decidir sola sin Groq
            # cuando ya sabe qué funciona para ese componente.
            cur.execute("ALTER TABLE decisiones_medico_ia ADD COLUMN componente TEXT")
        con.commit()
    except Exception as e:
        print(f"[DB MIGRACIÓN] {type(e).__name__}: {e}")


def _verificar_tamano_maximo(cur, con):
    """
    Red de seguridad final: revisa el tamaño REAL del archivo
    ada_cerebro.db en disco. Si supera DB_MAX_MB (config.py) —
    aunque la limpieza por antigüedad ya haya corrido — borra el 20%
    de filas más viejas de cada tabla que puede crecer con el tiempo,
    y compacta el archivo con VACUUM para recuperar el espacio de
    verdad (SQLite no libera espacio en disco solo con DELETE).
    Nunca deja que la base de datos crezca sin límite, pase lo que
    pase.
    """
    from config import DB_MAX_MB
    try:
        if not os.path.exists(DB_PATH):
            return
        tam_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
        if tam_mb <= DB_MAX_MB:
            return

        print(f"⚠️  ada_cerebro.db pesa {tam_mb:.1f}MB (límite {DB_MAX_MB}MB) — recortando historial más viejo.")

        tablas_con_fecha = [
            ("historial_medico",      "fecha_hora"),
            ("eventos_contexto",      "registrado_en"),
            ("decisiones_medico_ia",  "fecha"),
            ("cache_groq",            "fecha"),
            ("optimizaciones",        "fecha"),
            ("salud_ssd",             "fecha"),
            ("memoria_por_proceso",   "fecha"),
        ]
        for tabla, columna_fecha in tablas_con_fecha:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tabla}")
                total = cur.fetchone()[0]
                if total > 20:
                    borrar = int(total * 0.2)
                    cur.execute(f"""
                        DELETE FROM {tabla} WHERE id IN (
                            SELECT id FROM {tabla} ORDER BY {columna_fecha} ASC LIMIT ?
                        )
                    """, (borrar,))
            except sqlite3.OperationalError:
                # Tabla sin esa columna o sin filas — no pasa nada,
                # seguimos con las demás.
                continue
        con.commit()

        cur.execute("VACUUM")
        con.commit()

        nuevo_tam = os.path.getsize(DB_PATH) / (1024 * 1024)
        print(f"✅ Base de datos compactada — ahora pesa {nuevo_tam:.1f}MB.")
    except Exception as e:
        print(f"[DB LÍMITE TAMAÑO] {type(e).__name__}: {e}")

def _limpiar_temporal(cur, con):
    """
    Borra al arrancar usando los días definidos en config.py
    Si cambias los días en config, aquí se aplica automáticamente
    """
    from config import (CACHE_GROQ_DIAS, OPTIMIZACIONES_DIAS, SSD_HISTORIAL_DIAS,
                        HISTORIAL_MEDICO_DIAS, MEMORIA_PROCESO_DIAS)
    cur.execute(f"DELETE FROM cache_groq WHERE fecha < date('now', '-{CACHE_GROQ_DIAS} days')")
    cur.execute(f"DELETE FROM optimizaciones WHERE fecha < date('now', '-{OPTIMIZACIONES_DIAS} days')")
    cur.execute(f"DELETE FROM salud_ssd WHERE fecha < date('now', '-{SSD_HISTORIAL_DIAS} days')")
    cur.execute(f"DELETE FROM historial_medico WHERE fecha < date('now', '-{HISTORIAL_MEDICO_DIAS} days')")
    cur.execute(f"DELETE FROM eventos_contexto WHERE registrado_en < date('now', '-{HISTORIAL_MEDICO_DIAS} days')")
    cur.execute(f"DELETE FROM decisiones_medico_ia WHERE fecha < date('now', '-{HISTORIAL_MEDICO_DIAS} days')")
    cur.execute(f"DELETE FROM memoria_por_proceso WHERE fecha < date('now', '-{MEMORIA_PROCESO_DIAS} days')")
    con.commit()

# ------------------------------------------
#   PROCESOS SOSPECHOSOS
# ------------------------------------------

def registrar_proceso_sospechoso(nombre, ram_pct, cpu_pct):
    """Ada recuerda procesos problemáticos entre sesiones"""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M")

        cur.execute("SELECT id, veces_visto, ram_promedio, cpu_promedio FROM procesos_sospechosos WHERE nombre=?", (nombre,))
        fila = cur.fetchone()

        if fila:
            # Actualizar promedio
            nuevo_ram = (fila[2] * fila[1] + ram_pct) / (fila[1] + 1)
            nuevo_cpu = (fila[3] * fila[1] + cpu_pct) / (fila[1] + 1)
            cur.execute("""
                UPDATE procesos_sospechosos
                SET veces_visto=?, ram_promedio=?, cpu_promedio=?, ultima_vez=?
                WHERE nombre=?
            """, (fila[1] + 1, nuevo_ram, nuevo_cpu, ahora, nombre))
        else:
            cur.execute("""
                INSERT INTO procesos_sospechosos (nombre, veces_visto, ram_promedio, cpu_promedio, primera_vez, ultima_vez)
                VALUES (?, 1, ?, ?, ?, ?)
            """, (nombre, ram_pct, cpu_pct, ahora, ahora))

        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

def es_proceso_conocido_sospechoso(nombre):
    """¿Ada ya vio este proceso antes y era problemático?"""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT veces_visto FROM procesos_sospechosos WHERE nombre=?", (nombre,))
        fila = cur.fetchone()
        con.close()
        return fila[0] if fila else 0
    except Exception:
        return 0

# ------------------------------------------
#   OPTIMIZACIONES
# ------------------------------------------

def registrar_optimizacion(archivos, mb_liberados, ram_antes, ram_despues):
    """Ada aprende cuánto limpia cada vez"""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO optimizaciones (fecha, archivos_eliminados, mb_liberados, ram_antes_pct, ram_despues_pct)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M"), archivos, mb_liberados, ram_antes, ram_despues))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

def resumen_optimizaciones():
    """Cuánto ha limpiado Ada en total"""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT COUNT(*), SUM(mb_liberados), AVG(ram_antes_pct - ram_despues_pct) FROM optimizaciones")
        fila = cur.fetchone()
        con.close()
        if fila and fila[0]:
            return (f"He realizado {fila[0]} optimizaciones en total, "
                    f"liberando {fila[1]:.0f} megabytes. "
                    f"Promedio de RAM liberada: {fila[2]:.1f} por ciento.")
        return "Aún no tengo historial de optimizaciones."
    except Exception:
        return ""

# ------------------------------------------
#   CACHÉ DE GROQ
# ------------------------------------------

def buscar_cache_groq(pregunta):
    """¿Ada ya respondió esto antes? No gasta API"""
    try:
        # Clave simplificada — primeras 60 letras en minúsculas
        clave = pregunta.lower().strip()[:60]
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT respuesta, veces_usada FROM cache_groq WHERE pregunta_clave=?", (clave,))
        fila = cur.fetchone()
        if fila:
            # Actualizar contador de uso
            cur.execute("UPDATE cache_groq SET veces_usada=? WHERE pregunta_clave=?",
                       (fila[1] + 1, clave))
            con.commit()
            con.close()
            return fila[0]
        con.close()
        return None
    except Exception:
        return None

def guardar_cache_groq(pregunta, respuesta):
    """Guarda respuesta de Groq para reutilizar"""
    try:
        clave = pregunta.lower().strip()[:60]
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO cache_groq (pregunta_clave, respuesta, veces_usada, fecha)
            VALUES (?, ?, 1, ?)
        """, (clave, respuesta, datetime.now().strftime("%Y-%m-%d")))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

# ------------------------------------------
#   SALUD DEL SSD
# ------------------------------------------

def registrar_salud_ssd(libre_gb, total_gb):
    """Ada lleva registro del SSD Intel NVMe"""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO salud_ssd (fecha, disco_libre_gb, disco_total_gb, escrituras_sesion_mb)
            VALUES (?, ?, ?, 0)
        """, (datetime.now().strftime("%Y-%m-%d"), libre_gb, total_gb))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

def estado_salud_ssd():
    """
    Tendencia del SSD — ¿está perdiendo espacio con el tiempo?

    Cooldown en memoria de sesión (no en DB, se resetea si Ada
    reinicia -- coherente con el resto de _sesion): antes esto se
    llamaba en cada ciclo de _evaluar_ram() y, mientras el mismo
    registro viejo siguiera dentro de los últimos 10, repetía el
    aviso idéntico cada vez -- varias veces por minuto en la
    práctica. hablar() no pasa por el filtro anti-spam del logging
    (ese solo protege ada_log.txt), así que nada más lo frenaba.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT disco_libre_gb, fecha FROM salud_ssd ORDER BY id DESC LIMIT 10")
        filas = cur.fetchall()
        con.close()
        if len(filas) < 2:
            return None
        mas_reciente = filas[0][0]
        mas_viejo    = filas[-1][0]
        diferencia   = mas_viejo - mas_reciente
        if diferencia > 5:
            # Solo avisa si es la primera vez que se detecta ESTE
            # par de valores, o si ya pasó al menos 1 hora desde el
            # último aviso -- lo que evita el spam sin silenciar
            # una caída real y nueva que aparezca más tarde.
            firma = (round(mas_viejo, 1), round(mas_reciente, 1))
            ultima_firma = _sesion.get("ssd_alerta_firma")
            ultima_ts    = _sesion.get("ssd_alerta_ts", 0)
            ahora = time.time()
            if firma == ultima_firma and (ahora - ultima_ts) < 3600:
                return None
            _sesion["ssd_alerta_firma"] = firma
            _sesion["ssd_alerta_ts"]    = ahora
            return (f"Atención: el disco ha perdido {diferencia:.1f} gigabytes "
                    f"en los últimos registros. Revisa qué está creciendo.")
        return None
    except Exception:
        return None

# ------------------------------------------
#   MEMORIA DE SESIÓN — RAM pura
# ------------------------------------------

def recordar_sesion(clave, valor):
    _sesion[clave] = valor
    if clave == "ultima_orden":
        _sesion["ordenes_dadas"] += 1

def agregar_contexto(texto):
    _sesion["contexto_reciente"].append(texto)
    if len(_sesion["contexto_reciente"]) > 5:
        _sesion["contexto_reciente"].pop(0)

def obtener_contexto():
    return _sesion["contexto_reciente"]

def resumen_sesion():
    ordenes  = _sesion.get("ordenes_dadas", 0)
    inicio   = _sesion.get("inicio", "")
    alertas  = _sesion.get("alertas_emitidas", 0)
    opts     = _sesion.get("optimizaciones_sesion", 0)
    return (f"En esta sesión procesé {ordenes} órdenes desde las {inicio}. "
            f"Emití {alertas} alertas y realicé {opts} optimizaciones.")

# ------------------------------------------
#   HISTORIAL MÉDICO
# ------------------------------------------

def registrar_historial_medico(ram_libre_gb, ram_uso_pct, cpu_pct, disco_libre_gb, procesos_activos):
    """
    Guarda una muestra real cada vez que se llama (cada
    INTERVALO_MONITOREO_SEG). Antes usaba INSERT OR IGNORE con "fecha"
    como clave única, así que solo la primera lectura del día se
    guardaba y el resto se perdía en silencio — el predictor terminaba
    razonando sobre una sola foto al azar por día. Ahora cada lectura
    es su propia fila (fecha_hora es la clave única) y "fecha" queda
    solo para poder agrupar y promediar por día.
    """
    try:
        ahora = datetime.now()
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO historial_medico
            (fecha_hora, fecha, ram_libre_gb, ram_uso_pct, cpu_pct, disco_libre_gb, procesos_activos)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            # Microsegundos para que dos lecturas muy seguidas nunca
            # choquen contra el UNIQUE (en producción llegan cada
            # INTERVALO_MONITOREO_SEG, pero mejor a prueba de balas).
            ahora.strftime("%Y-%m-%d %H:%M:%S.%f"),
            ahora.strftime("%Y-%m-%d"),
            round(ram_libre_gb, 1),
            round(ram_uso_pct, 1),
            round(cpu_pct, 1),
            round(disco_libre_gb, 1),
            procesos_activos
        ))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

def obtener_promedios_diarios(dias=14):
    """
    Promedio real por día (no una sola foto suelta), del más reciente
    al más antiguo. Única fuente de verdad para tendencias — tanto
    diagnostico_tendencias() como medico.predecir_fallos() usan esta
    misma función, para que nunca vuelvan a existir dos cálculos que
    puedan contradecirse sobre el mismo dato.

    Devuelve: [(fecha, ram_libre_prom, disco_libre_prom, cpu_prom, muestras), ...]
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT fecha,
                   AVG(ram_libre_gb),
                   AVG(disco_libre_gb),
                   AVG(cpu_pct),
                   COUNT(*)
            FROM historial_medico
            GROUP BY fecha
            ORDER BY fecha DESC
            LIMIT ?
        """, (dias,))
        filas = cur.fetchall()
        con.close()
        return filas
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return []

def diagnostico_tendencias():
    """Ada analiza si el PC está mejorando o empeorando, con promedios reales por día"""
    filas = obtener_promedios_diarios(14)

    if len(filas) < 3:
        return "Aún estoy recopilando historial médico. Necesito al menos 3 días de datos."

    ram_reciente   = filas[0][1]
    ram_antigua    = filas[-1][1]
    diff_ram       = ram_antigua - ram_reciente
    disco_reciente = filas[0][2]
    disco_antiguo  = filas[-1][2]
    diff_disco     = disco_antiguo - disco_reciente

    msg = f"Historial médico — últimos {len(filas)} días:\n"

    if diff_ram > 2:
        msg += f"⚠️  RAM libre bajó {diff_ram:.1f} GB. Probablemente instalaste software residente.\n"
    elif diff_ram < -1:
        msg += f"✅ RAM libre mejoró {abs(diff_ram):.1f} GB.\n"
    else:
        msg += f"✅ RAM estable — promedio {ram_reciente:.1f} GB libre.\n"

    if diff_disco > 5:
        msg += f"⚠️  Disco perdió {diff_disco:.1f} GB. Pierdes {diff_disco/len(filas):.1f} GB por día.\n"
    elif diff_disco > 2:
        msg += f"⚠️  Disco bajando lentamente — {diff_disco:.1f} GB en {len(filas)} días.\n"
    else:
        msg += f"✅ Disco estable.\n"

    return msg

def _muestra_mas_cercana(cur, momento_str, tolerancia_min=30):
    """
    Busca en historial_medico la muestra más cercana en el tiempo a
    'momento_str'. Si no hay ninguna dentro de la tolerancia, devuelve
    None a propósito — mejor no correlacionar nada que correlacionar
    con un dato de otro momento y sacar una conclusión falsa.
    """
    cur.execute("""
        SELECT fecha_hora, ram_libre_gb, cpu_pct,
               ABS(strftime('%s', fecha_hora) - strftime('%s', ?)) AS dif
        FROM historial_medico
        ORDER BY dif ASC
        LIMIT 1
    """, (momento_str,))
    fila = cur.fetchone()
    if fila and fila[3] is not None and fila[3] <= tolerancia_min * 60:
        return fila[0], fila[1], fila[2]
    return None

def registrar_contexto_evento(evento: dict, proceso_culpable=None, proceso_culpable_pct=None) -> bool:
    """
    Guarda, para un evento del Event Log, el estado real del equipo en
    ese momento (RAM/CPU de la muestra más cercana) y, si se pudo
    identificar, el proceso que más consumía. Los duplicados (mismo
    evento_tiempo + evento_fuente, que se repiten porque
    leer_eventos_criticos siempre relee las últimas 24h) se ignoran
    solos gracias al UNIQUE de la tabla.
    """
    tiempo = evento.get("tiempo")
    fuente = evento.get("fuente")
    if not tiempo or not fuente:
        return False
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cercana = _muestra_mas_cercana(cur, tiempo)
        if not cercana:
            con.close()
            return False
        _, ram_libre, cpu_pct = cercana
        cur.execute("""
            INSERT OR IGNORE INTO eventos_contexto
            (evento_tiempo, evento_fuente, ram_libre_gb, cpu_pct,
             proceso_culpable, proceso_culpable_pct, registrado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            tiempo, fuente, ram_libre, cpu_pct,
            proceso_culpable, proceso_culpable_pct,
            datetime.now().strftime("%Y-%m-%d")
        ))
        con.commit()
        con.close()
        return True
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return False

def patron_procesos_conflictivos(minimo=3):
    """
    Busca procesos que se repiten cerca de varios eventos críticos —
    la señal de "esto probablemente está causando problemas", no solo
    que estuvo presente una vez de casualidad.
    Devuelve: [(proceso, veces_visto, pct_promedio), ...] del más
    repetido al menos repetido.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT proceso_culpable, COUNT(*), AVG(proceso_culpable_pct)
            FROM eventos_contexto
            WHERE proceso_culpable IS NOT NULL
            GROUP BY proceso_culpable
            HAVING COUNT(*) >= ?
            ORDER BY COUNT(*) DESC
        """, (minimo,))
        filas = cur.fetchall()
        con.close()
        return filas
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return []

def _inferir_exito_desde_resultado(resultado: str, ejecutada: bool):
    """
    Aprendizaje de reparaciones: las funciones de auto_reparador.py ya
    devuelven un texto que dice si la reparación se VERIFICÓ, si no
    liberó nada, si falló, etc. (ver reparar_archivos_sistema,
    limpiar_winsxs). En vez de cambiar la firma de esas funciones
    (que rompería el mensaje que Ada le da al usuario), se infiere el
    éxito con las mismas marcas de texto que esas funciones ya usan.

    Retorna 1 (éxito), 0 (fracaso) o None (no se pudo determinar —
    p.ej. no se ejecutó, o el texto no trae ninguna marca conocida).
    Ante la duda, None: mejor no contar un caso ambiguo que ensuciar
    la tasa de éxito con un dato inventado.
    """
    if not ejecutada or not resultado:
        return None

    texto = resultado.lower()

    marcas_exito = [
        "verificada", "liberé", "eliminé", "reconstruida",
        "completada y verificada", "de verdad",
    ]
    marcas_fracaso = [
        "no pude", "no se pudo", "tomó demasiado tiempo",
        "no pudo reparar", "unable to fix", "sin confirmar", "vale la pena revisarlo",
    ]

    # Todas las funciones de auto_reparador.py que fallan por una
    # excepción devuelven el mensaje empezando con "Error ...: {e}"
    # (reparar_archivos_sistema, limpiar_winsxs, limpiar_cache_iconos,
    # reparar_red, actualizar_con_winget, etc.) — se cubre con un
    # prefijo genérico en vez de listar cada frase una por una, que se
    # desactualizaría cada vez que se agregue una reparación nueva.
    empieza_con_error = texto.startswith("error")

    tiene_fracaso = empieza_con_error or any(m in texto for m in marcas_fracaso)
    tiene_exito = (not tiene_fracaso) and any(m in texto for m in marcas_exito)

    if tiene_fracaso:
        return 0
    if tiene_exito:
        return 1
    return None


def necesita_confirmacion_por_persistencia(accion, horas=48):
    """
    Nivel de confirmación intermedio, entre "ejecuta ciego" (riesgo
    bajo) y "solo recomienda" (riesgo alto): para riesgo medio, la
    PRIMERA vez que se recomienda una acción, Ada no la ejecuta —
    solo la deja anotada como "vista, esperando confirmación". Si en
    el siguiente ciclo de diagnóstico el problema sigue ahí y Groq
    vuelve a recomendar la MISMA acción, recién ahí se considera
    confirmada por persistencia (no fue un pico puntual) y se puede
    ejecutar. No requiere que haya un humano despierto para aprobar
    con contraseña — funciona igual en modo invisible.

    Retorna True si la última decisión registrada para esta acción
    fue justo ese "vista, esperando confirmación" reciente (dentro de
    la ventana de horas) — es decir, si YA se puede confirmar ahora.
    Retorna False si es la primera vez que se ve, si la última vez ya
    se ejecutó, o si la espera anterior ya expiró (ventana vencida,
    se trata como una observación nueva).
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT ejecutada, riesgo, fecha FROM decisiones_medico_ia
            WHERE accion = ?
            ORDER BY id DESC
            LIMIT 1
        """, (accion,))
        fila = cur.fetchone()
        con.close()

        if not fila:
            return False  # nunca se vio antes -> primera observación

        ejecutada, riesgo, fecha = fila
        if ejecutada or riesgo != "medio":
            return False  # la última vez ya se ejecutó, o no era este mecanismo

        try:
            momento = datetime.strptime(fecha, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return False  # fecha rara, no arriesgar una ejecución por un dato dudoso

        if (datetime.now() - momento) > timedelta(hours=horas):
            return False  # la espera venció, se trata como observación nueva

        return True  # persistió entre dos ciclos -> confirmada
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return False


def registrar_muestra_proceso(nombre, memoria_pct):
    """
    Memoria por proceso a largo plazo: guarda una muestra SOLO
    cuando el uso de memoria de este proceso cambió lo suficiente
    desde la última vez que se guardó (delta significativo,
    MEMORIA_PROCESO_DELTA_PCT en config.py) — no en cada lectura
    cruda. Así se puede rastrear la tendencia de semanas sin que la
    base de datos crezca sin necesidad real (idea original: guardar
    deltas en vez de cada lectura, para mantener a Ada liviana).
    """
    from config import MEMORIA_PROCESO_DELTA_PCT
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT memoria_pct FROM memoria_por_proceso
            WHERE nombre = ? ORDER BY id DESC LIMIT 1
        """, (nombre,))
        fila = cur.fetchone()

        if fila is not None and abs(memoria_pct - fila[0]) < MEMORIA_PROCESO_DELTA_PCT:
            con.close()
            return  # sin cambio significativo -> no vale la pena guardarlo

        cur.execute("""
            INSERT INTO memoria_por_proceso (nombre, fecha, memoria_pct)
            VALUES (?, ?, ?)
        """, (nombre, datetime.now().strftime("%Y-%m-%d %H:%M"), memoria_pct))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")


def detectar_fugas_memoria(dias=14):
    """
    Revisa, para cada proceso con suficiente historial guardado, si
    viene subiendo de forma sostenida en los últimos `dias` — eso es
    una fuga de memoria real, distinto de un pico puntual que ya
    detecta el análisis de procesos del momento (sistema.py).

    Compara la muestra más vieja contra la más nueva dentro de la
    ventana: si el crecimiento neto supera el umbral y hay muestras
    suficientes para que no sea ruido, lo reporta.

    Retorna una lista de dicts:
    [{"nombre", "memoria_inicial_pct", "memoria_actual_pct",
      "muestras", "voz"}, ...]
    """
    from config import MEMORIA_PROCESO_MIN_MUESTRAS_TENDENCIA, MEMORIA_PROCESO_UMBRAL_FUGA_PCT
    resultado = []
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT DISTINCT nombre FROM memoria_por_proceso")
        nombres = [f[0] for f in cur.fetchall()]

        for nombre in nombres:
            cur.execute(f"""
                SELECT fecha, memoria_pct FROM memoria_por_proceso
                WHERE nombre = ? AND fecha >= date('now', '-{dias} days')
                ORDER BY id ASC
            """, (nombre,))
            filas = cur.fetchall()

            if len(filas) < MEMORIA_PROCESO_MIN_MUESTRAS_TENDENCIA:
                continue

            inicial = filas[0][1]
            final = filas[-1][1]
            crecimiento = final - inicial

            if crecimiento >= MEMORIA_PROCESO_UMBRAL_FUGA_PCT:
                resultado.append({
                    "nombre": nombre,
                    "memoria_inicial_pct": inicial,
                    "memoria_actual_pct": final,
                    "muestras": len(filas),
                    "voz": (
                        f"{nombre} viene subiendo su uso de memoria de forma sostenida: "
                        f"de {inicial:.1f}% a {final:.1f}% en los últimos {dias} días. "
                        f"Podría ser una fuga de memoria."
                    ),
                })
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
    return resultado


def registrar_reparacion_confiable(accion, componente, resultado):
    """
    Escribe (o actualiza) en reparaciones_confiables — SOLO se llama
    desde registrar_decision_medico_ia() cuando _inferir_exito_desde_
    resultado() ya determinó exito=1, es decir, un resultado verificado
    de verdad (no "corrió sin error", sino confirmado). UPSERT sobre
    (accion, componente): no acumula una fila por vez, suma un contador
    y actualiza fecha/resultado — por eso esta tabla no necesita
    decaimiento ni límite de tamaño, ya está acotada por diseño.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
        cur.execute("""
            INSERT INTO reparaciones_confiables
                (accion, componente, veces_confirmado, primera_vez, ultima_vez, ultimo_resultado)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(accion, componente) DO UPDATE SET
                veces_confirmado = veces_confirmado + 1,
                ultima_vez = excluded.ultima_vez,
                ultimo_resultado = excluded.ultimo_resultado
        """, (accion, componente, ahora, ahora, resultado[:300]))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")


def conocimiento_confiable(componente=None, limite=10):
    """
    Lo que Ada sabe con certeza que funciona -- solo reparaciones que
    en algún momento se verificaron de verdad, no intentos sueltos.
    Si se pasa componente, filtra a ese tipo de problema (ram/ssd/
    eventos/etc). Ordenado por veces_confirmado descendente: lo más
    probado primero. Es la respuesta directa a "qué es realmente
    importante y qué no" -- lectura simple de una tabla ya curada,
    sin tener que recalcular nada sobre decisiones_medico_ia.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        if componente:
            cur.execute("""
                SELECT accion, componente, veces_confirmado, primera_vez, ultima_vez, ultimo_resultado
                FROM reparaciones_confiables WHERE componente = ?
                ORDER BY veces_confirmado DESC LIMIT ?
            """, (componente, limite))
        else:
            cur.execute("""
                SELECT accion, componente, veces_confirmado, primera_vez, ultima_vez, ultimo_resultado
                FROM reparaciones_confiables
                ORDER BY veces_confirmado DESC LIMIT ?
            """, (limite,))
        filas = cur.fetchall()
        con.close()
        return [
            {"accion": f[0], "componente": f[1], "veces_confirmado": f[2],
             "primera_vez": f[3], "ultima_vez": f[4], "ultimo_resultado": f[5]}
            for f in filas
        ]
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return []


def registrar_decision_medico_ia(accion, riesgo, razon, ejecutada, resultado="", severidad=None, componente=None):
    """
    Deja anotado en la base de datos qué recomendó Groq y qué hizo
    Ada de verdad — para poder revisar después el historial completo
    de decisiones automáticas del médico. severidad es opcional
    (categoria de calcular_severidad_diagnostico) para saber, con el
    tiempo, si el médico actúa distinto según qué tan grave era la
    situación. componente es opcional (componente_dominante de la
    misma función) — qué parte del equipo motivó la decisión, para
    poder aprender por tipo de problema (ver decision_local_confiable).
    """
    try:
        exito = _inferir_exito_desde_resultado(resultado, ejecutada)
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO decisiones_medico_ia
            (fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito, componente)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            accion, riesgo, razon, 1 if ejecutada else 0, resultado[:300],
            severidad, exito, componente
        ))
        con.commit()
        con.close()

        # Memoria destilada: solo cuando quedó verificado de verdad
        # (exito == 1, el criterio estricto de _inferir_exito_desde_
        # resultado), no cada vez que se ejecuta algo. Va después del
        # commit de arriba -- si esto falla, la decisión ya quedó
        # registrada igual, no se pierde el registro operativo por un
        # problema en la capa destilada.
        if exito == 1:
            registrar_reparacion_confiable(accion, componente, resultado)
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

def historial_decisiones_medico_ia(limite=10):
    """Últimas decisiones del médico autónomo, para revisar o preguntarle a Ada."""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT fecha, accion, riesgo, razon, ejecutada, resultado, severidad, exito
            FROM decisiones_medico_ia
            ORDER BY id DESC
            LIMIT ?
        """, (limite,))
        filas = cur.fetchall()
        con.close()
        return filas
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return []

def _peso_decaimiento(fecha_str: str, vida_media_dias: float) -> float:
    """
    Peso (0-1] de un intento según cuántos días pasaron desde
    'fecha_str' (formato '%Y-%m-%d %H:%M', el mismo que guarda
    registrar_decision_medico_ia). Decaimiento exponencial: a los
    vida_media_dias, el peso ya cayó a la mitad; al doble de esos
    días, a un cuarto; y así.

    Nunca llega a 0 -- un intento viejo pesa cada vez menos, pero no
    se descarta del todo acá. Descartar filas viejas de la base es una
    decisión distinta, ya resuelta por _limpiar_temporal() (borrado
    por antigüedad); esto solo bajarles el PESO en el cálculo mientras
    siguen presentes.

    Sin fecha parseable, devuelve 1.0 (no penaliza) -- ante la duda,
    nunca se le resta confianza a un intento por un problema de
    formato que no es culpa suya.
    """
    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return 1.0
    dias = max(0.0, (datetime.now() - fecha).total_seconds() / 86400)
    return 0.5 ** (dias / vida_media_dias)


def tasa_exito_reparacion(accion, ultimas=5):
    """
    Aprendizaje de reparaciones: de las últimas N veces que se
    EJECUTÓ esta acción (ejecutada=1), cuántas fueron éxito real
    según _inferir_exito_desde_resultado. Los casos ambiguos
    (exito IS NULL) no cuentan ni a favor ni en contra — ni en el
    numerador ni en el denominador.

    Retorna: {"intentos": int, "exitos": int, "porcentaje": float|None}
    porcentaje es None si no hay suficiente data para opinar
    (0 intentos con resultado claro). "intentos" y "exitos" son
    conteos crudos (para mostrar en mensajes tal cual), pero
    "porcentaje" está PONDERADO por antigüedad -- un fallo de ayer
    pesa más que un éxito de hace varias vidas medias
    (config.REPARACION_VIDA_MEDIA_DECAIMIENTO_DIAS), así que una
    reparación que dejó de funcionar recientemente ve caer su
    porcentaje más rápido que si todos los intentos pesaran igual.
    """
    from config import REPARACION_VIDA_MEDIA_DECAIMIENTO_DIAS
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT exito, fecha FROM decisiones_medico_ia
            WHERE accion = ? AND ejecutada = 1 AND exito IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
        """, (accion, ultimas))
        filas = cur.fetchall()
        con.close()

        intentos = len(filas)
        if intentos == 0:
            return {"intentos": 0, "exitos": 0, "porcentaje": None}

        exitos = sum(f[0] for f in filas)
        peso_total = peso_exitos = 0.0
        for exito, fecha in filas:
            peso = _peso_decaimiento(fecha, REPARACION_VIDA_MEDIA_DECAIMIENTO_DIAS)
            peso_total += peso
            peso_exitos += peso * exito

        porcentaje = round((peso_exitos / peso_total) * 100, 1) if peso_total > 0 else None
        return {"intentos": intentos, "exitos": exitos, "porcentaje": porcentaje}
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return {"intentos": 0, "exitos": 0, "porcentaje": None}

def fallos_consecutivos(accion, componente=None, limite_busqueda=15):
    """
    CIRCUITO DE SEGURIDAD contra bucles infinitos: cuenta cuántos
    fallos SEGUIDOS acumula esta acción, contando desde la ejecución
    más reciente hacia atrás y parando en cuanto encuentra el primer
    éxito (o casos ambiguos, que no cuentan ni suman ni cortan la
    racha -- se ignoran y se sigue mirando hacia atrás).

    A diferencia de tasa_exito_reparacion() (que necesita una MUESTRA
    GRANDE para opinar, ej. 5 intentos con 40% de éxito), esto
    reacciona de inmediato: 3 fallos seguidos son 3 fallos seguidos,
    sin importar cuántos intentos totales haya en la historia. Es la
    diferencia entre un límite APRENDIDO (tasa) y un límite DURO
    programado en el núcleo -- este último es el que evita que un
    agente que se repara a sí mismo quede atrapado reintentando su
    propio error sin ningún tope.

    componente=None cuenta fallos consecutivos de la acción en
    CUALQUIER componente (más estricto); pasar un componente cuenta
    solo los fallos consecutivos para ese tipo de problema específico.

    Retorna un entero >= 0.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        if componente:
            cur.execute("""
                SELECT exito FROM decisiones_medico_ia
                WHERE accion = ? AND componente = ? AND ejecutada = 1
                ORDER BY id DESC
                LIMIT ?
            """, (accion, componente, limite_busqueda))
        else:
            cur.execute("""
                SELECT exito FROM decisiones_medico_ia
                WHERE accion = ? AND ejecutada = 1
                ORDER BY id DESC
                LIMIT ?
            """, (accion, limite_busqueda))
        filas = [f[0] for f in cur.fetchall()]
        con.close()

        consecutivos = 0
        for exito in filas:
            if exito is None:
                continue  # ambiguo -- no corta la racha ni suma, se ignora
            if exito == 0:
                consecutivos += 1
            else:
                break  # primer éxito encontrado -- la racha de fallos termina acá
        return consecutivos
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return 0

# Nombres en español para día de la semana (datetime.weekday(): 0=lunes)
_DIAS_SEMANA_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Franjas horarias amplias -- no hace falta más granularidad que esto
# para detectar un patrón real ("siempre a la tarde"), y mantenerlas
# anchas evita falsos patrones por casualidad con pocos datos.
_FRANJAS_HORARIAS = [
    ("madrugada", range(0, 6)),
    ("mañana",    range(6, 12)),
    ("tarde",     range(12, 18)),
    ("noche",     range(18, 24)),
]

def detectar_patrones_temporales(dias_atras=30, minimo_casos=4, umbral_pct=60):
    """
    Busca, para cada componente con historial reciente en
    decisiones_medico_ia, si sus problemas se concentran en un día
    de la semana o una franja horaria específica -- en vez de estar
    distribuidos parejo en el tiempo. Esto es lo más parecido a
    "reconocer un patrón que se repite" que tenemos hoy: no mirar
    solo el síntoma de ahora, sino cuándo suele aparecer.

    No agrega ninguna tabla ni recolección nueva -- usa las mismas
    filas que ya se guardan cada vez que el médico autónomo actuó.
    Es una simple agrupación de datos que ya existían, no un costo
    nuevo de RAM/CPU en segundo plano.

    Un patrón solo se reporta si tiene evidencia suficiente
    (minimo_casos) Y suficiente concentración (>= umbral_pct% de los
    casos en el mismo día/franja) -- por debajo de eso, no dice nada:
    mejor omitir un patrón débil que inventar una coincidencia.

    Retorna una lista de dicts, cada uno:
    {"componente": str, "tipo": "dia_semana"|"franja_horaria",
     "detalle": str, "casos": int, "total": int, "porcentaje": float,
     "voz": str}
    """
    patrones = []
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        limite_fecha = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d %H:%M")

        cur.execute("""
            SELECT DISTINCT componente FROM decisiones_medico_ia
            WHERE componente IS NOT NULL AND componente != 'ninguno' AND fecha >= ?
        """, (limite_fecha,))
        componentes = [f[0] for f in cur.fetchall()]

        for componente in componentes:
            cur.execute("""
                SELECT fecha FROM decisiones_medico_ia
                WHERE componente = ? AND fecha >= ?
            """, (componente, limite_fecha))
            fechas_crudas = [f[0] for f in cur.fetchall()]

            fechas = []
            for f in fechas_crudas:
                try:
                    fechas.append(datetime.strptime(f, "%Y-%m-%d %H:%M"))
                except ValueError:
                    continue

            total = len(fechas)
            if total < minimo_casos:
                continue

            # 1) Patrón por día de la semana
            conteo_dias = {}
            for dt in fechas:
                conteo_dias[dt.weekday()] = conteo_dias.get(dt.weekday(), 0) + 1
            dia_top, casos_dia = max(conteo_dias.items(), key=lambda kv: kv[1])
            pct_dia = round((casos_dia / total) * 100, 1)

            if pct_dia >= umbral_pct:
                nombre_dia = _DIAS_SEMANA_ES[dia_top]
                patrones.append({
                    "componente": componente,
                    "tipo": "dia_semana",
                    "detalle": nombre_dia,
                    "casos": casos_dia,
                    "total": total,
                    "porcentaje": pct_dia,
                    "voz": (f"Noto un patrón: {casos_dia} de los últimos {total} problemas de "
                            f"{componente} ({pct_dia}%) cayeron en {nombre_dia}. "
                            f"No parece casualidad."),
                })
                continue  # ya hay patrón fuerte, no hace falta revisar franja horaria también

            # 2) Patrón por franja horaria (solo si no hubo patrón de día)
            conteo_franjas = {}
            for dt in fechas:
                for nombre, rango in _FRANJAS_HORARIAS:
                    if dt.hour in rango:
                        conteo_franjas[nombre] = conteo_franjas.get(nombre, 0) + 1
                        break
            if conteo_franjas:
                franja_top, casos_franja = max(conteo_franjas.items(), key=lambda kv: kv[1])
                pct_franja = round((casos_franja / total) * 100, 1)
                if pct_franja >= umbral_pct:
                    patrones.append({
                        "componente": componente,
                        "tipo": "franja_horaria",
                        "detalle": franja_top,
                        "casos": casos_franja,
                        "total": total,
                        "porcentaje": pct_franja,
                        "voz": (f"Noto un patrón: {casos_franja} de los últimos {total} problemas de "
                                f"{componente} ({pct_franja}%) ocurrieron de {franja_top}. "
                                f"Puede haber algo que se dispara en ese horario."),
                    })

        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

    return patrones

def tasa_exito_reparacion_por_componente(accion, componente, ultimas=5):
    """
    Igual que tasa_exito_reparacion, pero filtrado a las ejecuciones
    de ESTA acción que fueron motivadas por ESTE componente específico
    (ssd/ram/cpu/bateria/drivers/eventos). Una misma acción puede
    haberse usado para distintos tipos de problema con resultados
    distintos -- mezclarlo todo en una sola tasa global esconde esa
    diferencia. Es la base para que decision_local_confiable() pueda
    comparar EVIDENCIA por tipo de problema en vez de solo por acción
    suelta, que es lo más parecido a aprendizaje real que tenemos hoy.

    Igual que tasa_exito_reparacion(), "porcentaje" está PONDERADO por
    antigüedad (config.REPARACION_VIDA_MEDIA_DECAIMIENTO_DIAS) --
    esto es lo que hace que decision_local_confiable() dude de una
    acción que empezó a fallar hace poco, aunque todavía tenga éxitos
    viejos dentro de la ventana de conteo.
    """
    from config import REPARACION_VIDA_MEDIA_DECAIMIENTO_DIAS
    if not componente:
        return {"intentos": 0, "exitos": 0, "porcentaje": None}
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT exito, fecha FROM decisiones_medico_ia
            WHERE accion = ? AND componente = ? AND ejecutada = 1 AND exito IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
        """, (accion, componente, ultimas))
        filas = cur.fetchall()
        con.close()

        intentos = len(filas)
        if intentos == 0:
            return {"intentos": 0, "exitos": 0, "porcentaje": None}

        exitos = sum(f[0] for f in filas)
        peso_total = peso_exitos = 0.0
        for exito, fecha in filas:
            peso = _peso_decaimiento(fecha, REPARACION_VIDA_MEDIA_DECAIMIENTO_DIAS)
            peso_total += peso
            peso_exitos += peso * exito

        porcentaje = round((peso_exitos / peso_total) * 100, 1) if peso_total > 0 else None
        return {"intentos": intentos, "exitos": exitos, "porcentaje": porcentaje}
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return {"intentos": 0, "exitos": 0, "porcentaje": None}

def decision_local_confiable(componente, minimo_intentos=None, umbral_pct=None):
    """
    El objetivo final del aprendizaje de reparaciones: que Ada deje de
    depender de Groq para problemas que ya conoce bien.

    v2: antes esto confiaba ciegamente en la ÚLTIMA acción que se usó
    para este componente, sin comparar contra otras que también se
    hubieran probado -- si "desactivar_servicios_basura" funcionó
    9/10 veces para "ram" pero la última vez que hubo un problema de
    ram se usó otra acción que salió mal, Ada igual se hubiera quedado
    con esa última por pura recencia. Eso no es aprender, es recordar
    sin comparar.

    Ahora compara TODAS las acciones que alguna vez se ejecutaron para
    este mismo componente_dominante y elige la que acumula la MEJOR
    tasa de éxito real, entre las que ya tienen evidencia suficiente
    (minimo_intentos). Si dos acciones califican, gana la de mayor
    porcentaje -- comparación real entre opciones, no solo memoria del
    último intento.

    No reemplaza a Groq para problemas nuevos o poco vistos -- solo
    para el patrón exacto que ya demostró, con evidencia real y
    repetida, que funciona. Si en algún momento la acción ganadora
    empieza a fallar, tasa_exito_reparacion_por_componente() lo
    refleja enseguida y deja de ganar la comparación.

    Retorna {"accion": str, "riesgo": str, "razon": str, "porcentaje": float}
    o None si no hay suficiente confianza todavía (o no hay historial
    para este componente).
    """
    from config import (REPARACION_MINIMO_INTENTOS_PARA_DECISION_LOCAL,
                         REPARACION_UMBRAL_CONFIANZA_DECISION_LOCAL)
    minimo_intentos = minimo_intentos or REPARACION_MINIMO_INTENTOS_PARA_DECISION_LOCAL
    umbral_pct = umbral_pct or REPARACION_UMBRAL_CONFIANZA_DECISION_LOCAL

    if not componente:
        return None
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT DISTINCT accion FROM decisiones_medico_ia
            WHERE componente = ? AND ejecutada = 1
        """, (componente,))
        acciones_probadas = [f[0] for f in cur.fetchall()]
        con.close()
        if not acciones_probadas:
            return None

        candidatos = []
        for accion in acciones_probadas:
            tasa = tasa_exito_reparacion_por_componente(accion, componente, ultimas=minimo_intentos)
            if tasa["intentos"] >= minimo_intentos and tasa["porcentaje"] is not None:
                candidatos.append({"accion": accion, "porcentaje": tasa["porcentaje"], "intentos": tasa["intentos"]})

        calificados = [c for c in candidatos if c["porcentaje"] >= umbral_pct]
        if not calificados:
            return None
        mejor = max(calificados, key=lambda c: c["porcentaje"])
        otros = [c for c in candidatos if c["accion"] != mejor["accion"]]
        segundo = max(otros, key=lambda c: c["porcentaje"]) if otros else None

        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT riesgo, razon FROM decisiones_medico_ia
            WHERE accion = ? AND componente = ? AND ejecutada = 1
            ORDER BY id DESC LIMIT 1
        """, (mejor["accion"], componente))
        fila = cur.fetchone()
        con.close()
        riesgo, razon_previa = fila if fila else ("bajo", "")

        # Con el segundo mejor candidato, la razón puede explicar la
        # comparación real (evidencia contra evidencia), no solo el
        # número ganador aislado -- esto es lo que un "por qué elegí
        # esto" con sustancia necesita, en vez de una cifra suelta.
        if segundo:
            explicacion = (f"Ya aprendida: {mejor['porcentaje']}% de éxito en {mejor['intentos']} intentos "
                           f"para este tipo de problema, mejor que {segundo['accion']} "
                           f"({segundo['porcentaje']}% en {segundo['intentos']} intentos)")
        else:
            explicacion = (f"Ya aprendida: {mejor['porcentaje']}% de éxito en {mejor['intentos']} "
                           f"intentos para este tipo de problema")

        return {
            "accion": mejor["accion"],
            "riesgo": riesgo or "bajo",
            "razon": explicacion,
            "porcentaje": mejor["porcentaje"],
        }
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return None

def accion_ejecutada_recientemente(accion, horas=24):
    """
    Revisa si esta misma acción del médico autónomo ya se ejecutó en
    las últimas X horas. Sin esto, como leer_eventos_criticos() lee
    una ventana de 24h, el mismo error viejo del Event Log seguía
    "detectándose" en cada ciclo (cada 3 horas) y Ada terminaba
    corriendo DISM/SFC completo una y otra vez para el mismo problema
    ya resuelto — pesado y sin ningún beneficio real.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM decisiones_medico_ia
            WHERE accion = ? AND ejecutada = 1
            AND fecha >= datetime('now', ?)
        """, (accion, f'-{horas} hours'))
        count = cur.fetchone()[0]
        con.close()
        return count > 0
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return False

# ------------------------------------------
#   CAMBIOS TECNOLÓGICOS — VigilanteTecnologico
#   Qué cambió en Windows, qué módulos de Ada
#   podrían verse afectados, y con qué prioridad
# ------------------------------------------

def registrar_cambio_tecnologico(tipo, version_anterior, version_nueva, prioridad, razon, modulos_afectados=None):
    """
    Deja anotado un cambio tecnológico detectado (hoy: actualizaciones
    de Windows) para que revisar y actualizar Ada después sea leer
    esta tabla, no adivinar desde cero qué pudo haberse roto.

    modulos_afectados es una lista de strings (nombres de archivos de
    Ada) -- se guarda como JSON. prioridad: "alta"|"media"|"baja".
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO cambios_tecnologicos
            (fecha, tipo, version_anterior, version_nueva, prioridad, razon, modulos_afectados, revisado)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            tipo, version_anterior, version_nueva, prioridad, razon,
            json.dumps(modulos_afectados or [], ensure_ascii=False),
        ))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")

def historial_cambios_tecnologicos(limite=10, solo_pendientes=False):
    """
    Últimos cambios tecnológicos detectados, más reciente primero.
    solo_pendientes=True filtra a los que todavía no se marcaron como
    revisados -- para no seguir mencionando algo que ya se resolvió.

    Retorna lista de dicts con todas las columnas, incluyendo
    modulos_afectados ya deserializado de JSON a lista de Python.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        query = "SELECT id, fecha, tipo, version_anterior, version_nueva, prioridad, razon, modulos_afectados, revisado FROM cambios_tecnologicos"
        if solo_pendientes:
            query += " WHERE revisado = 0"
        query += " ORDER BY id DESC LIMIT ?"
        cur.execute(query, (limite,))
        filas = cur.fetchall()
        con.close()

        resultado = []
        for f in filas:
            try:
                modulos = json.loads(f[7]) if f[7] else []
            except (json.JSONDecodeError, TypeError):
                modulos = []
            resultado.append({
                "id": f[0], "fecha": f[1], "tipo": f[2],
                "version_anterior": f[3], "version_nueva": f[4],
                "prioridad": f[5], "razon": f[6],
                "modulos_afectados": modulos, "revisado": bool(f[8]),
            })
        return resultado
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return []

def marcar_cambio_tecnologico_revisado(id_cambio):
    """Marca un cambio tecnológico como ya revisado -- para que Ada no
    lo siga mencionando en cada log una vez que ya se atendió."""
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("UPDATE cambios_tecnologicos SET revisado = 1 WHERE id = ?", (id_cambio,))
        con.commit()
        con.close()
        return True
    except Exception as e:
        print(f"[DB ERROR] {type(e).__name__}: {e}")
        return False
