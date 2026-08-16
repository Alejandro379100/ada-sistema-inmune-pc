# ==========================================
#   watchdog_ada.py v1.1
#   Vigila si el scheduler de Ada sigue AVANZANDO
#   (no solo si el proceso sigue vivo -- eso ya
#   lo cubre el mutex de instancia única en app.py).
#
#   Corre SEPARADO de Ada, vía su propia tarea
#   programada de Windows cada 5 minutos -- si el
#   hilo del scheduler está trabado, Ada misma no
#   podría notarlo ni reiniciarse a sí misma.
# ==========================================

import os
import time
import logging
import subprocess
from logging.handlers import RotatingFileHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LATIDO_PATH = os.path.join(BASE_DIR, "privado", "latido.txt")
LOG_PATH = os.path.join(BASE_DIR, "privado", "watchdog_log.txt")

# Con el scheduler tickeando ~cada 1s, 5 minutos sin latido es una
# anomalía real, no un pico puntual -- no hay riesgo de reiniciar
# a Ada por una vuelta lenta ocasional (la vuelta más lenta conocida
# hoy es _evaluar_cpu, con hasta 30s, y corre en su propio hilo, no
# bloquea el heartbeat del hilo principal).
UMBRAL_SEGUNDOS = 300

# Log rotativo nativo, mismo criterio de liviandad que ya sigue el
# resto de Ada (LOG_ROTACION_DIAS/LOG_BACKUPS_MAXIMOS en config.py):
# este script escribe muy poco (solo cuando encuentra algo anómalo,
# ver main()), así que 200 KB con 1 backup alcanza de sobra -- pero
# sin rotación, un log que en teoría no debería crecer nunca
# terminaría creciendo para siempre igual, que es justo el tipo de
# estado sin límite que el resto del proyecto ya evita en todos
# lados (Steady State, en el vocabulario de Release It!).
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
_handler = RotatingFileHandler(LOG_PATH, maxBytes=200_000, backupCount=1, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])


def _ultimo_latido():
    """None si no hay latido registrado -- eso NO es evidencia de
    cuelgue (puede ser una instalación nueva, o Ada apagada a
    propósito), así que nunca dispara un reinicio por sí solo."""
    try:
        with open(LATIDO_PATH, "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except Exception:
        return None


def _ada_esta_corriendo() -> bool:
    """
    Chequeo liviano por nombre de proceso, con tasklist nativo --
    a propósito no depende de psutil ni de nada del entorno de Ada,
    para no compartir un punto de fallo con lo que está vigilando.
    """
    try:
        salida = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return "pythonw.exe" in salida.stdout
    except Exception:
        return False


def main():
    latido = _ultimo_latido()
    if latido is None:
        return

    antiguedad = time.time() - latido
    if antiguedad < UMBRAL_SEGUNDOS:
        return  # todo normal -- no se loguea cada corrida, solo lo anómalo

    if not _ada_esta_corriendo():
        # El proceso ya no existe -- la tarea programada "Ada" lo
        # relanza sola en el próximo intervalo/login. Nada que hacer
        # acá, y reiniciar algo que ya no corre no tendría sentido.
        logging.warning(f"Latido de {antiguedad:.0f}s pero Ada no está corriendo -- nada que hacer.")
        return

    # OJO: taskkill /IM pythonw.exe mata TODOS los procesos con ese
    # nombre, no solo Ada -- en este equipo hoy es seguro porque Ada
    # es el único pythonw.exe persistente conocido, pero si en algún
    # momento corre otro script con pythonw en paralelo, esto lo
    # mataría también. Vale la pena revisar esto si eso cambia.
    logging.error(f"Latido de {antiguedad:.0f}s con Ada corriendo -- scheduler trabado. Reiniciando.")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe"],
                        capture_output=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(2)
        subprocess.run(["schtasks", "/Run", "/TN", "Ada"],
                        capture_output=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW)
        logging.info("Ada reiniciada por el watchdog.")
    except Exception as e:
        logging.error(f"No pude reiniciar Ada: {e}")


if __name__ == "__main__":
    main()
