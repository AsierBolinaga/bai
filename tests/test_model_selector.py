"""Selección de motor/modelo según el modo (core/model_selector.py)."""
import pytest

from core.model_selector import ModelSelector, SinMotorDisponible, hay_conexion
from core.motors.base import MotorError, MotorNoDisponible
from tests.conftest import config_base, mensajes_basicos


# --------------------------------------------------------------------------- modo
def test_modo_inicial_viene_de_la_configuracion(selector_fake):
    assert selector_fake.crear(config_base("offline")).modo == "offline"
    assert selector_fake.crear(config_base("online")).modo == "online"


def test_set_modo_valida_y_normaliza(selector_fake):
    sel = selector_fake.crear()
    assert sel.set_modo(" ONLINE ") == "online"
    assert sel.modo == "online"
    with pytest.raises(ValueError):
        sel.set_modo("hibrido")
    assert sel.modo == "online"  # no cambia tras un valor inválido


# --------------------------------------------------------------------------- candidatos
def test_candidatos_offline_son_motor_principal_mas_fallback(selector_fake):
    sel = selector_fake.crear()
    assert [(c.nombre, c.tipo) for c in sel.candidatos("offline")] == [("off_a", "offline"), ("off_b", "offline")]


def test_candidatos_online_incluyen_offline_si_fallback_offline(selector_fake):
    sel = selector_fake.crear()
    assert [c.nombre for c in sel.candidatos("online")] == ["on_a", "off_a", "off_b"]


def test_candidatos_online_sin_fallback_offline(selector_fake):
    cfg = config_base("online")
    cfg["online"]["fallback_offline"] = False
    sel = selector_fake.crear(cfg)
    assert [c.nombre for c in sel.candidatos("online")] == ["on_a"]
    # El parámetro explícito tiene prioridad sobre la configuración
    assert [c.nombre for c in sel.candidatos("online", fallback_offline=True)] == ["on_a", "off_a", "off_b"]


def test_candidatos_sin_duplicados(selector_fake):
    cfg = config_base()
    cfg["offline"]["fallback"] = ["off_a", "off_b", "off_b"]
    assert [c.nombre for c in selector_fake.crear(cfg).candidatos("offline")] == ["off_a", "off_b"]


def test_candidato_modelo_y_config(selector_fake):
    sel = selector_fake.crear()
    on, off = sel.candidatos("online")[0], sel.candidatos("offline")[0]
    assert on.modelo == "modelo-online-a"
    assert off.modelo == "a.gguf"  # nombre de fichero legible, no la ruta completa
    assert off.config == {"model_path": "models/a.gguf"}


def test_modo_desconocido_en_candidatos(selector_fake):
    with pytest.raises(ValueError):
        selector_fake.crear().candidatos("mixto")


# --------------------------------------------------------------------------- modo offline
def test_fallo_arranque_respeta_fallback_y_no_contamina_otras_sesiones(selector_fake):
    sel = selector_fake.crear()
    sel.marcar_no_disponible("off_a", "fallo al cargar el modelo")
    estado = sel.estado()["candidatos"]
    assert not estado[0]["disponible"] and estado[0]["motivo"] == "fallo al cargar el modelo"
    assert estado[1]["disponible"]
    respuesta = sel.responder(mensajes_basicos())
    assert respuesta.motor == "off_b" and respuesta.fallback_usado
    assert selector_fake.motores.todos["off_a"].llamadas == []
    nueva = selector_fake.crear()
    assert nueva.estado()["candidatos"][0]["disponible"]


def test_offline_usa_motor_principal(selector_fake):
    sel = selector_fake.crear(config_base("offline"))
    r = sel.responder(mensajes_basicos())
    assert (r.motor, r.modelo, r.tipo, r.modo) == ("off_a", "a.gguf", "offline", "offline")
    assert r.texto == "respuesta de off_a"
    assert r.fallback_usado is False and r.errores == []
    assert selector_fake.motores.todos["off_b"].llamadas == []


