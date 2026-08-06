# ==========================================
#   manual_playbook.py v1.0
#   Runbook fijo: comando PowerShell (admin)
#   exacto para cada acción que Ada detecta
#   pero no puede o no está autorizada a
#   ejecutar sola -- Ada nunca inventa un
#   comando, solo cita uno de esta lista.
# ==========================================

# Uno por acción del CATALOGO_ACCIONES de auto_reparador.py. comando_admin
# es texto fijo, pensado para copiar y pegar directo en PowerShell como
# Administrador -- no se genera con IA ni se arma en tiempo de ejecución,
# para que nunca cambie sin que un humano lo revise acá primero.
PLAYBOOK_MANUAL = {
    "reparar_archivos_sistema": {
        "comando_admin": "sfc /scannow",
        "que_resuelve": ("Corrupción de archivos de sistema. Ada la detecta pero necesita "
                          "permisos de administrador que no tiene por diseño."),
    },
    "limpiar_winsxs": {
        "comando_admin": "Dism /Online /Cleanup-Image /StartComponentCleanup /ResetBase",
        "que_resuelve": ("Limpieza de componentes de Windows. Es lo mismo que Ada ya intenta "
                          "sola -- correrlo manual con administrador puede tener más permisos."),
    },
    "reparar_red": {
        "comando_admin": "netsh winsock reset && netsh int ip reset && ipconfig /flushdns",
        "que_resuelve": "Problemas de red/conectividad. Riesgo alto -- Ada nunca la ejecuta sola.",
    },
    "actualizar_con_winget": {
        "comando_admin": "winget upgrade --all",
        "que_resuelve": "Software desactualizado. Riesgo alto -- Ada nunca actualiza todo sin confirmación.",
    },
}


def texto_sugerido(accion: str) -> str:
    """
    Fragmento listo para concatenar en una notificación o mensaje hablado:
    ' Comando (PowerShell como Administrador): <comando>'. Cadena vacía si
    la acción no tiene un comando manual documentado -- así el llamador
    puede sumarlo directo al mensaje sin chequear None antes.
    """
    entrada = PLAYBOOK_MANUAL.get(accion)
    if not entrada:
        return ""
    return f" Comando (PowerShell como Administrador): {entrada['comando_admin']}"
