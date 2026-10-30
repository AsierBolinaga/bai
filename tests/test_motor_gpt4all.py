"""Motor offline GPT4All (core/motors/gpt4all_engine.py) con librería simulada."""
from contextlib import contextmanager

import pytest

from core.motors import gpt4all_engine as motor
from core.motors.base import MotorError, MotorNoDisponible
from tests.conftest import escribir_gguf_falso


class GPT4AllFake:
    instancias = []

    def __init__(self, model_name, model_path, **kw):
        self.model_name, self.model_path = model_name, model_path
        self.kwargs = kw
        self.sesiones, self.generaciones, self.plantillas = [], [], []
        self.contenido = " hola gpt4all "
        GPT4AllFake.instancias.append(self)

    @contextmanager
    def chat_session(self, system_prompt=None, prompt_template=None, **kw):
        self.sesiones.append(system_prompt)
        self.plantillas.append(prompt_template)
        yield

    def generate(self, prompt, **kw):
        self.generaciones.append((prompt, kw))
        return self.contenido


@pytest.fixture
def gpt4all_fake(libreria_fake, monkeypatch):
    GPT4AllFake.instancias.clear()
    monkeypatch.setattr(motor, "_modelos", {})
    libreria_fake("gpt4all", GPT4All=GPT4AllFake)
    return GPT4AllFake


@pytest.fixture
def modelo_tmp(tmp_path):
    p = escribir_gguf_falso(tmp_path / "mistral.gguf")
    return p


def test_contrato():
    assert motor.NOMBRE == "gpt4all" and motor.TIPO == "offline"


def test_disponible(gpt4all_fake, modelo_tmp, tmp_path, libreria_fake):
    assert motor.disponible({"model_path": str(modelo_tmp)}) == (True, "")
    assert motor.disponible({})[0] is False
    assert motor.disponible({"model_path": str(tmp_path / "no.gguf")})[0] is False
    libreria_fake("gpt4all", instalada=False)
    assert motor.disponible({"model_path": str(modelo_tmp)})[0] is False


def test_ruta_desde_config_legacy(gpt4all_fake):
    from config.motors_config import PROJECT_ROOT
    assert motor._ruta_modelo({"modelo": "mistral-7b"}) == str(PROJECT_ROOT / "models" / "mistral-7b.gguf")
    assert motor._ruta_modelo({"modelo": "m.gguf"}) == str(PROJECT_ROOT / "models" / "m.gguf")
    assert motor._ruta_modelo({"ruta_modelo": "/x/y.gguf"}) == "/x/y.gguf"


def test_responder_separa_sistema_y_aplana_turnos(gpt4all_fake, modelo_tmp):
    msgs = [
        {"role": "system", "content": "Eres B.A.I"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "buenas"},
        {"role": "user", "content": "¿qué tal?"},
    ]
    texto = motor.responder(msgs, {"model_path": str(modelo_tmp), "max_tokens": 64, "temperature": 0.3})
    assert texto == "hola gpt4all"
    g = gpt4all_fake.instancias[0]
    assert (g.model_name, g.model_path) == ("mistral.gguf", str(modelo_tmp.parent))
    assert g.kwargs == {"allow_download": False, "n_ctx": 2048, "verbose": False}
    assert g.sesiones == ["Eres B.A.I"]
    assert g.plantillas == ["[INST] {0} [/INST]"]  # plantilla Mistral-Instruct por defecto
    prompt, kw = g.generaciones[0]
    assert prompt == "Usuario: hola\nB.A.I: buenas\nUsuario: ¿qué tal?\nB.A.I:"
    assert kw == {"max_tokens": 64, "temp": 0.3}


def test_responder_sin_sistema(gpt4all_fake, modelo_tmp):
    motor.responder([{"role": "user", "content": "hola"}], {"model_path": str(modelo_tmp)})
    g = gpt4all_fake.instancias[0]
    assert g.sesiones == [None] and g.generaciones[0][1] == {"max_tokens": 200}


