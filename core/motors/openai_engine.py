"""
Motor online: OpenAI (chat completions).

La clave se lee de la variable de entorno OPENAI_API_KEY (o de un fichero .env
mediante python-dotenv). Nunca se guarda en la configuración.
El cliente se crea de forma perezosa: importar este módulo no requiere la
librería `openai` ni la API key, de modo que B.A.I puede arrancar en modo
offline sin credenciales.
"""
import os

from dotenv import load_dotenv

from core.motors.base import MotorError, MotorNoDisponible, libreria_instalada, validar_mensajes

NOMBRE = "openai"
TIPO = "online"
HOST_CONECTIVIDAD = "api.openai.com"
ENV_API_KEY = "OPENAI_API_KEY"

MODELO_POR_DEFECTO = "gpt-4o"
TEMPERATURE_POR_DEFECTO = 0.5
MAX_TOKENS_POR_DEFECTO = 1024

_clientes = {}


def _api_key():
    load_dotenv()
    return os.getenv(ENV_API_KEY)


def disponible(config):
    if not libreria_instalada("openai"):
        return False, "librería 'openai' no instalada"
    if not _api_key():
        return False, f"variable de entorno {ENV_API_KEY} no definida"
    return True, ""


def _cliente():
    api_key = _api_key()
    if not api_key:
        raise MotorNoDisponible(f"variable de entorno {ENV_API_KEY} no definida")
    if api_key not in _clientes:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise MotorNoDisponible("librería 'openai' no instalada") from e
        _clientes[api_key] = OpenAI(api_key=api_key)
    return _clientes[api_key]


def responder(messages, config):
    validar_mensajes(messages)
    config = config or {}
    modelo = config.get("modelo", MODELO_POR_DEFECTO)
    try:
        response = _cliente().chat.completions.create(
            model=modelo,
            messages=messages,
            temperature=config.get("temperature", TEMPERATURE_POR_DEFECTO),
            max_tokens=config.get("max_tokens", MAX_TOKENS_POR_DEFECTO),
        )
        texto = response.choices[0].message.content
    except MotorError:
        raise
    except Exception as e:
        raise MotorError(f"Error al contactar con OpenAI ({modelo}): {e}") from e

    if not texto or not texto.strip():
        raise MotorError(f"OpenAI ({modelo}) devolvió una respuesta vacía.")
    return texto.strip()
