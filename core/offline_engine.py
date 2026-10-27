"""
Fachada de compatibilidad para el modo OFFLINE.

La lista de motores locales y su orden de fallback se definen en
config/motors_config.yaml (sección `offline`); la lógica de selección está en
core/model_selector.py. Los motores se registran en core/motors/registry.py.
"""
from core.model_selector import ModelSelector, SinMotorDisponible


def responder_offline(prompt, context=None, selector=None):
    """
    Devuelve (ok, texto) usando únicamente motores locales.
    `prompt` puede ser un texto (se envuelve como mensaje de usuario) o una
    lista de mensajes estilo chat. `context` (opcional) es un prompt de sistema.
    """
    propio = selector is None
    selector = selector or ModelSelector()
    if isinstance(prompt, str):
        mensajes = []
        if context:
            mensajes.append({"role": "system", "content": context})
        mensajes.append({"role": "user", "content": prompt})
    else:
        mensajes = list(prompt)
    try:
        respuesta = selector.responder(mensajes, modo="offline")
        return True, respuesta.texto
    except SinMotorDisponible as e:
        return False, f"[B.A.I] {e}"
    finally:
        if propio:
            selector.cerrar()  # no dejar la guardia de sesión instalada
