# Ada — Personal Immune System for Windows

*[Versión en español](README.md)*

An AI assistant that autonomously diagnoses and repairs performance issues on a Windows PC (RAM, CPU, disk, battery, drivers, system file integrity), learning from the real history of the machine it runs on.

Ada is not a generic cleaner: every decision goes through a risk engine (low / medium / high), a closed whitelist of allowed actions, and a safety circuit that stops it if something starts failing in a chain. High-risk actions are never executed without human confirmation.

## What it does

- **Continuous background diagnostics**: RAM, CPU (per core), disk (SSD, with leak prediction), battery, unsigned drivers, system file integrity
- **AI-driven decisions (Groq)**: proposes a plan of up to 2 actions based on the diagnosis, with 3-level degradation (large model → fast model → local heuristic if Groq is unavailable)
- **History-based learning**: compares the real success rate of each action on *this specific machine* before deciding to act alone, with time decay (a success from a month ago weighs less than one from yesterday)
- **Real verification**: after acting, it re-measures the sensor to confirm whether the problem was actually solved — it never assumes
- **Safety circuit**: stops itself after consecutive failures, never triggers a full system restore on its own
- **Text mode**: operated 100% through text commands in a terminal, no voice recognition (dropped due to unreliable accuracy)

## Architecture

| Module | Responsibility |
|---|---|
| `app.py` | Startup, logging, single instance |
| `sistema.py` | Central scheduler (background threads) |
| `medico.py` | Autonomous diagnosis and medical decision-making |
| `comandos.py` | Interprets text commands |
| `memoria.py` | SQLite persistence, history, learning |
| `ia.py` | Groq integration, 3-level degradation |
| `auto_reparador.py` | Closed catalog of real repair actions |
| `puntuacion.py` | Process scoring and triage |
| `fsm_medico.py` | State machine for the diagnostic cycle |
| `telemetria.py` | Structured (JSON) logging for analysis |
| `backtesting.py` | Analyzes history to measure whether decisions improve over time |
| `vigilante_tecnologico.py` | Detects Windows updates that might affect Ada |
| `perfil_pc.py` | Machine specifications and protection rules |
| `seguridad.py` | Password protection for destructive actions |

## Testing

129 automated tests with `pytest`, including mocks for `winreg`, WMI, and `subprocess` so the suite can run outside of Windows.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

## Stack

Python · SQLite · Groq API (Llama 3.3 70B / 3.1 8B) · psutil · pywin32 · pytest

## Database

Ada stores its history in SQLite (`ada_cerebro.db`, auto-generated, not included in the repository). Some of its main tables:

```sql
-- Periodic RAM/CPU/disk snapshot (used to detect trends)
CREATE TABLE historial_medico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT,
    ram_libre_gb REAL,
    ram_uso_pct REAL,
    cpu_pct REAL,
    disco_libre_gb REAL,
    procesos_activos INTEGER
);

-- Audit trail for every autonomous decision: what Groq recommended, what Ada did, and the real outcome
CREATE TABLE decisiones_medico_ia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT,
    accion TEXT,
    riesgo TEXT,
    razon TEXT,
    ejecutada INTEGER,
    resultado TEXT
);

-- Free disk space trend, to predict leaks before they become critical
CREATE TABLE salud_ssd (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT,
    disco_libre_gb REAL,
    disco_total_gb REAL
);
```

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError: No module named 'pytest'` | The venv isn't activated | Run `.\.venv\Scripts\Activate.ps1` before `pytest` |
| `Fatal error in launcher` running `pytest` | The project folder was moved after creating the venv (it has hardcoded absolute paths) | Delete `.venv` and recreate it: `python -m venv .venv`, reinstall requirements |
| `git push` rejected ("fetch first") | The remote repository has changes your local copy doesn't have | `git pull` first (auto-resolves the merge in most cases), then `git push` |
| Battery read timeout (>15s) via WMI/PowerShell | One-off, not confirmed as frequent | No action needed unless it repeats often |

## Note

This project is tailored to one specific machine (`perfil_pc.py` defines its exact specs and protection rules) — it's not a generic product ready to install on any PC without adapting that file first.

## How this project was built

This system was designed and directed by me, defining every decision, priority, and behavior — but the code itself was written by **Claude (Anthropic)**, based on my instructions, iterating together over several sessions. I have no formal training as a programmer; my contribution was the product design, priorities, security decisions, and the judgment calls on what Ada should and shouldn't do.

I'm sharing this openly because honesty matters to me: this project demonstrates my ability to design a complete system, make informed technical decisions, and direct the development of a real product using AI as a tool — not my ability to write code independently. I'm looking for roles in **product management, technical project management, automation, or prompt engineering**, where exactly that kind of work is what's needed.
