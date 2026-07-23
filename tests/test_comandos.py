# ==========================================
#   test_comandos.py
#   Prueba el cerebro de órdenes: el bug real de
#   reintentos de contraseña, y el comando nuevo
#   para revisar decisiones del médico autónomo.
# ==========================================


def test_password_incorrecta_no_cancela_la_accion_al_primer_intento(
    db_temporal, estado_limpio_comandos, monkeypatch
):
    """
    Bug real: antes, un solo error de contraseña cancelaba la acción
    pendiente de inmediato, aunque seguridad.py permite 3 intentos
    antes de bloquear la pantalla.
    """
    import comandos
    import seguridad

    monkeypatch.setattr(seguridad, "verificar_contrasena", lambda clave: (False, False))
    monkeypatch.setattr(seguridad, "intentos_restantes", lambda: 2)

    comandos._estado["esperando_password"] = True
    comandos._estado["accion_pendiente"] = "apagar"
    comandos._estado["accion_pendiente_data"] = None

    respuesta = comandos.procesar_orden("clave-incorrecta", lambda texto, prioridad=0: None)

    assert comandos._estado["esperando_password"] is True, \
        "No debería cancelar esperando_password tras un solo intento fallido"
    assert comandos._estado["accion_pendiente"] == "apagar", \
        "No debería perder la acción pendiente tras un solo intento fallido"
    assert "2 intentos" in respuesta


def test_password_incorrecta_demasiadas_veces_si_cancela(
    db_temporal, estado_limpio_comandos, monkeypatch
):
    """Cuando seguridad.py reporta bloqueo, ahí sí se cancela todo."""
    import comandos
    import seguridad

    monkeypatch.setattr(seguridad, "verificar_contrasena", lambda clave: (False, True))

    comandos._estado["esperando_password"] = True
    comandos._estado["accion_pendiente"] = "apagar"

    respuesta = comandos.procesar_orden("clave-incorrecta", lambda texto, prioridad=0: None)

    assert comandos._estado["esperando_password"] is False
    assert comandos._estado["accion_pendiente"] is None
    assert "bloque" in respuesta.lower()


def test_comando_decisiones_medico(db_temporal, estado_limpio_comandos):
    """El comando 'que has decidido' debe mostrar el historial real
    de decisiones del médico autónomo."""
    import comandos

    db_temporal.registrar_decision_medico_ia(
        "limpiar_winsxs", "bajo", "prueba", ejecutada=True, resultado="liberado 1GB"
    )

    respuesta = comandos.procesar_orden("que has decidido", lambda texto, prioridad=0: None)
    assert "limpiar_winsxs" in respuesta


def test_comando_decisiones_medico_sin_historial(db_temporal, estado_limpio_comandos):
    """Si nunca ha decidido nada, debe decirlo con claridad, no fallar."""
    import comandos

    respuesta = comandos.procesar_orden("que has decidido", lambda texto, prioridad=0: None)
    assert "no he tomado" in respuesta.lower() or "ninguna decisión" in respuesta.lower()


def test_comando_cambios_tecnologicos_reporta_pendientes(db_temporal, estado_limpio_comandos, monkeypatch):
    """El comando 'revisa actualizaciones' debe mostrar los cambios
    tecnológicos pendientes de revisar, sin inventar ninguno nuevo si
    la versión de Windows no cambió desde la última vez."""
    import comandos
    import vigilante_tecnologico

    # Sin cambio de versión real esta vez -- el comando debe caer al
    # historial de pendientes en vez de reportar un cambio inventado.
    monkeypatch.setattr(vigilante_tecnologico, "verificar_actualizacion_os", lambda preguntar_groq_fn=None: "")

    db_temporal.registrar_cambio_tecnologico(
        tipo="actualizacion_windows", version_anterior="22631.3527", version_nueva="22631.3800",
        prioridad="media", razon="parche acumulativo", modulos_afectados=["auto_reparador.py"],
    )

    respuesta = comandos.procesar_orden("revisa actualizaciones", lambda texto, prioridad=0: None)

    assert "22631.3527" in respuesta
    assert "22631.3800" in respuesta


