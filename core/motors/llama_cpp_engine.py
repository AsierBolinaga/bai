"""
Motor offline: llama.cpp (llama-cpp-python).

El modelo se carga de forma perezosa en la primera petición y se mantiene en
caché (una instancia por ruta de modelo). Importar este módulo no carga nada.
"""
import atexit
from time import time

from config.motors_config import resolver_ruta
from core.motors.base import MotorError, MotorNoDisponible, libreria_instalada, validar_gguf, validar_mensajes

NOMBRE = "llama_cpp"
TIPO = "offline"

N_CTX_POR_DEFECTO = 2048
MAX_TOKENS_POR_DEFECTO = 256
TEMPERATURE_POR_DEFECTO = 0.7
CHAT_FORMAT_POR_DEFECTO = "llama-2"
STOP_POR_DEFECTO = ["</s>", "###"]

_modelos = {}  # model_path -> instancia Llama


def liberar_modelos():
    """Libera los modelos cargados. Se ejecuta al salir para evitar errores de
    destrucción tardía de llama-cpp-python durante el cierre del intérprete."""
    for modelo in list(_modelos.values()):
        try:
            cerrar = getattr(modelo, "close", None)
            if callable(cerrar):
                cerrar()
        except Exception:
            pass
    _modelos.clear()


atexit.register(liberar_modelos)


def _ruta_modelo(config):
    ruta = (config or {}).get("model_path")
    if not ruta:
        return None
    return resolver_ruta(ruta)


def disponible(config):
    if not libreria_instalada("llama_cpp"):
        return False, "librería 'llama_cpp' no instalada"
    return validar_gguf(_ruta_modelo(config))


def cargar_modelo(config):
    """Carga (o recupera de caché) el modelo indicado en config['model_path']."""
    ok, motivo = disponible(config)
    if not ok:
        raise MotorNoDisponible(motivo)

    ruta = _ruta_modelo(config)
    if ruta in _modelos:
        return _modelos[ruta]

    try:
        from llama_cpp import Llama
    except ImportError as e:
        raise MotorNoDisponible("librería 'llama_cpp' no instalada") from e

    print(f"[B.A.I] Cargando modelo llama.cpp desde: {ruta}")
    try:
        modelo = Llama(
            model_path=ruta,
            n_ctx=config.get("n_ctx", N_CTX_POR_DEFECTO),
            use_mlock=config.get("use_mlock", True),
            verbose=config.get("verbose", False),
            chat_format=config.get("chat_format", CHAT_FORMAT_POR_DEFECTO),
        )
    except Exception as e:
        raise MotorError(f"Error al cargar el modelo llama.cpp: {e}") from e

    print("[B.A.I] Modelo cargado correctamente.")
    _modelos[ruta] = modelo
    return modelo


def responder(messages, config):
    validar_mensajes(messages)
    config = config or {}
    modelo = cargar_modelo(config)

    inicio = time()
    try:
        resultado = modelo.create_chat_completion(
            messages=messages,
            max_tokens=config.get("max_tokens", MAX_TOKENS_POR_DEFECTO),
            temperature=config.get("temperature", TEMPERATURE_POR_DEFECTO),
            stop=config.get("stop", STOP_POR_DEFECTO),
        )
        texto = resultado["choices"][0]["message"]["content"]
    except Exception as e:
        raise MotorError(f"Error al usar llama.cpp: {e}") from e

    if config.get("debug"):
        print(f"[DEBUG] llama.cpp respondió en {time() - inicio:.2f} s")

    if not texto or not texto.strip():
        raise MotorError("llama.cpp devolvió una respuesta vacía.")
    return texto.strip()
