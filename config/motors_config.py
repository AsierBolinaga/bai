"""
Carga y normalización de la configuración de motores (config/motors_config.yaml).

Expone:
  - PROJECT_ROOT / CONFIG_PATH : rutas absolutas (independientes del CWD).
  - cargar_motors_config(path)  : devuelve la configuración normalizada y validada.
  - resolver_ruta(ruta)         : convierte rutas relativas en absolutas respecto
                                  a la raíz del proyecto.
  - motors_config               : configuración cargada al importar (compatibilidad).
"""
import copy
import os
import warnings
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "motors_config.yaml"

MODOS_VALIDOS = ("online", "offline")
PRIORIDADES_VALIDAS = ("local", "online")
AISLAMIENTOS_VALIDOS = ("proceso", "python")

# Sobrescrituras en tiempo de ejecución (opciones de línea de comandos de bai.py).
# Claves admitidas: "modo_por_defecto", "aislamiento_offline".
SOBRESCRITURAS = {}

# Opciones de motor que habilitarían acceso a red. En la sección offline se
# fuerzan a False sea cual sea el YAML (los adaptadores también las ignoran).
OPCIONES_RED_OFFLINE = ("allow_download",)

# Valores por defecto de cada sección. Se completan con lo que haya en el YAML.
DEFAULTS = {
    "modo_por_defecto": "offline",
    "aislamiento_offline": "proceso",
    "mostrar_motor": True,
    "online": {
        "motor": "openai",
        "fallback": [],
        "prioridad": "local",
        "fallback_offline": True,
        "max_mensajes_contexto": None,
        "motores": {"openai": {"modelo": "gpt-4o"}},
    },
    "offline": {
        "motor": "llama_cpp",
        "fallback": [],
        "max_mensajes_contexto": None,
        "motores": {
            "llama_cpp": {"model_path": "models/mistral-7b-instruct-v0.1.Q4_0.gguf"}
        },
    },
}


class ConfigError(ValueError):
    """Configuración de motores inválida."""


def resolver_ruta(ruta):
    """Devuelve `ruta` absoluta; las rutas relativas se resuelven desde PROJECT_ROOT."""
    if ruta is None:
        return None
    ruta = os.path.expanduser(str(ruta))
    if os.path.isabs(ruta):
        return ruta
    return str(PROJECT_ROOT / ruta)


def _normalizar_legacy(raw):
    """
    Admite el formato antiguo del YAML (claves planas):
        motor_offline / motor : nombre del motor local
        model_path / ruta_modelo : ruta del modelo
        modelo : nombre del modelo
    y lo convierte a la estructura por secciones.
    """
    if "offline" in raw or "online" in raw:
        return raw

    motor = raw.get("motor_offline") or raw.get("motor")
    if not motor:
        return raw

    modelo = raw.get("modelo")
    model_path = raw.get("model_path") or raw.get("ruta_modelo")
    if not model_path and modelo:
        model_path = f"models/{modelo}.gguf"

    motor_cfg = {}
    if model_path:
        motor_cfg["model_path"] = model_path
    if modelo:
        motor_cfg["modelo"] = modelo

    nuevo = {k: v for k, v in raw.items()
             if k not in ("motor_offline", "motor", "modelo", "model_path", "ruta_modelo")}
    nuevo["offline"] = {"motor": motor, "motores": {motor: motor_cfg}}
    return nuevo


def _fusionar_seccion(defaults, valores, nombre):
    if valores is None:
        valores = {}
    if not isinstance(valores, dict):
        raise ConfigError(f"La sección '{nombre}' debe ser un diccionario.")
    seccion = copy.deepcopy(defaults)
    for k, v in valores.items():
        if k == "motores":
            continue
        seccion[k] = v
    # Los motores del YAML sustituyen a los de por defecto (no se mezclan).
    if "motores" in valores and valores["motores"] is not None:
        if not isinstance(valores["motores"], dict):
            raise ConfigError(f"'{nombre}.motores' debe ser un diccionario.")
        seccion["motores"] = {
            n: (dict(c) if isinstance(c, dict) else {}) for n, c in valores["motores"].items()
        }
    return seccion