def test_comando_cambios_tecnologicos_sin_pendientes(db_temporal, estado_limpio_comandos, monkeypatch):
    """Sin ningún cambio pendiente, debe decirlo claro, no fallar ni inventar uno."""
    import comandos
    import vigilante_tecnologico

    monkeypatch.setattr(vigilante_tecnologico, "verificar_actualizacion_os", lambda preguntar_groq_fn=None: "")

    respuesta = comandos.procesar_orden("revisa actualizaciones", lambda texto, prioridad=0: None)

    assert "no hay cambios" in respuesta.lower()


# ==========================================
#   Bug real: "si" como substring confirmaba
#   acciones sin que el usuario dijera que sí.
#   Pasó de verdad: "como te sientes" cerró un
#   proceso porque "sientes" empieza con "si".
# ==========================================

def test_contiene_confirmacion_no_confunde_palabras_con_si_adentro():
    import comandos
    assert comandos._contiene_confirmacion("como te sientes", ["si"]) is False
    assert comandos._contiene_confirmacion("el sistema esta lento", ["si"]) is False
    assert comandos._contiene_confirmacion("eso es positivo", ["si"]) is False


def test_contiene_confirmacion_reconoce_si_como_palabra_completa():
    import comandos
    assert comandos._contiene_confirmacion("si", ["si"]) is True
    assert comandos._contiene_confirmacion("si, hazlo", ["si"]) is True
    assert comandos._contiene_confirmacion("dale si por favor", ["si"]) is True


def test_contiene_confirmacion_frases_largas_siguen_funcionando_como_antes():
    """Las frases de más de una palabra son lo bastante específicas
    como para seguir comparándose por substring sin riesgo real."""
    import comandos
    assert comandos._contiene_confirmacion("si, confirmar apagado ya", ["confirmar apagado"]) is True


def test_pregunta_inocente_ya_no_cierra_el_proceso_pendiente(estado_limpio_comandos, monkeypatch):
    """
    El bug real, reproducido exactamente como pasó: con un proceso
    esperando confirmación, preguntar 'como te sientes' NO debería
    cerrarlo. Antes esto ejecutaba taskkill de verdad.
    """
    import comandos

    llamadas_taskkill = {"veces": 0}
    monkeypatch.setattr(comandos.subprocess, "run",
                         lambda *a, **kw: llamadas_taskkill.update(veces=llamadas_taskkill["veces"] + 1))
    monkeypatch.setattr(comandos, "es_proceso_critico", lambda nombre: False)

    comandos._estado["esperando_confirmar_proceso"] = True
    comandos._estado["proceso_pendiente"] = "WhatsApp.Root.exe"

    resultado = comandos.procesar_orden("como te sientes", hablar=lambda *a, **kw: None)

    assert llamadas_taskkill["veces"] == 0, "No debería haber cerrado el proceso"
    assert "no lo termino" in resultado.lower()
    # Y el estado pendiente ya se limpió -- la siguiente pregunta de
    # verdad ("cómo te sientes") se procesa normal, no queda pegada
    # esperando una confirmación que nunca se dio.
    assert comandos._estado["esperando_confirmar_proceso"] is False


def test_confirmacion_real_si_cierra_el_proceso(estado_limpio_comandos, monkeypatch):
    """Contraparte: un 'si' de verdad sí debe confirmar, como
    siempre — el arreglo no debería volver esto más estricto de lo
    necesario."""
    import comandos

    llamadas_taskkill = {"veces": 0}
    monkeypatch.setattr(comandos.subprocess, "run",
                         lambda *a, **kw: llamadas_taskkill.update(veces=llamadas_taskkill["veces"] + 1))
    monkeypatch.setattr(comandos, "es_proceso_critico", lambda nombre: False)

    comandos._estado["esperando_confirmar_proceso"] = True
    comandos._estado["proceso_pendiente"] = "WhatsApp.Root.exe"

    resultado = comandos.procesar_orden("si", hablar=lambda *a, **kw: None)

    assert llamadas_taskkill["veces"] == 1
    assert "terminado" in resultado.lower()
