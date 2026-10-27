"""Motor online OpenAI (core/motors/openai_engine.py) con librería `openai` simulada."""
import types

import pytest

from core.motors import openai_engine as motor
from core.motors.base import MotorError, MotorNoDisponible
from tests.conftest import mensajes_basicos


class ClienteFake:
    """Imita openai.OpenAI(...).chat.completions.create(...)."""
    instancias = []

    def __init__(self, api_key=None, **kw):
        self.api_key = api_key
        self.llamadas = []
        self.contenido = "  Hola desde OpenAI  "
        self.error = None
        ClienteFake.instancias.append(self)
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        msg = types.SimpleNamespace(content=self.contenido)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


@pytest.fixture
def openai_fake(libreria_fake, monkeypatch):
    ClienteFake.instancias.clear()
    monkeypatch.setattr(motor, "_clientes", {})
    monkeypatch.setattr(motor, "load_dotenv", lambda *a, **k: None)  # no leer .env real
    libreria_fake("openai", OpenAI=ClienteFake)
    return ClienteFake


def test_contrato():
    assert motor.NOMBRE == "openai" and motor.TIPO == "online"
    assert motor.HOST_CONECTIVIDAD == "api.openai.com"


def test_disponible_sin_libreria(libreria_fake, monkeypatch):
    monkeypatch.setattr(motor, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    libreria_fake("openai", instalada=False)
    ok, motivo = motor.disponible({})
    assert ok is False and "openai" in motivo


def test_disponible_sin_api_key(openai_fake, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ok, motivo = motor.disponible({})
    assert ok is False and "OPENAI_API_KEY" in motivo


def test_disponible_ok(openai_fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert motor.disponible({}) == (True, "")
    assert openai_fake.instancias == []  # disponible() no crea el cliente


def test_responder_usa_config(openai_fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    msgs = mensajes_basicos()
    texto = motor.responder(msgs, {"modelo": "gpt-4o-mini", "temperature": 0.1, "max_tokens": 77})
    assert texto == "Hola desde OpenAI"
    cliente = openai_fake.instancias[0]
    assert cliente.api_key == "sk-test"
    assert cliente.llamadas == [{"model": "gpt-4o-mini", "messages": msgs, "temperature": 0.1, "max_tokens": 77}]


def test_responder_valores_por_defecto(openai_fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    motor.responder(mensajes_basicos(), {})
    llamada = openai_fake.instancias[0].llamadas[0]
    assert (llamada["model"], llamada["temperature"], llamada["max_tokens"]) == ("gpt-4o", 0.5, 1024)


def test_cliente_se_reutiliza(openai_fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    motor.responder(mensajes_basicos(), {})
    motor.responder(mensajes_basicos(), {})
    assert len(openai_fake.instancias) == 1


def test_responder_sin_api_key(openai_fake, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MotorNoDisponible):
        motor.responder(mensajes_basicos(), {})


def test_error_de_api_se_convierte_en_motor_error(openai_fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    motor._cliente().error = RuntimeError("rate limit")
    with pytest.raises(MotorError, match="rate limit"):
        motor.responder(mensajes_basicos(), {"modelo": "gpt-4o"})


def test_respuesta_vacia_es_error(openai_fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    motor._cliente().contenido = "  "
    with pytest.raises(MotorError, match="vacía"):
        motor.responder(mensajes_basicos(), {})


def test_mensajes_invalidos(openai_fake, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(ValueError):
        motor.responder("texto plano", {})
