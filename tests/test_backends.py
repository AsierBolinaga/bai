"""
El orquestador es agnóstico del backend local: la elección se hace por
configuración y registro, y los adaptadores entregan al modelo un contexto
efectivo equivalente (identidad + memoria + idioma + turnos).
"""
import sys
import types

import pytest
import yaml

from config.motors_config import cargar_motors_config
from core.model_selector import ModelSelector
from core.motors import registry
from core.motors.base import contexto_efectivo, mensajes_a_prompt
from tests.conftest import escribir_gguf_falso
from tests.test_base import MENSAJES_BAI
from tests.test_motor_gpt4all import GPT4AllFake
from tests.test_motor_llama_cpp import LlamaFake


@pytest.fixture
def backends_fake(libreria_fake, monkeypatch, tmp_path):
    from core.motors import gpt4all_engine, llama_cpp_engine
    LlamaFake.instancias.clear()
    GPT4AllFake.instancias.clear()
    monkeypatch.setattr(llama_cpp_engine, "_modelos", {})
    monkeypatch.setattr(gpt4all_engine, "_modelos", {})
    libreria_fake("llama_cpp", Llama=LlamaFake)
    libreria_fake("gpt4all", GPT4All=GPT4AllFake)
    modelo = escribir_gguf_falso(tmp_path / "m.gguf")

    def config(motor, fallback=()):
        p = tmp_path / f"{motor}.yaml"
        p.write_text(yaml.safe_dump({"modo_por_defecto": "offline", "mostrar_motor": False, "offline": {
            "motor": motor, "fallback": list(fallback),
            "motores": {"llama_cpp": {"model_path": str(modelo)}, "gpt4all": {"model_path": str(modelo)}}}}),
            encoding="utf-8")
        return cargar_motors_config(p)

    return types.SimpleNamespace(config=config, modelo=str(modelo))


def _contexto_llama():
    enviados = LlamaFake.instancias[-1].llamadas[-1]["messages"]
    return contexto_efectivo(enviados)


def _contexto_gpt4all():
    g = GPT4AllFake.instancias[-1]
    sistema = g.sesiones[-1] or ""
    prompt, _ = g.generaciones[-1]
    return sistema, prompt


# --------------------------------------------------------------------------- selección por configuración
def test_backend_local_se_elige_por_configuracion(backends_fake):
    with ModelSelector(config=backends_fake.config("gpt4all")) as sel:
        r = sel.responder(MENSAJES_BAI)
    assert r.motor == "gpt4all" and LlamaFake.instancias == [] and len(GPT4AllFake.instancias) == 1

    with ModelSelector(config=backends_fake.config("llama_cpp")) as sel:
        r = sel.responder(MENSAJES_BAI)
    assert r.motor == "llama_cpp" and len(LlamaFake.instancias) == 1 and len(GPT4AllFake.instancias) == 1


def test_orquestador_no_depende_de_llama_cpp():
    import inspect
    import core.ai_engine, core.model_selector
    for modulo in (core.ai_engine, core.model_selector):
        codigo = "\n".join(l for l in inspect.getsource(modulo).splitlines() if not l.strip().startswith("#"))
        assert "llama_cpp" not in codigo.replace("llama_cpp_engine", ""), modulo.__name__


# --------------------------------------------------------------------------- contexto efectivo equivalente
def test_backends_reciben_contexto_efectivo_equivalente(backends_fake):
    with ModelSelector(config=backends_fake.config("llama_cpp")) as sel:
        sel.responder(MENSAJES_BAI)
    with ModelSelector(config=backends_fake.config("gpt4all")) as sel:
        sel.responder(MENSAJES_BAI)

    sistema_llama, turnos_llama = _contexto_llama()
    sistema_gpt4all, prompt_gpt4all = _contexto_gpt4all()
    sistema_esperado, turnos_esperados = contexto_efectivo(MENSAJES_BAI)

    # Mismo texto de sistema (identidad + memoria + idioma) en ambos backends
    assert sistema_llama == sistema_gpt4all == sistema_esperado
    for fragmento in ("Eres B.A.I", "furgoneta camper", "idioma del usuario"):
        assert fragmento in sistema_llama
    # Mismos turnos, en el mismo orden: llama.cpp como mensajes, GPT4All aplanados como texto
    assert turnos_llama == turnos_esperados
    assert prompt_gpt4all == mensajes_a_prompt([{"role": r, "content": c} for r, c in turnos_esperados])


def test_fallback_entre_backends_conserva_el_contexto(backends_fake, monkeypatch):
    from core.motors.base import MotorError
    from core.motors import llama_cpp_engine
    cfg = backends_fake.config("llama_cpp", fallback=["gpt4all"])
    monkeypatch.setattr(llama_cpp_engine, "responder", lambda m, c: (_ for _ in ()).throw(MotorError("caído")))
    with ModelSelector(config=cfg) as sel:
        r = sel.responder(MENSAJES_BAI)
    assert r.motor == "gpt4all" and r.fallback_usado
    sistema, _ = _contexto_gpt4all()
    assert sistema == contexto_efectivo(MENSAJES_BAI)[0]


# --------------------------------------------------------------------------- adaptador nuevo sin tocar el orquestador
def test_adaptador_nuevo_solo_con_registro_y_configuracion(tmp_path, monkeypatch, ai_engine_aislado):
    """Añadir un backend = módulo que cumple base.py + entrada en el registro + YAML.
    ai_engine y ModelSelector no cambian."""
    recibido = {}
    modulo = types.ModuleType("tests.fakes.eco_engine")
    modulo.NOMBRE, modulo.TIPO = "eco", "offline"
    modulo.disponible = lambda cfg: (True, "") if cfg.get("activo") else (False, "desactivado en la configuración")
    def responder(messages, cfg):
        recibido["contexto"] = contexto_efectivo(messages)
        return f"eco: {messages[-1]['content']}"
    modulo.responder = responder
    monkeypatch.setitem(sys.modules, "tests.fakes.eco_engine", modulo)
    monkeypatch.setitem(registry.MOTORES, "eco", "tests.fakes.eco_engine")

    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"modo_por_defecto": "offline", "mostrar_motor": True, "offline": {
        "motor": "eco", "motores": {"eco": {"activo": True, "modelo": "eco-v1"}}}}), encoding="utf-8")
    with ModelSelector(config=cargar_motors_config(p)) as sel:
        ai_engine_aislado.set_selector(sel)
        hist = []
        r = ai_engine_aislado.ask("hola eco", hist)
    assert r == "eco: hola eco\n[eco · eco-v1 · offline]"
    assert recibido["contexto"][0].startswith("Prompt de sistema de prueba.")
    assert hist == [{"role": "user", "content": "hola eco"}, {"role": "assistant", "content": "eco: hola eco"}]
