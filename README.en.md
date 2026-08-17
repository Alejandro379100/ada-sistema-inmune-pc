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
- **Timing-aware**: before running heavy repairs (SFC/DISM), it checks whether the machine is in good shape for it (free RAM, no Windows Update competing for disk access) — if not, it defers the request and finishes it on its own once conditions clear, without losing track of it
- **Heartbeat and watchdog**: the central scheduler writes its own liveness signal; an independent watcher process, with its own Windows scheduled task, restarts Ada if that signal stops updating
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
| `manual_playbook.py` | Maps a component/anomaly to the exact PowerShell command when the safety circuit blocks a repair |
| `watchdog_ada.py` | Independent process (own scheduled task) that watches the scheduler's heartbeat and restarts Ada if it stops responding |
| `puntuacion.py` | Process scoring and triage |
| `fsm_medico.py` | State machine for the diagnostic cycle |
| `telemetria.py` | Structured (JSON) logging for analysis |
| `backtesting.py` | Analyzes history to measure whether decisions improve over time |
| `vigilante_tecnologico.py` | Detects Windows updates that might affect Ada |
| `perfil_pc.py` | Machine specifications and protection rules |
| `seguridad.py` | Password protection for destructive actions |

## Testing

136 automated tests with `pytest`, including mocks for `winreg`, WMI, and `subprocess` so the suite can run outside of Windows.

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

## Technical note: why do two `pythonw.exe` processes show up?

When checking Windows Task Manager while Ada is running, you'll see
**two** processes named `pythonw.exe`. This is **not a duplicate instance**
of Ada — it's standard behavior for Python 3.13+ virtual environments on
Windows:

- The first one (`.venv\Scripts\pythonw.exe`) is a lightweight launcher
  that redirects to the base system Python.
- The second one (`C:\PythonXXX\pythonw.exe`) is the real interpreter,
  the one actually running Ada's code.

This is the same pattern in any modern Python application using a virtual
environment on Windows, nothing specific to this project. To confirm it
yourself: open Task Manager → "Details" tab → right-click the column
headers → "Select columns" → enable "Command line". You'll see each
process has a different path, and that the single-instance mutex
(`app.py`) only runs once, in the real process — there are never two
Adas running in parallel.

Confirmed with real evidence (Windows process-creation auditing,
Event ID 4688) after a thorough investigation: without this check, it's
easy to mistake this for a duplication bug when it's actually Python's
own expected design.

## Note

This project is tailored to one specific machine (`perfil_pc.py` defines its exact specs and protection rules) — it's not a generic product ready to install on any PC without adapting that file first.

## A real example: diagnose before fixing

In August 2026, the safety circuit had been blocking an automatic repair
(`reparar_archivos_sistema`) for weeks with no clear explanation. Instead
of assuming a cause, we reviewed the full 3-week log and found the real
pattern: the failures lined up with `TiWorker.exe` (Windows Update)
competing for the same resource Ada needed. We confirmed the hypothesis
with Task Manager in real time before touching a single line of code.

The fix wasn't "retry more" — it was teaching Ada to recognize a bad
moment and defer the repair on its own, without losing the request.
Testing it on real Windows surfaced a second missing piece: neither
running the command by hand nor asking Ada directly gave any way to
tell Ada that a problem had already been reviewed and resolved. That
mechanism was added, tested end to end, and confirmed working in
production.

Seven new tests cover the first check (136 total). The rest is
documented in the project's decision history.

## How this project was built

This system was designed and directed by me, defining every decision, priority, and behavior — but the code itself was written by **Claude (Anthropic)**, based on my instructions, iterating together over several sessions. I have no formal training as a programmer; my contribution was the product design, priorities, security decisions, and the judgment calls on what Ada should and shouldn't do.

I'm sharing this openly because honesty matters to me: this project demonstrates my ability to design a complete system, make informed technical decisions, and direct the development of a real product using AI as a tool — not my ability to write code independently. I'm looking for roles in **product management, technical project management, automation, or prompt engineering**, where exactly that kind of work is what's needed.
