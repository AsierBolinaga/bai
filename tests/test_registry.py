"""Registro de motores (core/motors/registry.py)."""
import sys
import types

import pytest

from core.motors import registry
from core.motors.base import MotorNoDisponible


@pytest.fixture(autouse=True)
def restaurar_registro():
    original = registry.motores_registrados()
    yield
    registry.MOTORES.clear()
    registry.MOTORES.update(original)


def test_motores_registrados_por_defecto():
    assert set(registry.motores_registrados()) == {"openai", "llama_cpp", "gpt4all", "ollama"}


def test_motor_desconocido():
    with pytest.raises(MotorNoDisponible, match="no registrado"):
        registry.obtener_motor("inexistente")


@pytest.mark.parametrize("nombre,tipo", [("openai", "online"), ("llama_cpp", "offline"), ("gpt4all", "offline")])
def test_motores_reales_se_importan_sin_librerias_pesadas(nombre, tipo):
    """Importar un motor no debe requerir openai/llama_cpp/gpt4all instalados."""
    modulo = registry.obtener_motor(nombre)
    assert modulo.NOMBRE == nombre
    assert modulo.TIPO == tipo
    assert callable(modulo.disponible) and callable(modulo.responder)


def test_motor_stub_no_implementado_se_detecta():
    # core/motors/ollama_engine.py es todavía un TODO
    with pytest.raises(MotorNoDisponible, match="no implementado"):
        registry.obtener_motor("ollama")


def test_modulo_que_no_importa(monkeypatch):
    registry.registrar_motor("roto", "tests.no_existe_este_modulo")
    with pytest.raises(MotorNoDisponible, match="No se pudo importar"):
        registry.obtener_motor("roto")


def test_registrar_motor_en_tiempo_de_ejecucion(monkeypatch):
    modulo = types.ModuleType("tests.fakes.custom")
    modulo.NOMBRE, modulo.TIPO = "custom", "offline"
    modulo.disponible = lambda cfg: (True, "")
    modulo.responder = lambda msgs, cfg: "ok"
    monkeypatch.setitem(sys.modules, "tests.fakes.custom", modulo)
    registry.registrar_motor("custom", "tests.fakes.custom")
    assert registry.obtener_motor("custom") is modulo
