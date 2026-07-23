# ==========================================
#   medir_liviandad.py
#
#   Herramienta INDEPENDIENTE de Ada — no la
#   modifica ni la toca. Se corre en una
#   terminal aparte MIENTRAS Ada está corriendo
#   normalmente, y mide su consumo real de RAM
#   y CPU en tu máquina durante un rato.
#
#   Uso:
#     1. Dejá Ada corriendo como siempre (con
#        ada.bat o como la tengas configurada).
#     2. Abrí OTRA terminal y corré:
#           python medir_liviandad.py
#     3. Dejalo un rato (por defecto 10 minutos,
#        usando a la PC normal mientras tanto).
#     4. Al final te muestra el reporte y lo
#        guarda en medicion_liviandad.txt para
#        que me lo compartas.
# ==========================================

import time
import sys
import statistics
from datetime import datetime

import psutil

DURACION_MINUTOS = 10
INTERVALO_SEGUNDOS = 5


def _encontrar_proceso_ada():
    """
    Busca el proceso de Python que está corriendo app.py de Ada.
    No asume un nombre exacto de ventana ni de .exe -- busca por la
    línea de comando, que es lo único confiable si Ada corre como
    'python app.py' o empaquetada.
    """
    candidatos = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(p.info["cmdline"] or []).lower()
            if "app.py" in cmdline and "ada" in cmdline.replace("\\", "/"):
                candidatos.append(p)
            elif "app.py" in cmdline:
                candidatos.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return candidatos


def main():
    print("Buscando el proceso de Ada...")
    candidatos = _encontrar_proceso_ada()

    if not candidatos:
        print("\nNo encontré ningún proceso corriendo app.py.")
        print("¿Está Ada corriendo ahora mismo? Iniciala primero y volvé a correr este script.")
        sys.exit(1)

    if len(candidatos) > 1:
        print(f"\nEncontré {len(candidatos)} procesos que podrían ser Ada:")
        for i, p in enumerate(candidatos):
            print(f"  [{i}] PID {p.pid} - {' '.join(p.info['cmdline'])}")
        idx = input("¿Cuál es? (número, o Enter para el primero): ").strip()
        proc = candidatos[int(idx)] if idx else candidatos[0]
    else:
        proc = candidatos[0]

    print(f"\nMidiendo PID {proc.pid} durante {DURACION_MINUTOS} minutos.")
    print("Usá tu PC normalmente mientras tanto -- así el número refleja uso real, no reposo.\n")

    muestras_ram_mb = []
    muestras_cpu_pct = []
    inicio = time.time()
    fin = inicio + DURACION_MINUTOS * 60

    # Primer llamado a cpu_percent() siempre da 0.0 -- es el punto de
    # referencia, no una medición real. Se descarta a propósito.
    proc.cpu_percent(interval=None)

    while time.time() < fin:
        try:
            time.sleep(INTERVALO_SEGUNDOS)
            ram_mb = proc.memory_info().rss / (1024 * 1024)
            cpu_pct = proc.cpu_percent(interval=None)
            muestras_ram_mb.append(ram_mb)
            muestras_cpu_pct.append(cpu_pct)
            transcurrido = int(time.time() - inicio)
            print(f"  [{transcurrido:>4}s] RAM: {ram_mb:6.1f} MB   CPU: {cpu_pct:5.1f}%")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            print("\nEl proceso de Ada terminó o dejé de tener acceso a él. Corto la medición acá.")
            break

    if not muestras_ram_mb:
        print("No junté ninguna muestra -- no hay nada que reportar.")
        sys.exit(1)

    reporte = []
    reporte.append("=" * 50)
    reporte.append("REPORTE DE LIVIANDAD DE ADA")
    reporte.append(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    reporte.append(f"Duración real: {int(time.time() - inicio)}s ({len(muestras_ram_mb)} muestras)")
    reporte.append("-" * 50)
    reporte.append(f"RAM  promedio: {statistics.mean(muestras_ram_mb):.1f} MB")
    reporte.append(f"RAM  mínima:   {min(muestras_ram_mb):.1f} MB")
    reporte.append(f"RAM  máxima:   {max(muestras_ram_mb):.1f} MB")
    reporte.append(f"CPU  promedio: {statistics.mean(muestras_cpu_pct):.1f}%")
    reporte.append(f"CPU  máximo:   {max(muestras_cpu_pct):.1f}%")
    reporte.append("=" * 50)
    reporte.append("")
    reporte.append("Para referencia (RAM en reposo, procesos típicos de Windows):")
    reporte.append("  - Chrome (1 pestaña):      ~150-300 MB")
    reporte.append("  - VS Code:                 ~200-400 MB")
    reporte.append("  - Spotify:                 ~150-250 MB")
    reporte.append("  - Un servicio de fondo liviano: <50 MB")

    texto_reporte = "\n".join(reporte)
    print("\n" + texto_reporte)

    with open("medicion_liviandad.txt", "w", encoding="utf-8") as f:
        f.write(texto_reporte)
    print("\nGuardado en medicion_liviandad.txt -- compartime ese archivo o pegame estos números.")


if __name__ == "__main__":
    main()