def validar_config(config):
    """Comprueba coherencia mínima de la configuración normalizada."""
    modo = config.get("modo_por_defecto")
    if modo not in MODOS_VALIDOS:
        raise ConfigError(
            f"'modo_por_defecto' debe ser uno de {MODOS_VALIDOS}, recibido: {modo!r}"
        )
    aislamiento = config.get("aislamiento_offline")
    if aislamiento not in AISLAMIENTOS_VALIDOS:
        raise ConfigError(
            f"'aislamiento_offline' debe ser uno de {AISLAMIENTOS_VALIDOS}, recibido: {aislamiento!r}"
        )
    for nombre in MODOS_VALIDOS:
        seccion = config[nombre]
        motor = seccion.get("motor")
        if not motor:
            raise ConfigError(f"La sección '{nombre}' necesita la clave 'motor'.")
        fallback = seccion.get("fallback") or []
        if isinstance(fallback, str):
            fallback = [fallback]
        if not isinstance(fallback, list):
            raise ConfigError(f"'{nombre}.fallback' debe ser una lista.")
        seccion["fallback"] = [str(m) for m in fallback]
        # Todo motor referenciado debe tener entrada en 'motores' (aunque sea vacía)
        for m in [motor] + seccion["fallback"]:
            seccion["motores"].setdefault(m, {})
        mx = seccion.get("max_mensajes_contexto")
        if mx is not None and (not isinstance(mx, int) or mx <= 0):
            raise ConfigError(f"'{nombre}.max_mensajes_contexto' debe ser entero > 0.")
        for identificador, opciones in seccion["motores"].items():
            if "descargar_al_arrancar" in opciones and not isinstance(opciones["descargar_al_arrancar"], bool):
                raise ConfigError(f"'{nombre}.motores.{identificador}.descargar_al_arrancar' debe ser booleano.")
            for campo in ("n_ctx", "max_tokens", "timeout"):
                if campo in opciones:
                    valor = opciones[campo]
                    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
                        raise ConfigError(f"'{nombre}.motores.{identificador}.{campo}' debe ser entero > 0.")
            if "n_ctx" in opciones and "max_tokens" in opciones:
                if opciones["max_tokens"] >= opciones["n_ctx"]:
                    raise ConfigError(f"'{nombre}.motores.{identificador}': max_tokens debe ser menor que n_ctx.")

    prioridad = str(config["online"].get("prioridad", "local")).lower()
    if prioridad not in PRIORIDADES_VALIDAS:
        raise ConfigError(f"'online.prioridad' debe ser uno de {PRIORIDADES_VALIDAS}, recibido: {prioridad!r}")
    config["online"]["prioridad"] = prioridad

    # Garantía offline: ninguna opción de red puede quedar activa en motores locales.
    for motor, cfg in config["offline"]["motores"].items():
        for opcion in OPCIONES_RED_OFFLINE:
            if cfg.get(opcion):
                warnings.warn(
                    f"offline.motores.{motor}.{opcion}=true ignorado: los motores offline "
                    f"nunca acceden a servicios externos.", stacklevel=2)
                cfg[opcion] = False
    return config


def cargar_motors_config(path=None):
    """
    Lee el YAML (por defecto CONFIG_PATH), lo normaliza con los valores por
    defecto y lo valida. Devuelve siempre un dict con las claves
    'modo_por_defecto', 'online' y 'offline'.
    """
    path = Path(path) if path else CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"No se encuentra el fichero de configuración: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ConfigError("El fichero de configuración debe contener un diccionario.")

    raw = _normalizar_legacy(raw)
    for clave in ("modo_por_defecto", "aislamiento_offline"):
        if clave in SOBRESCRITURAS:
            raw[clave] = SOBRESCRITURAS[clave]

    config = {
        "modo_por_defecto": str(raw.get("modo_por_defecto", DEFAULTS["modo_por_defecto"])).lower(),
        "aislamiento_offline": str(raw.get("aislamiento_offline", DEFAULTS["aislamiento_offline"])).lower(),
        "mostrar_motor": bool(raw.get("mostrar_motor", DEFAULTS["mostrar_motor"])),
        "online": _fusionar_seccion(DEFAULTS["online"], raw.get("online"), "online"),
        "offline": _fusionar_seccion(DEFAULTS["offline"], raw.get("offline"), "offline"),
    }
    return validar_config(config)


# Compatibilidad: configuración cargada al importar el módulo.
motors_config = cargar_motors_config()
