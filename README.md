# Ada — Sistema Inmune Personal para Windows

*[English version](README.en.md)*

Asistente de IA que diagnostica y repara de forma autónoma problemas de rendimiento en un PC con Windows (RAM, CPU, disco, batería, drivers, integridad del sistema), aprendiendo del historial real de la máquina en la que corre.

Ada no es un limpiador genérico: cada decisión pasa por un motor de riesgo (bajo / medio / alto), una lista blanca cerrada de acciones permitidas, y un circuito de seguridad que la detiene si algo empieza a fallar en cadena. Las acciones de riesgo alto nunca se ejecutan sin confirmación humana.

## Qué hace

- **Diagnóstico continuo** en segundo plano: RAM, CPU (por núcleo), disco (SSD, con predicción de fugas), batería, drivers sin firmar, integridad de archivos del sistema
- **Decisión con IA (Groq)**: propone un plan de hasta 2 acciones basado en el diagnóstico, con degradación en 3 niveles (modelo grande → modelo rápido → heurística local sin IA si Groq no está disponible)
- **Aprendizaje por historial**: compara el éxito real de cada acción en *esta* máquina antes de decidir actuar sola, con decaimiento temporal (un éxito de hace un mes pesa menos que uno de ayer)
- **Verificación real**: después de actuar, vuelve a medir el sensor para confirmar si el problema se resolvió — no asume
- **Circuito de seguridad**: se detiene sola tras fallos consecutivos, nunca dispara una restauración completa del sistema por su cuenta
- **Consciente del momento**: antes de correr reparaciones pesadas (SFC/DISM), chequea si el equipo está en buen momento (RAM libre, sin Windows Update compitiendo por el disco) — si no, la deja pendiente y la termina sola en cuanto se libera, sin perder el pedido
- **Heartbeat y watchdog**: el scheduler central escribe una señal de vida propia; un proceso vigilante independiente, con su propia tarea programada de Windows, reinicia a Ada si esa señal deja de actualizarse
- **Modo texto**: se opera 100% por comandos de texto en terminal, sin reconocimiento de voz (se descartó por poco confiable)

## Arquitectura

| Módulo | Responsabilidad |
|---|---|
| `app.py` | Arranque, logging, instancia única |
| `sistema.py` | Scheduler central (hilos en segundo plano) |
| `medico.py` | Diagnóstico y decisión médica autónoma |
| `comandos.py` | Interpreta órdenes de texto |
| `memoria.py` | Persistencia SQLite, historial, aprendizaje |
| `ia.py` | Integración con Groq, degradación en 3 niveles |
| `auto_reparador.py` | Catálogo cerrado de reparaciones reales |
| `manual_playbook.py` | Mapea componente/anomalía al comando PowerShell exacto cuando el circuito de seguridad bloquea una reparación |
| `watchdog_ada.py` | Proceso independiente (tarea programada propia) que vigila el heartbeat del scheduler y reinicia a Ada si deja de responder |
| `puntuacion.py` | Scoring y triage de procesos |
| `fsm_medico.py` | Máquina de estados del ciclo de diagnóstico |
| `telemetria.py` | Logging estructurado (JSON) para análisis |
| `backtesting.py` | Analiza el historial para medir si las decisiones mejoran con el tiempo |
| `vigilante_tecnologico.py` | Detecta actualizaciones de Windows que puedan afectar a Ada |
| `perfil_pc.py` | Especificaciones y reglas de protección de la máquina |
| `seguridad.py` | Contraseña para acciones destructivas |

## Testing

136 tests automatizados con `pytest`, incluyendo mocks de `winreg`, WMI y `subprocess` para poder correr la suite fuera de Windows.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

## Stack

Python · SQLite · Groq API (Llama 3.3 70B / 3.1 8B) · psutil · pywin32 · pytest

## Base de datos

Ada guarda su historial en SQLite (`ada_cerebro.db`, generado automáticamente, no incluido en el repositorio). Algunas de sus tablas principales:

```sql
-- Snapshot periódico de RAM/CPU/disco (usado para detectar tendencias)
CREATE TABLE historial_medico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT,
    ram_libre_gb REAL,
    ram_uso_pct REAL,
    cpu_pct REAL,
    disco_libre_gb REAL,
    procesos_activos INTEGER
);

-- Auditoría de cada decisión autónoma: qué recomendó Groq, qué hizo Ada, y el resultado real
CREATE TABLE decisiones_medico_ia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT,
    accion TEXT,
    riesgo TEXT,
    razon TEXT,
    ejecutada INTEGER,
    resultado TEXT
);

-- Tendencia de espacio libre en disco, para predecir fugas antes de que sean críticas
CREATE TABLE salud_ssd (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT,
    disco_libre_gb REAL,
    disco_total_gb REAL
);
```

## Solución de problemas

