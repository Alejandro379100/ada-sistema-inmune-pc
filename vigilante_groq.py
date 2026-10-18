# ==========================================
#   vigilante_groq.py v1.0
#   Su único trabajo: vigilar que los modelos
#   que usa Ada (GROQ_MODELO_PRINCIPAL y
#   GROQ_MODELO_RAPIDO) sigan activos en Groq --
#   para no depender solo de leer el correo de
#   Groq a tiempo cuando descontinúan un modelo.
# ==========================================

import logging

from config import GROQ_MODELO_PRINCIPAL, GROQ_MODELO_RAPIDO


def verificar_modelos_activos() -> str:
    """
    Consulta la lista real de modelos activos en Groq
    (GET /v1/models, vía el SDK ya configurado en ia.py) y confirma
    que GROQ_MODELO_PRINCIPAL y GROQ_MODELO_RAPIDO sigan en esa lista.

    Defensivo a propósito: si Groq está caído, sin internet, o la
    API key falla, esto NO debe generar una alerta -- sería un falso
    positivo peor que no avisar nada ese ciclo (el próximo chequeo,
    unos días después, ya lo confirma bien). Solo alerta cuando la
    respuesta de Groq llegó bien Y falta alguno de los dos modelos.

    Retorna un string con el tag [VIGILANTE GROQ] (mismo criterio que
    vigilante_tecnologico, fácil de encontrar en el log) si falta
    alguno de los dos modelos, o "" si todo sigue activo o no se pudo
    confirmar nada esta vez.
    """
    import ia  # import local -- mismo patrón que el resto del proyecto,
               # evita ciclos de import al cargar el módulo

    if not ia.GROQ_ACTIVO or ia.groq_client is None:
        return ""  # sin conexión a Groq ahora mismo -- no es una alerta,
                   # es simplemente no poder confirmar nada este ciclo

    try:
        respuesta = ia.groq_client.models.list()
        ids_activos = {m.id for m in respuesta.data}
    except Exception as e:
        logging.warning(f"[VIGILANTE GROQ] No pude consultar la lista de modelos: {type(e).__name__}: {e}")
        return ""

    faltantes = [
        modelo for modelo in (GROQ_MODELO_PRINCIPAL, GROQ_MODELO_RAPIDO)
        if modelo not in ids_activos
    ]

    if not faltantes:
        return ""  # los dos modelos siguen activos -- todo bien, sin ruido

    voz = (
        f"[VIGILANTE GROQ] Alerta: {', '.join(faltantes)} ya no aparece(n) en la lista "
        f"de modelos activos de Groq -- puede que lo/los hayan descontinuado. Revisá "
        f"https://console.groq.com/docs/deprecations para confirmar y elegir el "
        f"reemplazo recomendado antes de que las llamadas empiecen a fallar."
    )
    # logging.warning (no .info) a propósito -- mismo criterio que
    # vigilante_tecnologico, esto necesita destacar en el log.
    logging.warning(voz)
    return voz
