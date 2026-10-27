"""
Flujo completo sin dobles internos: ai_engine -> ModelSelector -> registry ->
motores reales (openai_engine / llama_cpp_engine), simulando únicamente las
librerías externas y la red.
"""
import pytest
import yaml

from config.motors_config import cargar_motors_config
from core.model_selector import ModelSelector
from core.network_guard import GuardiaRed
from tests.conftest import escribir_gguf_falso
from tests.test_motor_llama_cpp import LlamaFake
from tests.test_motor_openai import ClienteFake


@pytest.fixture
def entorno_real(tmp_path, libreria_fake, monkeypatch, ai_engine_aislado):
    from core.motors import llama_cpp_engine, openai_engine

    LlamaFake.instancias.clear()
    ClienteFake.instancias.clear()
    monkeypatch.setattr(llama_cpp_engine, "_modelos", {})
    monkeypatch.setattr(openai_engine, "_clientes", {})
    monkeypatch.setattr(openai_engine, "load_dotenv", lambda *a, **k: None)
    libreria_fake("llama_cpp", Llama=LlamaFake)
    libreria_fake("openai", OpenAI=ClienteFake)
    libreria_fake("gpt4all", instalada=False)

    modelo = escribir_gguf_falso(tmp_path / "mistral.gguf")
    cfg_yaml = tmp_path / "motors_config.yaml"
    cfg_yaml.write_text(yaml.safe_dump({
        "modo_por_defecto": "online",
        "mostrar_motor": False,
        "online": {"motor": "openai", "fallback_offline": True, "prioridad": "online",
                   "motores": {"openai": {"modelo": "gpt-4o", "host_conectividad": "api.openai.com"}}},
        "offline": {"motor": "llama_cpp", "fallback": ["gpt4all"], "max_mensajes_contexto": 4,
                    "motores": {"llama_cpp": {"model_path": str(modelo)},
                                "gpt4all": {"model_path": str(modelo)}}},
    }), encoding="utf-8")

    red = {"ok": True}
    sel = ModelSelector(config=cargar_motors_config(cfg_yaml), comprobar_conexion=lambda host: red["ok"])
    ai_engine_aislado.set_selector(sel)
    return ai_engine_aislado, sel, red


def test_online_con_clave_usa_openai(entorno_real, monkeypatch):
    ai, sel, red = entorno_real
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    hist = []
    assert ai.ask("hola", hist) == "Hola desde OpenAI"
    assert ClienteFake.instancias[0].llamadas[0]["model"] == "gpt-4o"
    assert LlamaFake.instancias == []
    assert [m["role"] for m in hist] == ["user", "assistant"]


def test_online_sin_clave_cae_a_llama_cpp(entorno_real, monkeypatch, capsys):
    ai, sel, red = entorno_real
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai.ask("hola", []) == "respuesta local"
    assert ClienteFake.instancias == []
    assert len(LlamaFake.instancias) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().out


def test_online_sin_red_cae_a_llama_cpp(entorno_real, monkeypatch):
    ai, sel, red = entorno_real
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    red["ok"] = False
    assert ai.ask("hola", []) == "respuesta local"
    assert ClienteFake.instancias == []


def test_offline_forzado_ignora_openai_y_recorta_contexto(entorno_real, monkeypatch):
    ai, sel, red = entorno_real
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    hist = []
    ai.ask("pasa a modo offline", hist)
    for i in range(5):
        assert ai.ask(f"pregunta {i}", hist) == "respuesta local"
    assert ClienteFake.instancias == []
    assert len(LlamaFake.instancias) == 1  # modelo cargado una sola vez
    ultima = LlamaFake.instancias[0].llamadas[-1]["messages"]
    no_sistema = [m for m in ultima if m["role"] != "system"]
    assert len(no_sistema) == 4  # max_mensajes_contexto offline
    assert no_sistema[-1]["content"] == "pregunta 4"
    # contexto completo en offline: un único 'system' consolidado con identidad + memoria + idioma
    assert [m["role"] for m in ultima].count("system") == 1
    assert ultima[0]["content"] == ("Prompt de sistema de prueba.\n\nMemoria de prueba.\n\n"
                                    "Responde siempre en el idioma del usuario.")
    assert len(hist) == 10


def test_estado_refleja_disponibilidad_real(entorno_real, monkeypatch):
    ai, sel, red = entorno_real
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    texto = ai.ask("estado", [])
    assert "-- online  openai" in texto and "OPENAI_API_KEY" in texto
    assert "OK offline llama_cpp" in texto
    assert "-- offline gpt4all" in texto and "no instalada" in texto


# --------------------------------------------------------------------------- aislamiento de red en modo offline
def test_offline_no_abre_ningun_socket(entorno_real, monkeypatch):
    """Modo offline: ni comprobación de conectividad ni ninguna otra conexión."""
    ai, sel, red = entorno_real
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    sel.set_modo("offline")

    def conectividad_prohibida(host):
        raise AssertionError(f"comprobación de conectividad en modo offline hacia {host}")

    monkeypatch.setattr(sel, "_comprobar_conexion", conectividad_prohibida)
    with GuardiaRed() as bloqueo:
        r = ai.ask("hola", [])
        # Reconfirmar también con las fachadas
        from core.offline_engine import responder_offline
        ok, _ = responder_offline("hola", selector=sel)
    assert r == "respuesta local" and ok
    assert bloqueo.intentos == []
    assert ClienteFake.instancias == []



def test_regresion_config_allow_download_true_no_reactiva_descargas(tmp_path, libreria_fake, monkeypatch):
    """Ruta completa con el adaptador real de GPT4All (librería simulada) y una
    configuración que intenta habilitar descargas en modo offline."""
    from tests.test_motor_gpt4all import GPT4AllFake
    from core.motors import gpt4all_engine
    GPT4AllFake.instancias.clear()
    monkeypatch.setattr(gpt4all_engine, "_modelos", {})
    libreria_fake("gpt4all", GPT4All=GPT4AllFake)
    modelo = escribir_gguf_falso(tmp_path / "m.gguf")
    cfg_yaml = tmp_path / "c.yaml"
    cfg_yaml.write_text(yaml.safe_dump({"modo_por_defecto": "offline", "offline": {
        "motor": "gpt4all", "motores": {"gpt4all": {"model_path": str(modelo), "allow_download": True}}}}),
        encoding="utf-8")
    with pytest.warns(UserWarning, match="allow_download=true ignorado"):
        config = cargar_motors_config(cfg_yaml)
    sel = ModelSelector(config=config, comprobar_conexion=lambda h: (_ for _ in ()).throw(AssertionError("red")))
    with GuardiaRed() as guardia:
        r = sel.responder([{"role": "user", "content": "hola"}])
    assert r.motor == "gpt4all"
    assert GPT4AllFake.instancias[0].kwargs["allow_download"] is False
    assert guardia.intentos == []