def test_offline_no_comprueba_conectividad(selector_fake):
    sel = selector_fake.crear(config_base("offline"))
    selector_fake.estado["conexion"] = False
    sel.responder(mensajes_basicos())
    assert selector_fake.estado["hosts"] == []


def test_offline_fallback_si_principal_no_disponible(selector_fake):
    selector_fake.motores.todos["off_a"].disponible_ok = False
    selector_fake.motores.todos["off_a"].motivo = "no se encuentra el modelo"
    sel = selector_fake.crear(config_base("offline"))
    r = sel.responder(mensajes_basicos())
    assert r.motor == "off_b" and r.fallback_usado is True
    assert r.errores == [("off_a", "no se encuentra el modelo")]
    assert selector_fake.motores.todos["off_a"].llamadas == []  # nunca se invoca a un motor no disponible


def test_offline_fallback_si_principal_lanza_motor_error(selector_fake):
    selector_fake.motores.todos["off_a"].error = MotorError("fallo de generación")
    r = selector_fake.crear(config_base("offline")).responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert r.errores == [("off_a", "fallo de generación")]


def test_offline_fallback_si_principal_lanza_excepcion_inesperada(selector_fake):
    selector_fake.motores.todos["off_a"].error = RuntimeError("bug interno")
    r = selector_fake.crear(config_base("offline")).responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert r.errores[0][0] == "off_a" and "bug interno" in r.errores[0][1]


def test_offline_fallback_si_respuesta_vacia(selector_fake):
    selector_fake.motores.todos["off_a"].respuesta = "   "
    r = selector_fake.crear(config_base("offline")).responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert r.errores == [("off_a", "respuesta vacía")]


def test_offline_motor_no_registrado_se_salta(selector_fake):
    cfg = config_base("offline")
    cfg["offline"]["motor"] = "ollama"
    cfg["offline"]["fallback"] = ["off_b"]
    r = selector_fake.crear(cfg).responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert "no registrado" in r.errores[0][1]


def test_offline_sin_ningun_motor(selector_fake):
    for m in selector_fake.motores.todos.values():
        m.disponible_ok, m.motivo = False, "apagado"
    sel = selector_fake.crear(config_base("offline"))
    with pytest.raises(SinMotorDisponible) as exc:
        sel.responder(mensajes_basicos())
    assert exc.value.modo == "offline"
    assert exc.value.errores == [("off_a", "apagado"), ("off_b", "apagado")]
    assert "off_a: apagado" in str(exc.value)


# --------------------------------------------------------------------------- modo online
def test_online_con_conexion_usa_motor_online(selector_fake):
    sel = selector_fake.crear(config_base("online"))
    msgs = mensajes_basicos("hola online")
    r = sel.responder(msgs)
    assert (r.motor, r.tipo, r.modo, r.fallback_usado) == ("on_a", "online", "online", False)
    # Los mensajes llegan íntegros al motor (system + user) con su configuración
    llamadas = selector_fake.motores.todos["on_a"].llamadas
    assert llamadas == [(msgs, {"modelo": "modelo-online-a"})]
    # Se comprobó la conectividad contra el host del motor
    assert selector_fake.estado["hosts"] == ["on_a.example"]


def test_online_host_conectividad_configurable(selector_fake):
    cfg = config_base("online")
    cfg["online"]["motores"]["on_a"]["host_conectividad"] = "proxy.local"
    selector_fake.crear(cfg).responder(mensajes_basicos())
    assert selector_fake.estado["hosts"] == ["proxy.local"]


def test_online_sin_conexion_cae_a_offline(selector_fake):
    selector_fake.estado["conexion"] = False
    r = selector_fake.crear(config_base("online")).responder(mensajes_basicos())
    assert r.motor == "off_a" and r.tipo == "offline" and r.modo == "online"
    assert r.fallback_usado is True
    assert r.errores == [("on_a", "sin conexión con on_a.example")]
    assert selector_fake.motores.todos["on_a"].llamadas == []


