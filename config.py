# ==========================================
#   config.py - Centro de Control de Ada
#   Todos los ajustes en un solo lugar.
#   Cambia aquí, se aplica en todo Ada.
# ==========================================

# ------------------------------------------
#   ENTRADA/SALIDA
#   Ada ya no usa micrófono (Vosk se quitó por
#   completo — fallaba reconociendo el acento).
#   Todo pasa por texto en la terminal.
# ------------------------------------------

# ------------------------------------------
#   HIBERNACIÓN
# ------------------------------------------
MINUTOS_HIBERNACION = 15      # Sin actividad → Ada hiberna para liberar RAM

# ------------------------------------------
#   REGISTRO DE ACTIVIDAD (LOGS)
# ------------------------------------------
LOG_ROTACION_DIAS   = 5       # Cada 5 días se archiva el log viejo y se reemplaza
LOG_BACKUPS_MAXIMOS = 1       # Solo se guarda 1 log anterior — el resto se borra solo

# ------------------------------------------
#   RAM Y CPU
# ------------------------------------------
RAM_META_LIBRE_GB       = 6.0  # Mínimo libre para programar fluido en VS Code
RAM_ALERTA_PCT          = 65   # % → Ada avisa
RAM_CRITICA_GB          = 4.0  # GB libres → Ada actúa sola
CPU_ALERTA_PCT          = 90   # % sostenido → Ada avisa
NUCLEO_SATURADO_PCT         = 90   # % al que un núcleo individual se considera saturado
NUCLEO_DESBALANCE_PROMEDIO_MAX = 50  # si el promedio general es menor a esto pero hay núcleos saturados, es un proceso acaparando un núcleo, no carga real

# ------------------------------------------
#   DISCO
# ------------------------------------------
DISCO_ALERTA_LIBRE_GB   = 15   # GB libres → Ada avisa
DISCO_CRITICO_LIBRE_GB  = 8    # GB libres → Ada alerta urgente

# ------------------------------------------
#   MONITOREO
# ------------------------------------------
INTERVALO_MONITOREO_SEG = 180  # Cada 3 min revisa RAM, CPU, disco
INTERVALO_ANALISIS_SEG  = 600  # Cada 10 min análisis profundo de procesos
INTERVALO_MEDICO_IA_SEG = 10800  # Cada 3 horas: diagnóstico completo + Groq decide una reparación de la lista blanca

# ------------------------------------------
#   GROQ — DOS MODELOS SEGÚN URGENCIA
# ------------------------------------------
# Modelo potente — para preguntas de Alejandro
GROQ_MODELO_PRINCIPAL   = "llama-3.3-70b-versatile"
GROQ_MAX_TOKENS_PUBLICO = 120

# Modelo rápido y liviano — para análisis internos silenciosos
GROQ_MODELO_RAPIDO      = "llama-3.1-8b-instant"
GROQ_MAX_TOKENS_INTERNO = 80

# ------------------------------------------
#   DEGRADACIÓN ELEGANTE DEL PROVEEDOR DE IA
# ------------------------------------------
# Si Groq (70B) no responde dentro de este tiempo, se corta la espera
# y se prueba con el modelo rápido (8B) -- un ciclo del médico no
# puede quedar colgado esperando una respuesta que no llega, sobre
# todo corriendo en modo invisible sin nadie mirando.
GROQ_TIMEOUT_PRINCIPAL_SEG = 12
# El modelo rápido ya es liviano de por sí, pero si TAMPOCO responde
# en este tiempo (sin internet, Groq caído del todo), se cae al
# último escalón: una heurística local sin ningún modelo de IA.
GROQ_TIMEOUT_RAPIDO_SEG = 8

# ------------------------------------------
#   PROGRAMAS
# ------------------------------------------
# Edge se cierra automáticamente si se abre solo — Alejandro no lo usa
CERRAR_EDGE_AUTOMATICO = True

# WhatsApp — Ada pregunta antes de cerrar
PREGUNTAR_WHATSAPP      = True

# Tiempo de inactividad antes de preguntar por WhatsApp (minutos)
MINUTOS_INACTIVIDAD_WHATSAPP = 15

# ------------------------------------------
#   MÉDICO AUTÓNOMO — APRENDIZAJE DE REPARACIONES
# ------------------------------------------
# Con menos intentos que esto, no hay suficiente historial para
# opinar — el médico deja que Groq decida sin ese factor.
REPARACION_MINIMO_INTENTOS_PARA_EVALUAR = 3
# Si la tasa de éxito de una acción cae por debajo de esto (con ya
# suficientes intentos), el médico deja de ejecutarla sola aunque
# Groq y la lista blanca digan que es de riesgo bajo/medio — la baja
# a "solo recomendar" hasta que un humano la revise.
REPARACION_UMBRAL_TASA_EXITO_MINIMA = 40

