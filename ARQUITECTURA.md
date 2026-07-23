# Ada v5.0 — Mapa del proyecto

Este archivo existe para que cualquier IA (o Alejandro dentro de 6 meses)
entienda la arquitectura de Ada en 2 minutos, sin tener que leer 4.500
líneas de código de una sentada.

## Qué es Ada

Un asistente personal que corre en la PC de Alejandro (Windows, Lenovo
ThinkPad, i5-8350U, 16GB RAM). Se comunica **100% por texto en terminal**
(sin voz — Vosk se quitó en la v5.0 porque no entendía el acento). Cuida
la salud del equipo sola (RAM, CPU, disco, batería, SSD) y responde
órdenes en lenguaje natural, con Groq como respaldo de IA para lo que
no reconoce por palabras clave.

## Cómo arranca

1. `iniciar_ada.bat` → activa el entorno virtual y corre `app.py`.
2. `app.py` pregunta: **[1] Terminal** o **[2] Invisible**.
   - Terminal: conversación normal, Ada responde por consola.
   - Invisible: Ada esconde su propia ventana (`ctypes` + `ShowWindow`)
     y sigue viva en segundo plano, solo cuidando el PC sin pedir nada.
3. En ambos casos arranca `sistema._scheduler()` — un solo hilo que
   reemplaza a todos los monitores sueltos, revisando RAM/CPU/disco/
   Edge/WhatsApp/llamadas/procesos cada cierto intervalo.

## Los módulos, de afuera hacia adentro

| Archivo | Qué hace |
|---|---|
| `app.py` | Arranque, logging, menú terminal/invisible, hibernación |
| `comandos.py` | Traduce lo que escribe Alejandro a una acción concreta |
| `ia.py` | Llamadas a Groq (respuestas + autoconocimiento del PC) |
| `sistema.py` | El "sistema inmune": limpieza, salud, scheduler central |
| `medico.py` | Diagnóstico profundo: Event Log, SSD (SMART), presión de RAM |
| `auto_reparador.py` | DISM/SFC, drivers, batería, reparaciones automáticas |
| `puntuacion.py` | Le pone un score 0-100 a cada proceso corriendo |
| `nucleo_procesos.py` | **Única** puerta de entrada a `psutil.process_iter()` |
| `perfil_pc.py` | El "ADN" del equipo: specs, rutas protegidas, rutas de limpieza |
| `memoria.py` | SQLite: historial, caché de Groq, estadísticas |
| `modo_enfoque.py` | Pomodoro + bloqueo de distracciones |
| `monitor_arranque.py` | Analiza qué tan rápido/lento arrancó Windows |
| `seguridad.py` | Contraseña para acciones destructivas (apagar, borrar, etc.) |
| `voz.py` | Ya NO es voz real — es la terminal de texto (se dejó el nombre por compatibilidad) |
| `config.py` | Todos los números ajustables en un solo lugar |

## Reglas de oro que el código respeta

1. **Nunca tocar procesos críticos** — lista en `perfil_pc.py["procesos_criticos"]`.
2. **Nunca borrar dentro de rutas_protegidas** — se valida en
   `sistema._ruta_esta_protegida()` antes de cualquier limpieza.
3. **Nunca leer procesos del sistema fuera de `nucleo_procesos.py`** —
   así se evita la condición de carrera entre hilos que antes generaba
   miles de errores repetidos en el log (bug real, resuelto en v5.0).
4. **Todo subprocess.run/Popen debe llevar `creationflags=subprocess.CREATE_NO_WINDOW`**
   salvo que la intención sea abrir algo visible a propósito (notepad,
   configuración de Windows, etc.).

## Logs

`ada_log.txt` se rota automáticamente cada 5 días (`config.LOG_ROTACION_DIAS`)
y solo se guarda 1 respaldo anterior — nunca se llena el disco. Además,
si el mismo error se repite muchas veces seguidas, el filtro anti-spam
de `app.py` lo resume en vez de escribirlo mil veces.

## Historial de versiones relevante

- **v4.0** → tenía Vosk (reconocimiento de voz), un bug de condición de
  carrera en `psutil.process_iter()` que generaba miles de errores por
  día, una coma de más que rompía la sintaxis de `sistema.py`, rutas
  con "USUARIO" sin reemplazar, y código muerto en `comandos.py`.
- **v5.0** → sin Vosk (100% texto), bug de procesos resuelto de raíz,
  sintaxis arreglada, rutas dinámicas con el usuario real, guardrail de
  `rutas_protegidas` conectado de verdad, logs con rotación de 5 días,
  y menú de arranque terminal/invisible.
