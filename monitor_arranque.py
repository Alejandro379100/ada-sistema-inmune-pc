# ==========================================
#   monitor_arranque.py v1.1
#   Ada vigila el arranque de Windows
#   Detecta programas nuevos sin permiso
# ==========================================

import winreg
import json
import os
import logging

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT    = os.path.join(BASE_DIR, "privado", "arranque_snapshot.json")

CLAVES_ARRANQUE = [
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
]

IGNORAR = [
    "ada", "iniciar_ada", "onedrive", "securityhealth", "screenrec", "adobe", "microsoft", "windows", "security",
    "realtek", "intel", "lenovo", "teams", "discord"
]


def _texto_seguro(valor) -> str:
    """
    Normaliza cualquier valor de registro a texto antes de buscarle
    coincidencias. La mayoría de las entradas de Run son REG_SZ o
    REG_EXPAND_SZ (ya texto), pero el registro también permite
    REG_DWORD (int) o REG_BINARY (bytes) -- si alguna vez aparece una
    entrada así, `valor.lower()` tiraba AttributeError. sistema.py
    atrapa esa excepción con su propio try/except (no tumba el
    scheduler), pero la snapshot nunca llegaba a guardarse esa vuelta
    -- fallaba en silencio y se repetía cada 6h. Con str(valor) esto
    ya no puede pasar, para ningún tipo que devuelva winreg.
    """
    try:
        return str(valor)
    except Exception:
        return ""


def _leer_arranque() -> dict:
    resultado = {}
    for hive, clave in CLAVES_ARRANQUE:
        try:
            reg = winreg.OpenKey(hive, clave, 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    nombre, valor, _ = winreg.EnumValue(reg, i)
                    resultado[nombre.lower()] = valor
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(reg)
        except Exception:
            pass
    return resultado

def _cargar_snapshot() -> dict:
    try:
        if os.path.exists(SNAPSHOT):
            with open(SNAPSHOT, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _guardar_snapshot(datos: dict):
    try:
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        with open(SNAPSHOT, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"[ARRANQUE] No pude guardar snapshot: {e}")

def inicializar():
    """Llama esto una vez al arrancar Ada para crear el snapshot base."""
    actual = _leer_arranque()
    if not os.path.exists(SNAPSHOT):
        _guardar_snapshot(actual)
        logging.info(f"[ARRANQUE] Snapshot inicial creado con {len(actual)} entradas.")

def verificar_arranque() -> str:
    """
    Compara el arranque actual con el snapshot.
    Retorna alerta si hay algo nuevo sospechoso.
    """
    actual   = _leer_arranque()
    snapshot = _cargar_snapshot()

    nuevos = {
        k: v for k, v in actual.items()
        if k not in snapshot
        and not any(ig in k.lower() or ig in _texto_seguro(v).lower() for ig in IGNORAR)
    }

    eliminados = {
        k: v for k, v in snapshot.items()
        if k not in actual
    }

    # Actualizar snapshot
    _guardar_snapshot(actual)

    if not nuevos and not eliminados:
        return ""

    msg = ""
    if nuevos:
        nombres = ", ".join(list(nuevos.keys())[:3])
        msg += (
            f"Alerta. Detecte {len(nuevos)} programa nuevo en el arranque de Windows: "
            f"{nombres}. Puede ser inofensivo o puede ser malware. "
            f"Di revisar arranque para que lo analice con Groq."
        )
        logging.warning(f"[ARRANQUE] Nuevos: {nuevos}")

    if eliminados:
        nombres = ", ".join(list(eliminados.keys())[:2])
        msg += f" Tambien desaparecieron {len(eliminados)} entradas del arranque: {nombres}."
        logging.info(f"[ARRANQUE] Eliminados: {eliminados}")

    return msg.strip()

def analizar_con_groq(preguntar_groq_fn) -> str:
    """Pide a Groq que analice las entradas del arranque."""
    actual = _leer_arranque()
    if not actual:
        return "No encontre entradas en el arranque de Windows."

    # Filtrar lo que ya sabemos que es seguro (Ada misma, OneDrive,
    # antivirus, drivers de fabricante, etc.) antes de mandarlo a
    # Groq. Sin este filtro, Groq analiza "ada" como si fuera un
    # desconocido y la marca sospechosa — literalmente Ada
    # sospechando de si misma.
    relevantes = {
        k: v for k, v in actual.items()
        if not any(ig in k.lower() or ig in _texto_seguro(v).lower() for ig in IGNORAR)
    }

    if not relevantes:
        return (
            "Revise el arranque de Windows: las entradas que hay son todas "
            "conocidas y seguras (Ada, OneDrive, antivirus, drivers). Nada sospechoso."
        )

    lista = "\n".join([f"- {k}: {_texto_seguro(v)[:80]}" for k, v in list(relevantes.items())[:15]])
    prompt = (
        f"Analiza estas entradas del arranque de Windows de un PC de programacion "
        f"con Windows 11, i5-8350U, 16GB RAM. Ya se filtraron las entradas conocidas "
        f"y seguras (Ada, OneDrive, antivirus, drivers de fabricante), asi que estas "
        f"son las que quedan por revisar. Di cuales son seguras, cuales son "
        f"innecesarias y cuales son sospechosas. Se muy conciso:\n{lista}"
    )
    return preguntar_groq_fn(prompt)