# Con al menos esta cantidad de intentos exitosos consecutivos para
# el mismo tipo de problema (mismo componente_dominante), Ada puede
# decidir sola sin preguntarle a Groq — ya aprendió qué funciona en
# este equipo. Solo aplica a acciones de riesgo bajo/medio de la
# lista automática, nunca a las que requieren confirmación humana.
REPARACION_MINIMO_INTENTOS_PARA_DECISION_LOCAL = 8
# Tasa de éxito mínima (%) para que esa confianza sea real y no una
# racha de suerte.
REPARACION_UMBRAL_CONFIANZA_DECISION_LOCAL = 90

# CIRCUITO DE SEGURIDAD contra bucles infinitos: si una misma acción
# falla esta cantidad de veces SEGUIDAS para el mismo componente (sin
# ningún éxito de por medio), Ada la bloquea de inmediato -- sin
# esperar a acumular una muestra grande como hace
# REPARACION_UMBRAL_TASA_EXITO_MINIMA. Esto es un límite DURO
# programado en el núcleo, no una decisión aprendida: existe para que
# un agente que se repara a sí mismo nunca pueda quedar atrapado
# intentando arreglar su propio fallo sin límite. Se resetea solo en
# cuanto la acción vuelve a tener éxito una vez.
REPARACION_LIMITE_FALLOS_CONSECUTIVOS = 3

# DECAIMIENTO TEMPORAL DEL CONOCIMIENTO APRENDIDO: la ventana de
# conteo (REPARACION_MINIMO_INTENTOS_PARA_DECISION_LOCAL, "ultimas=N")
# ya limita CUÁNTOS intentos viejos entran en la cuenta, pero no CUÁN
# viejos son -- un éxito de hace 4 meses, antes de un Windows Update
# que rompió esa reparación, pesa exactamente igual que uno de ayer
# mientras siga dentro de la ventana. Con esta vida media, cada
# intento pesa la mitad cada N días desde que ocurrió: un fallo de
# ayer pesa mucho más que un éxito de hace dos vidas medias, así que
# el conocimiento se ajusta solo con el tiempo, sin depender solo de
# acumular fallos nuevos para "empujar" a los viejos fuera de la
# ventana por cantidad.
REPARACION_VIDA_MEDIA_DECAIMIENTO_DIAS = 30

# ------------------------------------------
#   MEMORIA POR PROCESO A LARGO PLAZO
# ------------------------------------------
# No se guarda cada lectura cruda (eso infla la DB sin necesidad real
# — la memoria de un proceso no cambia de golpe segundo a segundo).
# Solo se guarda una muestra nueva cuando cambió al menos esto desde
# la última guardada — así se puede rastrear la tendencia de semanas
# sin peso extra en el disco.
MEMORIA_PROCESO_DELTA_PCT = 1.5
# Memoria mínima para que un proceso valga la pena rastrear a largo
# plazo (los cientos de procesos con <0.3% de RAM no aportan nada
# a la detección de fugas y solo suman filas).
MEMORIA_PROCESO_MIN_PCT_PARA_RASTREAR = 0.3
# Con menos muestras que esto en la ventana, no hay suficiente
# evidencia todavía para hablar de una tendencia real.
MEMORIA_PROCESO_MIN_MUESTRAS_TENDENCIA = 4
# Crecimiento sostenido mínimo (en puntos porcentuales de RAM) en la
# ventana de días para considerarlo una fuga real, no solo que el
# usuario abrió más pestañas.
MEMORIA_PROCESO_UMBRAL_FUGA_PCT = 3.0
# Cuántos días de historial por proceso se conservan antes de limpiar.
MEMORIA_PROCESO_DIAS = 30

# ------------------------------------------
#   SQLITE — RETENCIÓN DE DATOS
# ------------------------------------------
CACHE_GROQ_DIAS         = 30   # Días antes de limpiar caché de Groq
OPTIMIZACIONES_DIAS     = 60   # Días antes de limpiar historial
SSD_HISTORIAL_DIAS      = 90   # Días antes de limpiar historial del SSD
HISTORIAL_MEDICO_DIAS   = 60   # Días de muestras médicas antes de limpiar (ahora se guarda 1 fila por lectura, no por día)
DB_MAX_MB               = 5    # Tamaño máximo de la base de datos en MB