def test_online_sin_credenciales_cae_a_offline(selector_fake):
    on = selector_fake.motores.todos["on_a"]
    on.disponible_ok, on.motivo = False, "variable de entorno OPENAI_API_KEY no definida"
    r = selector_fake.crear(config_base("online")).responder(mensajes_basicos())
    assert r.motor == "off_a"
    assert r.errores == [("on_a", "variable de entorno OPENAI_API_KEY no definida")]


def test_online_error_de_api_cae_a_offline(selector_fake):
    selector_fake.motores.todos["on_a"].error = MotorError("Error al contactar con OpenAI: 429")
    r = selector_fake.crear(config_base("online")).responder(mensajes_basicos())
    assert r.motor == "off_a"
    assert r.errores == [("on_a", "Error al contactar con OpenAI: 429")]


def test_online_sin_fallback_offline_falla_si_no_hay_conexion(selector_fake):
    cfg = config_base("online")
    cfg["online"]["fallback_offline"] = False
    selector_fake.estado["conexion"] = False
    with pytest.raises(SinMotorDisponible) as exc:
        selector_fake.crear(cfg).responder(mensajes_basicos())
    assert exc.value.errores == [("on_a", "sin conexión con on_a.example")]
    assert selector_fake.motores.todos["off_a"].llamadas == []


def test_online_fallback_entre_motores_online_antes_que_offline(selector_fake):
    selector_fake.motores.crear("on_b", "online")
    cfg = config_base("online")
    cfg["online"]["fallback"] = ["on_b"]
    cfg["online"]["motores"]["on_b"] = {"modelo": "modelo-online-b"}
    selector_fake.motores.todos["on_a"].error = MotorError("caído")
    r = selector_fake.crear(cfg).responder(mensajes_basicos())
    assert r.motor == "on_b" and r.modelo == "modelo-online-b" and r.tipo == "online"


def test_responder_con_modo_explicito_no_cambia_el_modo_actual(selector_fake):
    sel = selector_fake.crear(config_base("online"))
    r = sel.responder(mensajes_basicos(), modo="offline")
    assert r.motor == "off_a" and r.modo == "offline"
    assert sel.modo == "online"


# --------------------------------------------------------------------------- tipo de motor
def test_motor_configurado_en_seccion_equivocada_se_rechaza(selector_fake):
    cfg = config_base("online")
    cfg["online"]["motor"] = "off_b"  # motor offline en la sección online
    sel = selector_fake.crear(cfg)
    candidato = sel.candidatos("online")[0]
    modulo, motivo = sel.comprobar(candidato)
    assert modulo is None and "tipo 'offline'" in motivo


def test_disponible_que_lanza_excepcion_no_rompe(selector_fake):
    def disponible_roto(cfg):
        raise RuntimeError("explota")

    selector_fake.motores.todos["off_a"].disponible = disponible_roto
    r = selector_fake.crear(config_base("offline")).responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert "error comprobando disponibilidad" in r.errores[0][1]


# --------------------------------------------------------------------------- recorte de contexto
def _historial(n):
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(n):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    msgs.append({"role": "user", "content": "final"})
    return msgs


def test_recorte_por_seccion(selector_fake):
    cfg = config_base("offline")
    cfg["offline"]["max_mensajes_contexto"] = 3
    selector_fake.crear(cfg).responder(_historial(10))
    recibidos = selector_fake.motores.todos["off_a"].llamadas[0][0]
    assert [m["content"] for m in recibidos] == ["sys", "u9", "a9", "final"]


def test_recorte_por_motor_sobrescribe_seccion(selector_fake):
    cfg = config_base("offline")
    cfg["offline"]["max_mensajes_contexto"] = 3
    cfg["offline"]["motores"]["off_a"]["max_mensajes_contexto"] = 1
    selector_fake.crear(cfg).responder(_historial(10))
    recibidos, config = selector_fake.motores.todos["off_a"].llamadas[0]
    assert [m["content"] for m in recibidos] == ["sys", "final"]
    assert "max_mensajes_contexto" not in config  # no se filtra al motor