def test_cache_y_errores(gpt4all_fake, modelo_tmp, tmp_path):
    cfg = {"model_path": str(modelo_tmp)}
    motor.responder([{"role": "user", "content": "a"}], cfg)
    motor.responder([{"role": "user", "content": "b"}], cfg)
    assert len(gpt4all_fake.instancias) == 1

    gpt4all_fake.instancias[0].contenido = ""
    with pytest.raises(MotorError, match="vacía"):
        motor.responder([{"role": "user", "content": "c"}], cfg)

    with pytest.raises(MotorNoDisponible):
        motor.responder([{"role": "user", "content": "d"}], {"model_path": str(tmp_path / "no.gguf")})


def test_regresion_allow_download_desactivado_por_defecto(gpt4all_fake, modelo_tmp):
    """Regresión: GPT4All con allow_download=True (su valor por defecto) consulta
    https://gpt4all.io aunque el modelo exista en disco; sin red la carga falla y
    en modo offline es una fuga de privacidad. El adaptador debe desactivarlo."""
    motor.responder([{"role": "user", "content": "hola"}], {"model_path": str(modelo_tmp)})
    assert gpt4all_fake.instancias[0].kwargs["allow_download"] is False


@pytest.mark.parametrize("valor", [True, 1, "true", "yes"])
def test_regresion_allow_download_no_es_configurable(gpt4all_fake, modelo_tmp, capsys, valor):
    """Regresión: una configuración con allow_download activado NO debe reactivar
    el acceso a gpt4all.io. El adaptador lo fuerza a False y avisa."""
    motor.responder([{"role": "user", "content": "hola"}],
                    {"model_path": str(modelo_tmp), "allow_download": valor, "n_ctx": 512, "verbose": True})
    assert gpt4all_fake.instancias[0].kwargs == {"allow_download": False, "n_ctx": 512, "verbose": True}
    assert "'allow_download' ignorado" in capsys.readouterr().out


def test_disponible_rechaza_fichero_corrupto(gpt4all_fake, tmp_path):
    malo = tmp_path / "m.gguf"
    malo.write_bytes(b"no soy un gguf")
    ok, motivo = motor.disponible({"model_path": str(malo)})
    assert ok is False and "formato GGUF" in motivo


def test_prompt_template_configurable(gpt4all_fake, modelo_tmp):
    motor.responder([{"role": "user", "content": "hola"}],
                    {"model_path": str(modelo_tmp), "prompt_template": "### Human:\n{0}\n### Assistant:\n"})
    assert gpt4all_fake.instancias[0].plantillas == ["### Human:\n{0}\n### Assistant:\n"]


def test_contexto_incluye_sistema_plantilla_y_reserva(gpt4all_fake, modelo_tmp):
    msgs = [{"role": "system", "content": "memoria"},
            {"role": "user", "content": "antiguo" * 200},
            {"role": "assistant", "content": "respuesta"},
            {"role": "user", "content": "actual"}]
    plantilla = "INICIO " * 20 + "{0} FIN"
    with pytest.warns(UserWarning, match="Contexto ajustado"):
        motor.responder(msgs, {"model_path": str(modelo_tmp), "n_ctx": 512,
                              "max_tokens": 64, "prompt_template": plantilla})
    instancia = gpt4all_fake.instancias[0]
    prompt, opciones = instancia.generaciones[0]
    assert "antiguo" not in prompt and "actual" in prompt
    assert instancia.sesiones == ["memoria"] and opciones["max_tokens"] == 64
    assert len(("memoria\n\n" + plantilla.format(prompt)).encode("utf-8")) + 64 + 64 <= 512


def test_plantilla_excesiva_no_llega_a_generar(gpt4all_fake, modelo_tmp):
    with pytest.raises(MotorError, match="Contexto insuficiente"):
        motor.responder([{"role": "user", "content": "hola"}],
                        {"model_path": str(modelo_tmp), "prompt_template": "x" * 3000 + "{0}"})
    assert gpt4all_fake.instancias == []


def test_cache_gpt4all_respeta_n_ctx(gpt4all_fake, modelo_tmp):
    for limite in (2048, 4096):
        motor.responder([{"role": "user", "content": "hola"}],
                        {"model_path": str(modelo_tmp), "n_ctx": limite})
    assert [g.kwargs["n_ctx"] for g in gpt4all_fake.instancias] == [2048, 4096]
