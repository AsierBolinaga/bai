"""Carga, normalización y validación de config/motors_config.yaml."""
import pytest
import yaml

from config import motors_config as mc


def escribir(tmp_path, datos):
    p = tmp_path / "motors_config.yaml"
    p.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    return p


def test_config_real_del_proyecto_es_valida():
    cfg = mc.cargar_motors_config()
    assert cfg["modo_por_defecto"] == "offline"
    assert cfg["online"]["prioridad"] == "local"
    assert not cfg["offline"]["motores"]["gpt4all"].get("allow_download")
    assert cfg["online"]["motor"] == "openai"
    assert cfg["online"]["motores"]["openai"]["modelo"] == "gpt-4o"
    assert cfg["offline"]["motor"] == "llama_cpp"
    assert cfg["offline"]["fallback"] == ["gpt4all"]
    assert "llama_cpp" in cfg["offline"]["motores"]
    assert cfg["offline"]["motores"]["llama_cpp"]["model_path"].endswith(".gguf")


def test_motors_config_module_level_compatibilidad():
    assert mc.motors_config["offline"]["motor"] == "llama_cpp"


def test_yaml_vacio_usa_defaults(tmp_path):
    p = tmp_path / "vacio.yaml"
    p.write_text("", encoding="utf-8")
    cfg = mc.cargar_motors_config(p)
    assert cfg["modo_por_defecto"] == "offline"       # privacidad por defecto
    assert cfg["online"]["prioridad"] == "local"      # local primero incluso en modo online
    assert cfg["online"]["motor"] == "openai"
    assert cfg["offline"]["motor"] == "llama_cpp"
    assert cfg["online"]["fallback_offline"] is True


def test_formato_legacy_plano_se_normaliza(tmp_path):
    p = escribir(tmp_path, {
        "motor_offline": "gpt4all",
        "modelo": "mistral-7b-instruct-v0.1.Q4_0",
        "model_path": "models/mistral-7b-instruct-v0.1.Q4_0.gguf",
    })
    cfg = mc.cargar_motors_config(p)
    assert cfg["offline"]["motor"] == "gpt4all"
    assert cfg["offline"]["motores"]["gpt4all"]["model_path"] == "models/mistral-7b-instruct-v0.1.Q4_0.gguf"
    assert cfg["offline"]["motores"]["gpt4all"]["modelo"] == "mistral-7b-instruct-v0.1.Q4_0"
    # El formato legacy no tenía sección online: se aplican los defaults
    assert cfg["online"]["motor"] == "openai"


def test_formato_legacy_readme_ruta_modelo(tmp_path):
    p = escribir(tmp_path, {"motor": "llama_cpp", "ruta_modelo": "models/x.gguf"})
    cfg = mc.cargar_motors_config(p)
    assert cfg["offline"]["motor"] == "llama_cpp"
    assert cfg["offline"]["motores"]["llama_cpp"]["model_path"] == "models/x.gguf"


def test_legacy_sin_ruta_deriva_de_modelo(tmp_path):
    p = escribir(tmp_path, {"motor_offline": "llama_cpp", "modelo": "mi-modelo"})
    cfg = mc.cargar_motors_config(p)
    assert cfg["offline"]["motores"]["llama_cpp"]["model_path"] == "models/mi-modelo.gguf"


def test_modo_por_defecto_invalido(tmp_path):
    p = escribir(tmp_path, {"modo_por_defecto": "hibrido"})
    with pytest.raises(mc.ConfigError):
        mc.cargar_motors_config(p)


def test_modo_por_defecto_normaliza_mayusculas(tmp_path):
    p = escribir(tmp_path, {"modo_por_defecto": "OFFLINE"})
    assert mc.cargar_motors_config(p)["modo_por_defecto"] == "offline"


def test_fallback_como_string_se_convierte_en_lista(tmp_path):
    p = escribir(tmp_path, {"offline": {"motor": "llama_cpp", "fallback": "gpt4all"}})
    cfg = mc.cargar_motors_config(p)
    assert cfg["offline"]["fallback"] == ["gpt4all"]
    # Los motores referenciados siempre tienen entrada en 'motores'
    assert "gpt4all" in cfg["offline"]["motores"]


def test_seccion_sin_motor_es_error(tmp_path):
    p = escribir(tmp_path, {"offline": {"motor": None}})
    with pytest.raises(mc.ConfigError):
        mc.cargar_motors_config(p)


@pytest.mark.parametrize("valor", [0, -3, "diez", 2.5])
def test_max_mensajes_contexto_invalido(tmp_path, valor):
    p = escribir(tmp_path, {"offline": {"motor": "llama_cpp", "max_mensajes_contexto": valor}})
    with pytest.raises(mc.ConfigError):
        mc.cargar_motors_config(p)


def test_motores_del_yaml_sustituyen_a_los_defaults(tmp_path):
    p = escribir(tmp_path, {"offline": {"motor": "ollama", "motores": {"ollama": {"modelo": "mistral"}}}})
    cfg = mc.cargar_motors_config(p)
    assert set(cfg["offline"]["motores"]) == {"ollama"}


def test_fichero_inexistente(tmp_path):
    with pytest.raises(mc.ConfigError):
        mc.cargar_motors_config(tmp_path / "no_existe.yaml")


def test_yaml_no_diccionario(tmp_path):
    p = tmp_path / "lista.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(mc.ConfigError):
        mc.cargar_motors_config(p)


def test_resolver_ruta():
    assert mc.resolver_ruta(None) is None
    assert mc.resolver_ruta("/abs/x.gguf") == "/abs/x.gguf"
    assert mc.resolver_ruta("models/x.gguf") == str(mc.PROJECT_ROOT / "models" / "x.gguf")


def test_config_path_es_absoluta_e_independiente_del_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = mc.cargar_motors_config()
    assert cfg["offline"]["motor"] == "llama_cpp"
