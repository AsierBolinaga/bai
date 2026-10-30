"""Confirmacion acotada de la terminacion de grupos propios en Linux."""
from pathlib import Path
import logging
import os
import time


def estado_grupo(grupo):
    estados = {}
    for entrada in Path("/proc").iterdir():
        if not entrada.name.isdecimal():
            continue
        try:
            if os.getpgid(int(entrada.name)) != grupo:
                continue
            contenido = (entrada / "stat").read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue
        # comm puede contener espacios e incluso parentesis.
        campos = contenido.rsplit(")", 1)[1].split()
        if int(campos[2]) == grupo:
            estados[int(entrada.name)] = campos[0]
    return estados


def esperar_grupo(grupo, plazo):
    limite = time.monotonic() + plazo
    while True:
        estados = estado_grupo(grupo)
        activos = {pid: estado for pid, estado in estados.items() if estado not in ("Z", "X")}
        if not activos:
            if estados:
                logging.getLogger(__name__).warning(
                    "Grupo %s terminado; quedan entradas sin recoger por su padre: %s", grupo, estados)
            return estados
        if time.monotonic() >= limite:
            raise RuntimeError(f"El grupo {grupo} mantiene procesos activos tras el cierre: {activos}")
        time.sleep(0.01)
