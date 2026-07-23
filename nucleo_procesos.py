# ==========================================
#   nucleo_procesos.py v1.0 - Acceso seguro a psutil
#
#   PROBLEMA QUE RESUELVE (el bug real de los miles
#   de errores "[SCHEDULER ERROR] KeyError"):
#
#   psutil.process_iter() usa una caché GLOBAL interna
#   compartida por todo el programa (psutil._pmap).
#   Ada tiene varios hilos (scheduler, voz, comandos)
#   llamando psutil.process_iter() AL MISMO TIEMPO con
#   distintos atributos. Cuando dos hilos lo hacen a la
#   vez, uno puede sobreescribir la información del otro
#   a mitad de camino, y entonces p.info["name"] ya no
#   existe -> KeyError. Esto no es culpa de un solo
#   archivo: pasaba cada vez que dos partes de Ada
#   miraban los procesos del sistema en simultáneo.
#
#   LA SOLUCIÓN: todo el programa pasa por UNA sola
#   puerta (este archivo) protegida con un candado
#   (threading.Lock). Mientras un hilo lee los procesos,
#   ningún otro hilo puede leerlos al mismo tiempo, y el
#   resultado se copia a una lista de diccionarios
#   normales ANTES de soltar el candado. Así nunca más
#   se pisan entre ellos.
# ==========================================

import threading
import psutil

_LOCK = threading.Lock()


def listar_procesos(attrs):
    """
    Devuelve una lista de diccionarios planos con los procesos
    activos y los atributos pedidos. Es la ÚNICA forma correcta
    de leer procesos en todo Ada — nunca llames a
    psutil.process_iter() directamente fuera de este archivo.

    Ejemplo:
        procesos = listar_procesos(["name", "memory_percent"])
        for p in procesos:
            nombre = p.get("name") or "desconocido"
    """
    resultado = []
    with _LOCK:
        for proc in psutil.process_iter(attrs):
            try:
                # dict(...) copia la info AHORA, mientras tenemos
                # el candado — así ya no importa lo que hagan los
                # demás hilos después.
                resultado.append(dict(proc.info))
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
    return resultado
