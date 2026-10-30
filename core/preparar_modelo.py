"""Instalación explícita de un modelo conocido, antes del aislamiento offline."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

import requests

from config.motors_config import resolver_ruta
from core.motors.base import MotorError, libreria_instalada

ARCHIVO = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
REVISION = "91cad51170dc346986eccefdc2dd33a9da36ead9"
SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
TAMANO = 1117320736
URL = f"https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/{REVISION}/{ARCHIVO}"


def _verificar(ruta):
    if ruta.stat().st_size != TAMANO:
        raise MotorError(f"Modelo incompleto: {ruta}. Esperaba {TAMANO} bytes. "
                         "Aparta el archivo para volver a descargarlo.")
    with ruta.open("rb") as archivo:
        digest = hashlib.file_digest(archivo, "sha256").hexdigest()
    if digest != SHA256:
        raise MotorError(f"SHA256 incorrecto: {ruta}. Aparta el archivo para volver a descargarlo.")


def preparar_modelo(config, salida=print):
    opciones = config["offline"]["motores"].get(config["offline"]["motor"], {})
    if not opciones.get("descargar_al_arrancar", False):
        return
    if not opciones.get("model_path"):
        raise MotorError("La preparación automática necesita 'model_path'.")
    ruta = Path(resolver_ruta(opciones.get("model_path")))
    if config["offline"]["motor"] != "llama_cpp" or ruta.name != ARCHIVO:
        raise MotorError("La descarga automática sólo admite el modelo Qwen ligero verificado.")
    if not libreria_instalada("llama_cpp"):
        raise MotorError("Falta llama-cpp-python. Instala requirements.txt antes de descargar el modelo.")
    if ruta.exists():
        salida("[B.A.I] Verificando el modelo local...")
        _verificar(ruta)
        return
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(ruta.parent).free < TAMANO + 64 * 1024 * 1024:
        raise MotorError("No hay espacio suficiente para descargar el modelo local (1,12 GB).")
    salida("[B.A.I] Preparación con red: descargo Qwen2.5 1.5B Q4_K_M (1,12 GB) "
           "de Hugging Face. No envío conversaciones. Después activo el modo offline.")
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(dir=ruta.parent, prefix=ruta.name + ".", suffix=".part",
                                         delete=False) as archivo:
            temporal = Path(archivo.name)
            recibidos, porcentaje = 0, -1
            with requests.get(URL, stream=True, timeout=(15, 60)) as respuesta:
                respuesta.raise_for_status()
                for bloque in respuesta.iter_content(chunk_size=1024 * 1024):
                    recibidos += len(bloque)
                    if recibidos > TAMANO:
                        raise MotorError("La descarga supera el tamaño esperado.")
                    archivo.write(bloque)
                    progreso = recibidos * 100 // TAMANO // 5 * 5
                    if progreso != porcentaje:
                        salida(f"[B.A.I] Descargando modelo: {progreso}%")
                        porcentaje = progreso
            archivo.flush()
            os.fsync(archivo.fileno())
        _verificar(temporal)
        os.replace(temporal, ruta)
        salida("[B.A.I] Modelo instalado y SHA256 verificado.")
    except requests.RequestException as error:
        raise MotorError(f"No se pudo descargar el modelo: {error}. "
                         "Reintenta al arrancar con conexión; no se usará la nube como sustituto.") from error
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
