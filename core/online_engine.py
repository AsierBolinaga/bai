"""
Fachada de compatibilidad para el modo ONLINE.

La implementación real vive en core/motors/openai_engine.py y la selección de
motor/modelo en core/model_selector.py. Esta función fuerza el modo online
SIN fallback a motores locales.
"""
from core.model_selector import ModelSelector, SinMotorDisponible


def responder_online(prompted_history, selector=None):
    """Devuelve (ok, texto). Usa únicamente los motores online configurados."""
    propio = selector is None
    selector = selector or ModelSelector()
    try:
        respuesta = selector.responder(prompted_history, modo="online", fallback_offline=False)
        return True, respuesta.texto
    except SinMotorDisponible as e:
        return False, f"[B.A.I] {e}"
    finally:
        if propio:
            selector.cerrar()
