"""Personalización local sin datos privados ni cambios en el almacén del usuario."""
import pytest

from config import personalizacion


@pytest.mark.parametrize("nombre", ["system_prompt.txt", "user_profile.yaml"])
def test_plantilla_por_defecto_y_preferencia_por_archivo_local(monkeypatch, tmp_path, nombre):
    monkeypatch.setattr(personalizacion, "PROJECT_ROOT", tmp_path)
    base = tmp_path / "config" / "data" / nombre
    base.parent.mkdir(parents=True)
    base.write_text("plantilla", encoding="utf-8")
    assert personalizacion.ruta_personalizacion(nombre) == base
    local = base.with_name(f"{base.stem}.local{base.suffix}")
    local.write_text("", encoding="utf-8")
    assert personalizacion.ruta_personalizacion(nombre) == local
    assert base.read_text(encoding="utf-8") == "plantilla"


def test_personalizacion_llega_a_ambos_adaptadores_sin_red(monkeypatch, tmp_path):
    from core import ai_engine, memory_engine
    from core.contexto import ajustar_contexto
    from core.motors.base import consolidar_sistema, separar_sistema
    from core.motors.copilot_engine import _contar

    prompt = tmp_path / "system_prompt.local.txt"
    perfil = tmp_path / "user_profile.local.yaml"
    prompt.write_text("Eres un asistente sereno y directo.", encoding="utf-8")
    perfil.write_text("tratamiento: Visitante\n", encoding="utf-8")
    monkeypatch.setattr(ai_engine, "SYSTEM_PROMPT_PATH", prompt)
    monkeypatch.setattr(memory_engine, "MEMORY_PATH", str(perfil))
    monkeypatch.setattr(memory_engine, "FACTS_PATH", str(tmp_path / "facts.yaml"))
    mensajes = ai_engine.construir_mensajes("Hola", [])
    assert "sereno" in mensajes[0]["content"]
    assert "Visitante" in mensajes[1]["content"]
    local = ajustar_contexto(consolidar_sistema(mensajes), 4096, 256)
    online = ajustar_contexto(mensajes, 16384, 1024, contar=_contar)
    assert "Visitante" in local[0]["content"]
    assert "sereno" in local[0]["content"]
    sistema, _ = separar_sistema(online)
    assert "Visitante" in sistema and "sereno" in sistema
    assert (tmp_path / "facts.yaml").is_file()
    assert list(tmp_path.glob("user_profile.local.yaml.legado-*.bak"))
