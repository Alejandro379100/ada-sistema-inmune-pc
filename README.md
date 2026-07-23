# Ada — Sistema Inmune Personal para Windows

Asistente de IA que diagnostica y repara de forma autónoma problemas de rendimiento en un PC con Windows (RAM, CPU, disco, batería, drivers, integridad del sistema), aprendiendo del historial real de la máquina en la que corre.

Ada no es un limpiador genérico: cada decisión pasa por un motor de riesgo (bajo / medio / alto), una lista blanca cerrada de acciones permitidas, y un circuito de seguridad que la detiene si algo empieza a fallar en cadena. Las acciones de riesgo alto nunca se ejecutan sin confirmación humana.

## Qué hace

- **Diagnóstico continuo** en segundo plano: RAM, CPU (por núcleo), disco (SSD, con predicción de fugas), batería, drivers sin firmar, integridad de archivos del sistema
- **Decisión con IA (Groq)**: propone un plan de hasta 2 acciones basado en el diagnóstico, con degradación en 3 niveles (modelo grande → modelo rápido → heurística local sin IA si Groq no está disponible)
- **Aprendizaje por historial**: compara el éxito real de cada acción en *esta* máquina antes de decidir actuar sola, con decaimiento temporal (un éxito de hace un mes pesa menos que uno de ayer)
- **Verificación real**: después de actuar, vuelve a medir el sensor para confirmar si el problema se resolvió — no asume
- **Circuito de seguridad**: se detiene sola tras fallos consecutivos, nunca dispara una restauración completa del sistema por su cuenta
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
| `puntuacion.py` | Scoring y triage de procesos |
| `fsm_medico.py` | Máquina de estados del ciclo de diagnóstico |
| `telemetria.py` | Logging estructurado (JSON) para análisis |
| `backtesting.py` | Analiza el historial para medir si las decisiones mejoran con el tiempo |
| `vigilante_tecnologico.py` | Detecta actualizaciones de Windows que puedan afectar a Ada |
| `perfil_pc.py` | Especificaciones y reglas de protección de la máquina |
| `seguridad.py` | Contraseña para acciones destructivas |

## Testing

129 tests automatizados con `pytest`, incluyendo mocks de `winreg`, WMI y `subprocess` para poder correr la suite fuera de Windows.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

## Stack

Python · SQLite · Groq API (Llama 3.3 70B / 3.1 8B) · psutil · pywin32 · pytest

## Nota

Este proyecto está hecho a medida de una máquina específica (`perfil_pc.py` define sus especificaciones exactas y reglas de protección) — no es un producto genérico listo para instalar en cualquier PC sin adaptar ese archivo primero.

## Cómo se construyó este proyecto

Este sistema fue diseñado y dirigido por mí, definiendo cada decisión, prioridad y comportamiento — pero el código en sí lo escribió **Claude (Anthropic)**, a partir de mis indicaciones, iterando en conjunto durante varias sesiones. No tengo formación como programadora; mi aporte fue el diseño del producto, las prioridades, las decisiones de seguridad y el criterio sobre qué debía hacer Ada y qué no.

Lo cuento así de claro porque me interesa ser honesta: este proyecto demuestra mi capacidad para diseñar un sistema completo, tomar decisiones técnicas informadas, y dirigir el desarrollo de un producto real usando IA como herramienta — no mi capacidad para escribir código de forma independiente. Busco roles orientados a **gestión de producto, gestión de proyectos técnicos, automatización o prompt engineering**, donde ese tipo de trabajo es exactamente el que se necesita.