def test_sin_recorte_por_defecto(selector_fake):
    selector_fake.crear(config_base("offline")).responder(_historial(10))
    assert len(selector_fake.motores.todos["off_a"].llamadas[0][0]) == 22


# --------------------------------------------------------------------------- estado / seleccionar
def test_estado_describe_candidatos(selector_fake):
    selector_fake.estado["conexion"] = False
    selector_fake.motores.todos["off_a"].disponible_ok = False
    selector_fake.motores.todos["off_a"].motivo = "sin modelo"
    estado = selector_fake.crear(config_base("online")).estado()
    assert estado["modo"] == "online"
    assert [(c["motor"], c["disponible"]) for c in estado["candidatos"]] == [
        ("on_a", False), ("off_a", False), ("off_b", True)]
    assert estado["candidatos"][0]["motivo"] == "sin conexión con on_a.example"
    assert estado["candidatos"][1]["motivo"] == "sin modelo"
    assert estado["candidatos"][2]["modelo"] == "b.gguf"


def test_seleccionar_devuelve_primer_disponible(selector_fake):
    selector_fake.motores.todos["off_a"].disponible_ok = False
    sel = selector_fake.crear(config_base("offline"))
    candidato, modulo, errores = sel.seleccionar()
    assert candidato.nombre == "off_b" and modulo is selector_fake.motores.todos["off_b"]
    assert errores == [("off_a", "")] or errores[0][0] == "off_a"


def test_seleccionar_sin_disponibles(selector_fake):
    for m in selector_fake.motores.todos.values():
        m.disponible_ok = False
    candidato, modulo, errores = selector_fake.crear(config_base("offline")).seleccionar()
    assert candidato is None and modulo is None and len(errores) == 2


