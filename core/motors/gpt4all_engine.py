"""
Motor offline: GPT4All.

`model_path` apunta al fichero .gguf (misma convención que llama_cpp); GPT4All
recibe el directorio y el nombre de fichero por separado. El modelo se carga de
forma perezosa y se cachea por ruta.
"""
import os

from config.motors_config import resolver_ruta
from core.motors.base import (MotorError, MotorNoDisponible, libreria_instalada, mensajes_a_prompt,
                              separar_sistema, validar_gguf, validar_mensajes)

NOMBRE = "gpt4all"
TIPO = "offline"

N_CTX_POR_DEFECTO = 2048
# Plantilla de prompt para modelos Llama-2 / Mistral-Instruct ({0} = mensaje del usuario).
# Sin allow_download GPT4All no puede consultar la plantilla del modelo en
# gpt4all.io, así que se indica explícitamente (configurable con 'prompt_template').
PROMPT_TEMPLATE_POR_DEFECTO = "[INST] {0} [/INST]"

_modelos = {}  # model_path -> instancia GPT4All


def _ruta_modelo(config):
    config = config or {}
    ruta = config.get("model_path") or config.get("ruta_modelo")
    if not ruta and config.get("modelo"):
        ruta = f"models/{config['modelo']}"
        if not ruta.endswith(".gguf"):
            ruta += ".gguf"
    if not ruta:
        return None
    return resolver_ruta(ruta)


def disponible(config):
    if not libreria_instalada("gpt4all"):
        return False, "librería 'gpt4all' no instalada"
    return validar_gguf(_ruta_modelo(config))


def cargar_modelo(config):
    ok, motivo = disponible(config)
    if not ok:
        raise MotorNoDisponible(motivo)

    ruta = _ruta_modelo(config)
    if ruta in _modelos:
        return _modelos[ruta]

    try:
        from gpt4all import GPT4All
    except ImportError as e:
        raise MotorNoDisponible("librería 'gpt4all' no instalada") from e

    if config.get("allow_download"):
        print("[B.A.I] Aviso: 'allow_download' ignorado en el motor gpt4all: los motores "
              "offline nunca descargan ni contactan con servicios externos.")

    try:
        # allow_download=False SIEMPRE (no configurable): con el valor por defecto
        # de GPT4All (True) se consulta https://gpt4all.io aunque el modelo ya
        # exista en disco, y sin red la carga falla.
        modelo = GPT4All(
            model_name=os.path.basename(ruta),
            model_path=os.path.dirname(ruta),
            allow_download=False,
            n_ctx=config.get("n_ctx", N_CTX_POR_DEFECTO),
            verbose=bool(config.get("verbose", False)),
        )
    except Exception as e:
        raise MotorError(f"Error al cargar el modelo GPT4All: {e}") from e

    _modelos[ruta] = modelo
    return modelo


def responder(messages, config):
    validar_mensajes(messages)
    config = config or {}
    modelo = cargar_modelo(config)

    sistema, turnos = separar_sistema(messages)
    # El historial (user/assistant) se aplana en texto; el sistema va aparte.
    prompt = mensajes_a_prompt(turnos) if turnos else ""

    kwargs = {}
    if "max_tokens" in config:
        kwargs["max_tokens"] = config["max_tokens"]
    if "temperature" in config:
        kwargs["temp"] = config["temperature"]

    sesion = {"prompt_template": config.get("prompt_template", PROMPT_TEMPLATE_POR_DEFECTO)}
    if sistema:
        sesion["system_prompt"] = sistema

    try:
        with modelo.chat_session(**sesion):
            texto = modelo.generate(prompt, **kwargs)
    except Exception as e:
        raise MotorError(f"Error al generar respuesta offline con GPT4All: {e}") from e

    if not texto or not texto.strip():
        raise MotorError("GPT4All devolvió una respuesta vacía.")
    return texto.strip()
