"""
Registro de motores disponibles.

Asocia el nombre usado en motors_config.yaml con el módulo Python que lo
implementa. Los módulos se importan de forma perezosa, y nunca deben importar
librerías pesadas (llama_cpp, gpt4all, openai...) a nivel de módulo, para que
registrar/inspeccionar un motor no requiera tenerlas instaladas.

Para añadir un motor nuevo:
  1. Crear core/motors/<nombre>_engine.py implementando el contrato de base.py
  2. Añadirlo a MOTORES (o llamar a registrar_motor en tiempo de ejecución)
  3. Configurarlo en motors_config.yaml
"""
import importlib

from core.motors.base import MotorNoDisponible

MOTORES = {
    # online
    "openai": "core.motors.openai_engine",
    "copilot": "core.motors.copilot_engine",
    # offline
    "llama_cpp": "core.motors.llama_cpp_engine",
    "gpt4all": "core.motors.gpt4all_engine",
    "ollama": "core.motors.ollama_engine",
}

_INTERFAZ_REQUERIDA = ("NOMBRE", "TIPO", "disponible", "responder")


def registrar_motor(nombre, module_path):
    """Registra (o sustituye) un motor en tiempo de ejecución."""
    MOTORES[nombre] = module_path


def motores_registrados():
    return dict(MOTORES)


def obtener_motor(nombre):
    """
    Importa y devuelve el módulo del motor `nombre`.
    Lanza MotorNoDisponible si no está registrado, no se puede importar o
    no implementa el contrato mínimo (p. ej. un motor todavía en TODO).
    """
    if nombre not in MOTORES:
        raise MotorNoDisponible(
            f"Motor '{nombre}' no registrado. Disponibles: {', '.join(sorted(MOTORES))}"
        )
    try:
        modulo = importlib.import_module(MOTORES[nombre])
    except Exception as e:  # ImportError u otro fallo al importar el módulo
        raise MotorNoDisponible(f"No se pudo importar el motor '{nombre}': {e}") from e

    faltan = [a for a in _INTERFAZ_REQUERIDA if not hasattr(modulo, a)]
    if faltan:
        raise MotorNoDisponible(
            f"Motor '{nombre}' no implementado (falta: {', '.join(faltan)})."
        )
    return modulo