# --------------------------------------------------------------------------- integración con registro real
def test_selector_con_registro_real_y_config_del_proyecto(monkeypatch):
    """Con la configuración real y sin librerías/credenciales, el selector
    diagnostica correctamente en vez de fallar."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("core.motors.openai_engine.load_dotenv", lambda *a, **k: None)
    sel = ModelSelector(comprobar_conexion=lambda host: False)
    assert sel.modo == "offline" and sel.prioridad == "online"
    estado = sel.estado("online")
    # La configuración actual no usa fallback local al autorizar Copilot.
    assert [c["motor"] for c in estado["candidatos"]] == ["copilot"]
    assert all(not c["disponible"] for c in estado["candidatos"])
    with pytest.raises(SinMotorDisponible):
        sel.responder(mensajes_basicos(), modo="online")


def test_hay_conexion_devuelve_false_sin_red(monkeypatch):
    import socket

    def fallo(*a, **k):
        raise OSError("sin red")

    monkeypatch.setattr(socket, "create_connection", fallo)
    assert hay_conexion("api.openai.com") is False


# --------------------------------------------------------------------------- política: prioridad local en modo online
from tests.conftest import config_local  # noqa: E402


def test_prioridad_local_orden_de_candidatos(selector_fake):
    sel = selector_fake.crear(config_local("online"))
    assert [c.nombre for c in sel.candidatos("online")] == ["off_a", "off_b", "on_a"]
    # El override por llamada permite pedir el motor online primero
    assert [c.nombre for c in sel.candidatos("online", prioridad="online")] == ["on_a", "off_a", "off_b"]


def test_prioridad_local_usa_motor_local_aunque_haya_conexion_y_clave(selector_fake):
    sel = selector_fake.crear(config_local("online"))
    r = sel.responder(mensajes_basicos())
    assert r.motor == "off_a" and r.tipo == "offline" and r.modo == "online" and r.fallback_usado is False
    assert selector_fake.motores.todos["on_a"].llamadas == []
    assert selector_fake.estado["hosts"] == []  # no se comprobó conectividad: no hizo falta


def test_prioridad_local_online_solo_si_ningun_local_disponible(selector_fake):
    for nombre in ("off_a", "off_b"):
        selector_fake.motores.todos[nombre].disponible_ok = False
        selector_fake.motores.todos[nombre].motivo = "sin modelo"
    r = selector_fake.crear(config_local("online")).responder(mensajes_basicos())
    assert r.motor == "on_a" and r.tipo == "online" and r.fallback_usado is True
    assert r.errores == [("off_a", "sin modelo"), ("off_b", "sin modelo")]


def test_prioridad_local_online_si_los_locales_fallan_al_generar(selector_fake):
    from core.motors.base import MotorError
    selector_fake.motores.todos["off_a"].error = MotorError("contexto excedido")
    selector_fake.motores.todos["off_b"].respuesta = ""
    r = selector_fake.crear(config_local("online")).responder(mensajes_basicos())
    assert r.motor == "on_a"


def test_prioridad_local_sin_nada_disponible(selector_fake):
    for m in selector_fake.motores.todos.values():
        m.disponible_ok = False
    with pytest.raises(SinMotorDisponible) as exc:
        selector_fake.crear(config_local("online")).responder(mensajes_basicos())
    assert [m for m, _ in exc.value.errores] == ["off_a", "off_b", "on_a"]


def test_prioridad_online_por_llamada(selector_fake):
    r = selector_fake.crear(config_local("online")).responder(mensajes_basicos(), prioridad="online")
    assert r.motor == "on_a" and r.fallback_usado is False


def test_prioridad_invalida_por_llamada(selector_fake):
    with pytest.raises(ValueError):
        selector_fake.crear(config_local("online")).candidatos("online", prioridad="auto")


def test_estado_incluye_prioridad(selector_fake):
    sel = selector_fake.crear(config_local("online"))
    assert sel.estado()["prioridad"] == "local"
    assert sel.estado("offline")["prioridad"] is None


# --------------------------------------------------------------------------- fallback_offline=False bajo prioridad local
def test_fallback_offline_false_excluye_locales_con_cualquier_prioridad(selector_fake):
    sel = selector_fake.crear(config_local("online"))
    assert [c.nombre for c in sel.candidatos("online", fallback_offline=False)] == ["on_a"]
    assert [c.nombre for c in sel.candidatos("online", fallback_offline=False, prioridad="online")] == ["on_a"]
    assert [c.nombre for c in sel.candidatos("online", fallback_offline=False, prioridad="local")] == ["on_a"]
    # sin el parámetro explícito, la prioridad local sigue poniendo los locales primero
    assert [c.nombre for c in sel.candidatos("online")] == ["off_a", "off_b", "on_a"]


def test_responder_online_explicito_suspende_y_restablece_la_guardia_incluso_con_error(selector_fake):
    from core.network_guard import guardia_activa
    sel = selector_fake.crear(config_local("offline"))
    selector_fake.motores.todos["on_a"].error = RuntimeError("explota")
    with pytest.raises(SinMotorDisponible):
        sel.responder(mensajes_basicos(), modo="online", fallback_offline=False)
    assert guardia_activa()
    # y en modo offline normal la guardia permanece durante la generación
    vista = {}
    selector_fake.motores.todos["off_a"].responder = lambda m, c: vista.setdefault("g", guardia_activa()) and "ok"
    sel.responder(mensajes_basicos())
    assert vista == {"g": True}


def test_sin_conexion_en_sesion_aislada_lo_indica(selector_fake, monkeypatch):
    from core import aislamiento
    monkeypatch.setattr(aislamiento, "en_namespace_aislado", lambda: True)
    selector_fake.estado["conexion"] = False
    sel = selector_fake.crear(config_base("offline"))
    modulo, motivo = sel.comprobar(sel.candidatos("online", fallback_offline=False)[0])
    assert modulo is None and "aislada a nivel de proceso" in motivo
