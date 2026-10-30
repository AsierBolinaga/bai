"""Opciones locales de audio, leídas al activar cada función."""
import math
from pathlib import Path

import yaml

RUTA = Path(__file__).resolve().with_name("audio_config.yaml")


def cargar_audio_config():
    with RUTA.open(encoding="utf-8") as archivo:
        opciones = yaml.safe_load(archivo)
    if not isinstance(opciones, dict):
        raise ValueError(f"Configuración de audio inválida: {RUTA}")
    limites = {"silencio_escucha": (0.3, 30), "silencio_reproduccion": (0, 10)}
    for nombre, (minimo, maximo) in limites.items():
        valor = opciones.get(nombre)
        if (isinstance(valor, bool) or not isinstance(valor, (int, float))
                or not math.isfinite(valor) or not minimo <= valor <= maximo):
            raise ValueError(f"Audio: {nombre} debe estar entre {minimo} y {maximo} segundos.")
    if set(opciones) != set(limites):
        raise ValueError("Configuración de audio: hay opciones desconocidas.")
    return opciones