| Problema | Causa | Solución |
|---|---|---|
| `ModuleNotFoundError: No module named 'pytest'` | El venv no está activado | `.\.venv\Scripts\Activate.ps1` antes de correr `pytest` |
| `Fatal error in launcher` al correr `pytest` | Se movió la carpeta del proyecto después de crear el venv (tiene rutas absolutas grabadas) | Borrar `.venv` y recrearlo: `python -m venv .venv`, reinstalar requirements |
| `git push` rechazado ("fetch first") | El repositorio remoto tiene cambios que tu copia local no tiene | `git pull` primero (resuelve el merge automático en la mayoría de los casos), después `git push` |
| Timeout leyendo batería (>15s) vía WMI/PowerShell | Puntual, no confirmado como frecuente | No requiere acción salvo que se repita seguido |
| Se abre una ventana y se cierra sola, después se abre OTRA (con el cartel de permisos de Windows en el medio) | Esperado -- `ada.bat` pide permisos de administrador para poder correr reparaciones reales (DISM/SFC). Windows solo permite pedir ese permiso cerrando la ventana actual y abriendo una nueva ya elevada | Ninguna, es el comportamiento normal. La ventana avisa esto mismo antes de cerrarse |

## Personalización visual (opcional)

Ada habla en un celeste eléctrico por defecto (código nativo, sin librerías —
ver `voz.py`), así que ya se ve así corras donde corras. Si además usás
**Windows Terminal** (no la consola clásica), podés agregarle una imagen de
fondo y un esquema de color a juego, igual que en las capturas de este README:

1. Guardá `fondo_ada.png` (incluida en este repo) en la carpeta del proyecto.
2. Abrí `windows-terminal-ada.jsonc` (también en este repo) y seguí las
   instrucciones de ahí — es un perfil opcional para pegar en la configuración
   de Windows Terminal, con la ruta que tengas vos en tu computadora.

Es completamente opcional — Ada funciona igual sin esto, es solo estética.

## Nota técnica: ¿por qué aparecen dos procesos `pythonw.exe`?

Al revisar el Administrador de tareas de Windows mientras Ada corre, vas a ver
**dos** procesos llamados `pythonw.exe`. Esto **no es una instancia duplicada**
de Ada — es el comportamiento estándar de los entornos virtuales de Python
3.13+ en Windows:

- El primero (`.venv\Scripts\pythonw.exe`) es un lanzador liviano que redirige
  al Python base del sistema.
- El segundo (`C:\PythonXXX\pythonw.exe`) es el intérprete real, el que
  efectivamente corre el código de Ada.

Es el mismo patrón en cualquier aplicación Python moderna que use un entorno
virtual en Windows, no algo exclusivo de este proyecto. Para confirmarlo con
tus propios ojos: abrí el Administrador de tareas → pestaña "Detalles" →
click derecho en los encabezados de columna → "Seleccionar columnas" →
activá "Línea de comandos". Vas a ver que cada proceso tiene una ruta
distinta, y que el mutex de instancia única (`app.py`) solo se ejecuta una
vez, en el proceso real — nunca hay dos Adas corriendo en paralelo.

Confirmado con evidencia real (auditoría de creación de procesos de Windows,
Event ID 4688) tras una investigación a fondo: sin este chequeo, es fácil
confundirlo con un bug de duplicación cuando en realidad es el diseño
esperado del propio Python.

## Nota

Este proyecto está hecho a medida de una máquina específica (`perfil_pc.py` define sus especificaciones exactas y reglas de protección) — no es un producto genérico listo para instalar en cualquier PC sin adaptar ese archivo primero.

## Un ejemplo real: diagnosticar antes de arreglar

En agosto de 2026, el circuito de seguridad llevaba semanas bloqueando una
reparación automática (`reparar_archivos_sistema`) sin explicación clara.
En vez de asumir una causa, revisamos el log completo de 3 semanas y
encontramos el patrón real: los fallos coincidían con `TiWorker.exe`
(Windows Update) compitiendo por el mismo recurso que Ada necesitaba.
Confirmamos la hipótesis con el Administrador de Tareas en tiempo real
antes de tocar una sola línea de código.

La corrección no fue "reintentar más" — fue enseñarle a Ada a reconocer
el mal momento y diferir la reparación sola, sin perder el pedido. Al
probarlo en Windows real encontramos una segunda pieza faltante: ni
corriendo el comando a mano, ni con Ada, había forma de avisarle a Ada
que un problema ya se había revisado y resuelto. Se agregó ese mecanismo,
se probó de punta a punta, y quedó confirmado funcionando en producción.

Siete tests nuevos cubren el primer chequeo (136 en total). El resto
quedó documentado en el historial de decisiones del proyecto.

## Cómo se construyó este proyecto

Este sistema fue diseñado y dirigido por mí, definiendo cada decisión, prioridad y comportamiento — pero el código en sí lo escribió **Claude (Anthropic)**, a partir de mis indicaciones, iterando en conjunto durante varias sesiones. No tengo formación como programador; mi aporte fue el diseño del producto, las prioridades, las decisiones de seguridad y el criterio sobre qué debía hacer Ada y qué no.

Lo cuento así de claro porque me interesa ser honesto: este proyecto demuestra mi capacidad para diseñar un sistema completo, tomar decisiones técnicas informadas, y dirigir el desarrollo de un producto real usando IA como herramienta — no mi capacidad para escribir código de forma independiente. Busco roles orientados a **gestión de producto, gestión de proyectos técnicos, automatización o prompt engineering**, donde ese tipo de trabajo es exactamente el que se necesita.
