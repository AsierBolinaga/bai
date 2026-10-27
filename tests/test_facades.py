"""Fachadas de compatibilidad core/online_engine.py y core/offline_engine.py."""
from core.motors.base import MotorError
from core.offline_engine import responder_offline
from core.online_engine import responder_online
from tests.conftest import config_base, mensajes_basicos


def test_responder_offline_con_texto(selector_fake):
    sel = selector_fake.crear(config_base("online"))  # aunque el modo sea online, la fachada fuerza offline
    ok, texto = responder_offline("hola", selector=sel)
    assert (ok, texto) == (True, "respuesta de off_a")
    recibidos, _ = selector_fake.motores.todos["off_a"].llamadas[0]
    assert recibidos == [{"role": "user", "content": "hola"}]
    assert selector_fake.motores.todos["on_a"].llamadas == []


def test_responder_offline_con_contexto_y_lista(selector_fake):
    sel = selector_fake.crear()
    ok, _ = responder_offline("hola", context="eres B.A.I", selector=sel)
    assert ok
    recibidos, _ = selector_fake.motores.todos["off_a"].llamadas[0]
    assert recibidos[0] == {"role": "system", "content": "eres B.A.I"}

    ok, _ = responder_offline(mensajes_basicos("lista"), selector=sel)
    assert ok
    assert selector_fake.motores.todos["off_a"].llamadas[1][0] == mensajes_basicos("lista")


def test_responder_offline_fallo(selector_fake):
    for m in selector_fake.motores.todos.values():
        m.disponible_ok, m.motivo = False, "apagado"
    ok, texto = responder_offline("hola", selector=selector_fake.crear())
    assert ok is False and texto.startswith("[B.A.I]") and "apagado" in texto


def test_responder_online_no_usa_fallback_offline(selector_fake):
    sel = selector_fake.crear(config_base("online"))
    assert responder_online(mensajes_basicos(), selector=sel) == (True, "respuesta de on_a")

    selector_fake.motores.todos["on_a"].error = MotorError("API caída")
    ok, texto = responder_online(mensajes_basicos(), selector=sel)
    assert ok is False and "API caída" in texto
    assert selector_fake.motores.todos["off_a"].llamadas == []


def test_fachadas_no_dejan_guardia_instalada(monkeypatch):
    """Las fachadas crean un selector temporal (modo offline por defecto): deben liberarlo."""
    from core.network_guard import guardia_activa
    monkeypatch.setattr("core.motors.openai_engine.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ok, _ = responder_offline("hola")
    assert ok is False and not guardia_activa()
    ok, _ = responder_online(mensajes_basicos())
    assert ok is False and not guardia_activa()
