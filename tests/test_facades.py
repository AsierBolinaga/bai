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


# --------------------------------------------------------------------------- regresión: sólo online bajo prioridad local
def test_regresion_responder_online_nunca_usa_backend_local_con_prioridad_local(selector_fake):
    """Hallazgo reproducido: con online.prioridad=local, responder_online() (fallback_offline=False)
    devolvía la respuesta de un motor local. Debe limitarse a motores online."""
    from tests.conftest import config_local
    sel = selector_fake.crear(config_local("online"))
    assert responder_online(mensajes_basicos(), selector=sel) == (True, "respuesta de on_a")
    assert selector_fake.motores.todos["off_a"].llamadas == []

    selector_fake.motores.todos["on_a"].error = MotorError("API caída")
    ok, texto = responder_online(mensajes_basicos(), selector=sel)
    assert ok is False and "API caída" in texto
    assert selector_fake.motores.todos["off_a"].llamadas == []
    assert selector_fake.motores.todos["off_b"].llamadas == []


def test_regresion_guardia_de_sesion_offline_no_bloquea_llamada_online_autorizada(selector_fake):
    """responder_online() con un selector en modo offline: la guardia de sesión se
    suspende durante la llamada autorizada y se restablece después."""
    import socket
    from core.network_guard import AccesoRedBloqueado, guardia_activa
    from tests.conftest import config_local
    sel = selector_fake.crear(config_local("offline"))
    assert guardia_activa()
    observado = {}

    def responder_que_usa_red(messages, config):
        observado["guardia_durante"] = guardia_activa()
        try:
            socket.getaddrinfo("api.openai.com", 443)
            observado["red"] = "permitida"
        except AccesoRedBloqueado:
            observado["red"] = "BLOQUEADA"
        except OSError:
            observado["red"] = "permitida"   # sin red real en el entorno: fallo normal, no de la guardia
        return "ok online"

    selector_fake.motores.todos["on_a"].responder = responder_que_usa_red
    assert responder_online(mensajes_basicos(), selector=sel) == (True, "ok online")
    assert observado == {"guardia_durante": False, "red": "permitida"}
    assert guardia_activa() and sel.modo == "offline"   # la sesión sigue offline y protegida


def test_responder_online_con_selector_por_defecto_no_queda_bloqueado(monkeypatch):
    """Selector creado por la fachada (arranca offline): la comprobación de conectividad
    del motor online no debe ser bloqueada por la guardia de sesión."""
    from core import model_selector
    from core.network_guard import AccesoRedBloqueado, guardia_activa
    monkeypatch.setattr("core.motors.openai_engine.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    vistos = {}

    def conectividad(host, port=443, timeout=3):
        vistos["guardia"] = guardia_activa()
        return False  # sin red: el motor online no está disponible

    monkeypatch.setattr(model_selector, "hay_conexion", conectividad)
    import tests.test_motor_openai  # noqa: F401  (asegura que la librería falsa pueda inyectarse)
    import sys, types, importlib.machinery
    falso = types.ModuleType("openai"); falso.__spec__ = importlib.machinery.ModuleSpec("openai", None); falso.OpenAI = object
    monkeypatch.setitem(sys.modules, "openai", falso)
    ok, texto = responder_online(mensajes_basicos())
    assert ok is False and "sin conexión" in texto
    assert vistos == {"guardia": False}
    assert not guardia_activa()
