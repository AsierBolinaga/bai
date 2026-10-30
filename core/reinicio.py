"""Protocolo de reinicio: el supervisor conserva la red fuera del namespace."""
ONLINE = 75
OFFLINE = 76


def codigo_modo(modo):
    return ONLINE if modo == "online" else OFFLINE


def modo_reinicio(texto):
    from core.ai_engine import detectar_comando_modo, get_selector
    modo = detectar_comando_modo(texto)
    if modo is None:
        return None
    selector = get_selector()
    if modo == selector.modo:
        return None
    from core import aislamiento
    if (selector.config.get("aislamiento_offline") == "proceso"
            or aislamiento.en_namespace_aislado()):
        return modo
    return None


def aviso_reinicio(modo):
    if modo == "online":
        return ("Guardar y reiniciar en ONLINE para usar tu cuenta de Copilot. "
                "Las próximas preguntas pueden enviar a GitHub Copilot contexto del historial "
                "y de la memoria. No se autoriza acceso a archivos ni ejecución de comandos.")
    return "Guardar y reiniciar en OFFLINE para activar de nuevo el aislamiento de proceso."
