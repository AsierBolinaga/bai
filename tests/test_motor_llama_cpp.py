"""Motor offline llama.cpp (core/motors/llama_cpp_engine.py) con librería simulada."""
import pytest

from core.motors import llama_cpp_engine as motor
from core.motors.base import MotorError, MotorNoDisponible
from tests.conftest import escribir_gguf_falso, mensajes_basicos


class LlamaFake:
    instancias = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.llamadas = []
        self.contenido = " respuesta local "
        self.error = None
        self.cerrado = False
        LlamaFake.instancias.append(self)

    def close(self):
        self.cerrado = True

    def create_chat_completion(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        return {"choices": [{"message": {"role": "assistant", "content": self.contenido}}]}


class LlamaQueFalla:
    def __init__(self, **kwargs):
        raise RuntimeError("gguf corrupto")


@pytest.fixture
def llama_fake(libreria_fake, monkeypatch):
    LlamaFake.instancias.clear()
    monkeypatch.setattr(motor, "_modelos", {})
    libreria_fake("llama_cpp", Llama=LlamaFake)
    return LlamaFake


@pytest.fixture
def modelo_tmp(tmp_path):
    p = escribir_gguf_falso(tmp_path / "modelo.gguf")
    return str(p)


def test_contrato():
    assert motor.NOMBRE == "llama_cpp" and motor.TIPO == "offline"


def test_importar_no_carga_modelo(llama_fake):
    assert llama_fake.instancias == [] and motor._modelos == {}


def test_disponible_sin_libreria(libreria_fake, modelo_tmp):
    libreria_fake("llama_cpp", instalada=False)
    ok, motivo = motor.disponible({"model_path": modelo_tmp})
    assert ok is False and "llama_cpp" in motivo


def test_disponible_sin_model_path(llama_fake):
    ok, motivo = motor.disponible({})
    assert ok is False and "model_path" in motivo


def test_disponible_modelo_inexistente(llama_fake, tmp_path):
    ok, motivo = motor.disponible({"model_path": str(tmp_path / "no.gguf")})
    assert ok is False and "no se encuentra" in motivo


def test_disponible_ok_y_rutas_relativas_a_la_raiz(llama_fake, modelo_tmp, monkeypatch):
    assert motor.disponible({"model_path": modelo_tmp}) == (True, "")
    # Ruta relativa: se resuelve respecto a PROJECT_ROOT, no al CWD
    from config.motors_config import PROJECT_ROOT
    monkeypatch.chdir("/")
    ok, motivo = motor.disponible({"model_path": "models/inexistente.gguf"})
    assert ok is False and str(PROJECT_ROOT) in motivo


def test_responder_carga_con_parametros_y_usa_chat_completion(llama_fake, modelo_tmp):
    cfg = {"model_path": modelo_tmp, "n_ctx": 4096, "max_tokens": 128, "temperature": 0.2, "chat_format": "mistral-instruct"}
    msgs = mensajes_basicos()
    texto = motor.responder(msgs, cfg)
    assert texto == "respuesta local"
    llama = llama_fake.instancias[0]
    assert llama.kwargs == {"model_path": modelo_tmp, "n_ctx": 4096, "use_mlock": True,
                            "verbose": False, "chat_format": "mistral-instruct"}
    assert llama.llamadas == [{"messages": msgs, "max_tokens": 128, "temperature": 0.2, "stop": ["</s>", "###"]}]


def test_responder_valores_por_defecto(llama_fake, modelo_tmp):
    motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})
    llama = llama_fake.instancias[0]
    assert llama.kwargs["n_ctx"] == 2048 and llama.kwargs["chat_format"] == "llama-2"
    assert llama.llamadas[0]["max_tokens"] == 256 and llama.llamadas[0]["temperature"] == 0.7


def test_modelo_se_cachea_por_ruta(llama_fake, modelo_tmp, tmp_path):
    motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})
    motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})
    assert len(llama_fake.instancias) == 1
    otro = escribir_gguf_falso(tmp_path / "otro.gguf")
    motor.responder(mensajes_basicos(), {"model_path": str(otro)})
    assert len(llama_fake.instancias) == 2


def test_responder_sin_modelo_lanza_no_disponible(llama_fake, tmp_path):
    with pytest.raises(MotorNoDisponible):
        motor.responder(mensajes_basicos(), {"model_path": str(tmp_path / "no.gguf")})


def test_error_al_cargar(libreria_fake, modelo_tmp, monkeypatch):
    monkeypatch.setattr(motor, "_modelos", {})
    libreria_fake("llama_cpp", Llama=LlamaQueFalla)
    with pytest.raises(MotorError, match="gguf corrupto"):
        motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})
    assert motor._modelos == {}  # un fallo de carga no deja nada en la caché


def test_error_al_generar(llama_fake, modelo_tmp):
    motor.cargar_modelo({"model_path": modelo_tmp}).error = RuntimeError("contexto excedido")
    with pytest.raises(MotorError, match="contexto excedido"):
        motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})


def test_respuesta_vacia(llama_fake, modelo_tmp):
    motor.cargar_modelo({"model_path": modelo_tmp}).contenido = ""
    with pytest.raises(MotorError, match="vacía"):
        motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})


def test_disponible_rechaza_fichero_corrupto(llama_fake, tmp_path):
    """Regresión: una descarga truncada o una página HTML guardada como .gguf
    debe detectarse antes de intentar cargar el modelo."""
    malo = tmp_path / "mistral.gguf"
    malo.write_bytes(b"<!DOCTYPE html>")
    ok, motivo = motor.disponible({"model_path": str(malo)})
    assert ok is False and "formato GGUF" in motivo
    with pytest.raises(MotorNoDisponible):
        motor.responder(mensajes_basicos(), {"model_path": str(malo)})
    assert llama_fake.instancias == []


def test_liberar_modelos_cierra_y_vacia_cache(llama_fake, modelo_tmp):
    motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})
    instancia = llama_fake.instancias[0]
    motor.liberar_modelos()
    assert instancia.cerrado is True and motor._modelos == {}
    # Tras liberar, la siguiente petición vuelve a cargar el modelo
    motor.responder(mensajes_basicos(), {"model_path": modelo_tmp})
    assert len(llama_fake.instancias) == 2


def test_regresion_adaptador_consolida_los_mensajes_de_sistema(llama_fake, modelo_tmp):
    """Regresión: los formateadores de llama-cpp-python sólo leen el primer 'system';
    el adaptador debe entregar un único 'system' con identidad + memoria + idioma."""
    from tests.test_base import MENSAJES_BAI
    motor.responder(MENSAJES_BAI, {"model_path": modelo_tmp})
    enviados = llama_fake.instancias[0].llamadas[0]["messages"]
    assert [m["role"] for m in enviados] == ["system", "user", "assistant", "user"]
    for fragmento in ("Eres B.A.I", "furgoneta camper", "idioma del usuario"):
        assert fragmento in enviados[0]["content"]
    assert [m["content"] for m in enviados[1:]] == ["hola", "buenas", "¿cómo se llama mi vehículo?"]
