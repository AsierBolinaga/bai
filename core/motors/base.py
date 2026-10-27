"""
Contrato común de los motores LLM de B.A.I.

Todo módulo de motor (core/motors/<nombre>_engine.py) debe exponer:

    NOMBRE = "<nombre>"            # identificador usado en motors_config.yaml
    TIPO   = "online" | "offline"

    def disponible(config) -> tuple[bool, str]:
        # Comprueba, SIN cargar el modelo, si el motor puede usarse:
        # librería instalada, fichero de modelo presente, API key definida...
        # Devuelve (True, "") o (False, "motivo").

    def responder(messages, config) -> str:
        # Genera una respuesta a partir de la lista de mensajes estilo chat
        # [{"role": "system"|"user"|"assistant", "content": str}, ...].
        # Debe lanzar MotorError (o una subclase) si no puede responder,
        # NUNCA devolver el error como texto.

Este módulo ofrece además utilidades para motores que sólo aceptan texto plano.
"""
import importlib.util
import os
import struct
import sys


class MotorError(Exception):
    """El motor no ha podido generar una respuesta."""


class MotorNoDisponible(MotorError):
    """El motor no puede usarse (no instalado, sin modelo, sin credenciales, sin conexión)."""


ROLES_VALIDOS = ("system", "user", "assistant")


def libreria_instalada(nombre):
    """True si el paquete `nombre` puede importarse (sin importarlo realmente)."""
    if nombre in sys.modules:
        return sys.modules[nombre] is not None
    try:
        return importlib.util.find_spec(nombre) is not None
    except (ImportError, ValueError):
        return False


GGUF_MAGIC = b"GGUF"
GGUF_VERSIONES = (1, 2, 3)


def validar_gguf(ruta):
    """
    Comprueba, sin cargar el modelo, que `ruta` es un fichero GGUF plausible:
    existe, es un fichero regular, empieza por la firma 'GGUF' y declara una
    versión conocida. Detecta rutas equivocadas y descargas truncadas/corruptas
    antes de intentar cargar gigabytes en memoria.
    Devuelve (True, "") o (False, motivo).
    """
    if not ruta:
        return False, "falta 'model_path' en la configuración"
    if not os.path.exists(ruta):
        return False, f"no se encuentra el modelo en {ruta}"
    if not os.path.isfile(ruta):
        return False, f"la ruta del modelo no es un fichero: {ruta}"
    try:
        with open(ruta, "rb") as f:
            cabecera = f.read(8)
    except OSError as e:
        return False, f"no se puede leer el modelo {ruta}: {e}"
    if len(cabecera) < 8 or cabecera[:4] != GGUF_MAGIC:
        return False, f"el fichero no tiene formato GGUF (cabecera inválida): {ruta}"
    version = struct.unpack("<I", cabecera[4:8])[0]
    if version not in GGUF_VERSIONES:
        return False, f"versión GGUF desconocida ({version}) en {ruta}"
    return True, ""


def validar_mensajes(messages):
    """Valida la estructura de la lista de mensajes. Lanza ValueError si es incorrecta."""
    if not isinstance(messages, list) or not messages:
        raise ValueError("Se esperaba una lista de mensajes no vacía.")
    for m in messages:
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            raise ValueError(f"Mensaje mal formado: {m!r}")
        if m["role"] not in ROLES_VALIDOS:
            raise ValueError(f"Rol desconocido en mensaje: {m['role']!r}")
    return messages


def separar_sistema(messages):
    """
    Separa los mensajes 'system' del resto.
    Devuelve (texto_sistema, turnos) donde texto_sistema concatena todos los
    mensajes de sistema y turnos es la lista de mensajes user/assistant.
    """
    sistema = [m["content"] for m in messages if m["role"] == "system" and m["content"]]
    turnos = [m for m in messages if m["role"] != "system"]
    return "\n\n".join(sistema), turnos


def mensajes_a_prompt(messages, etiqueta_usuario="Usuario", etiqueta_asistente="B.A.I"):
    """
    Convierte la lista de mensajes en un prompt de texto plano para motores
    que no aceptan formato chat. Termina con la etiqueta del asistente para
    que el modelo continúe la conversación.
    """
    sistema, turnos = separar_sistema(messages)
    partes = []
    if sistema:
        partes.append(sistema)
    for m in turnos:
        etiqueta = etiqueta_usuario if m["role"] == "user" else etiqueta_asistente
        partes.append(f"{etiqueta}: {m['content']}")
    partes.append(f"{etiqueta_asistente}:")
    return "\n".join(partes)


def recortar_mensajes(messages, max_mensajes):
    """
    Limita el número de mensajes NO 'system' a los `max_mensajes` más recientes,
    conservando todos los mensajes de sistema en su posición relativa.
    Si max_mensajes es None devuelve la lista sin cambios.
    """
    if max_mensajes is None:
        return list(messages)
    no_sistema = [i for i, m in enumerate(messages) if m["role"] != "system"]
    if len(no_sistema) <= max_mensajes:
        return list(messages)
    descartar = set(no_sistema[: len(no_sistema) - max_mensajes])
    return [m for i, m in enumerate(messages) if i not in descartar]
