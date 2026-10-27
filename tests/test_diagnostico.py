"""Herramienta de diagnóstico (core/diagnostico.py)."""
import yaml

from core import diagnostico


def _yaml(tmp_path, datos):
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(datos), encoding="utf-8")
    return str(p)


def test_sin_modelo_devuelve_1_y_explica(tmp_path, capsys, libreria_fake, monkeypatch):
    libreria_fake("llama_cpp", Llama=object)
    libreria_fake("gpt4all", instalada=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = _yaml(tmp_path, {"modo_por_defecto": "offline",
                           "offline": {"motor": "llama_cpp", "fallback": ["gpt4all"],
                                       "motores": {"llama_cpp": {"model_path": str(tmp_path / "no.gguf")},
                                                   "gpt4all": {"model_path": str(tmp_path / "no.gguf")}}}})
    assert diagnostico.main(["--config", cfg]) == 1
    out = capsys.readouterr().out
    assert "OK  llama-cpp-python" in out and "--  gpt4all" in out
    assert "no se encuentra el modelo" in out
    assert "-- offline llama_cpp" in out and "-- offline gpt4all" in out and "no instalada" in out


def test_con_modelo_valido_devuelve_0(tmp_path, capsys, libreria_fake):
    from tests.conftest import escribir_gguf_falso
    from tests.test_motor_llama_cpp import LlamaFake
    modelo = escribir_gguf_falso(tmp_path / "m.gguf")
    libreria_fake("llama_cpp", Llama=LlamaFake)
    cfg = _yaml(tmp_path, {"modo_por_defecto": "offline",
                           "offline": {"motor": "llama_cpp", "motores": {"llama_cpp": {"model_path": str(modelo)}}}})
    assert diagnostico.main(["--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "cabecera GGUF válida" in out and "OK offline llama_cpp" in out


def test_probar_con_red_bloqueada(tmp_path, capsys, libreria_fake, monkeypatch):
    from tests.conftest import escribir_gguf_falso
    from tests.test_motor_llama_cpp import LlamaFake
    from core.motors import llama_cpp_engine
    monkeypatch.setattr(llama_cpp_engine, "_modelos", {})
    modelo = escribir_gguf_falso(tmp_path / "m.gguf")
    libreria_fake("llama_cpp", Llama=LlamaFake)
    cfg = _yaml(tmp_path, {"modo_por_defecto": "offline",
                           "offline": {"motor": "llama_cpp", "motores": {"llama_cpp": {"model_path": str(modelo)}}}})
    assert diagnostico.main(["--config", cfg, "--probar", "--bloquear-red", "--pregunta", "hola"]) == 0
    out = capsys.readouterr().out
    assert "Prueba real en modo OFFLINE con la red bloqueada" in out
    assert "OK  llama_cpp [m.gguf] (offline)" in out and "Respuesta: respuesta local" in out
    assert "ningún intento de conexión" in out


def test_probar_online_sin_credenciales_falla_limpiamente(tmp_path, capsys, libreria_fake, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("core.motors.openai_engine.load_dotenv", lambda *a, **k: None)
    libreria_fake("openai", OpenAI=object)
    cfg = _yaml(tmp_path, {"modo_por_defecto": "online",
                           "online": {"motor": "openai", "fallback_offline": False},
                           "offline": {"motor": "llama_cpp"}})
    assert diagnostico.main(["--config", cfg, "--modo", "online", "--probar"]) == 1
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" in out and "FALLO" in out


def test_informa_del_nivel_de_aislamiento(tmp_path, capsys, libreria_fake):
    from tests.conftest import escribir_gguf_falso
    from tests.test_motor_llama_cpp import LlamaFake
    modelo = escribir_gguf_falso(tmp_path / "m.gguf")
    libreria_fake("llama_cpp", Llama=LlamaFake)
    cfg = _yaml(tmp_path, {"modo_por_defecto": "offline",
                           "offline": {"motor": "llama_cpp", "motores": {"llama_cpp": {"model_path": str(modelo)}}}})
    assert diagnostico.main(["--config", cfg, "--probar", "--bloquear-red"]) == 0
    out = capsys.readouterr().out
    assert "Aislamiento vigente:" in out and "interfaces visibles:" in out
    assert "aislamiento_offline=proceso" in out
    # Sin --aislar la herramienta no presume aislamiento completo
    assert "no ve subprocesos ni código nativo" in out or "aislamiento de proceso" in out


def test_aislar_no_disponible_se_informa(tmp_path, capsys, monkeypatch):
    from core import aislamiento
    monkeypatch.setattr(aislamiento, "aislar_proceso", lambda: (False, "motivo de prueba"))
    cfg = _yaml(tmp_path, {"modo_por_defecto": "offline", "offline": {"motor": "llama_cpp"}})
    diagnostico.main(["--config", cfg, "--aislar"])
    assert "Aislamiento de proceso: NO DISPONIBLE (motivo de prueba)" in capsys.readouterr().out
