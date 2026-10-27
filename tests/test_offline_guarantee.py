"""
Garantía de modo offline: nunca se contacta con servicios externos, sea cual
sea la configuración, y nunca se pasa a online sin orden explícita del usuario.
"""
import socket
import warnings

import pytest
import yaml

from config import motors_config as mc
from core.model_selector import ModelSelector, SinMotorDisponible
from core.network_guard import AccesoRedBloqueado
from tests.conftest import config_base, mensajes_basicos


# --------------------------------------------------------------------------- configuración
def test_config_allow_download_true_en_offline_se_neutraliza(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"offline": {"motor": "gpt4all", "motores": {"gpt4all": {
        "model_path": "models/m.gguf", "allow_download": True}}}}), encoding="utf-8")
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        cfg = mc.cargar_motors_config(p)
    assert cfg["offline"]["motores"]["gpt4all"]["allow_download"] is False
    assert any("allow_download=true ignorado" in str(a.message) for a in avisos)


@pytest.mark.parametrize("valor", ["hibrida", "auto", 1])
def test_prioridad_invalida(tmp_path, valor):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"online": {"motor": "openai", "prioridad": valor}}), encoding="utf-8")
    with pytest.raises(mc.ConfigError):
        mc.cargar_motors_config(p)


def test_prioridad_normaliza_mayusculas(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"online": {"motor": "openai", "prioridad": "ONLINE"}}), encoding="utf-8")
    assert mc.cargar_motors_config(p)["online"]["prioridad"] == "online"


# --------------------------------------------------------------------------- selector: sólo motores locales
def test_offline_rechaza_motor_online_configurado_como_local(selector_fake):
    """Aunque el YAML ponga un motor online en la sección offline, no se ejecuta."""
    cfg = config_base("offline")
    cfg["offline"]["motor"] = "on_a"
    cfg["offline"]["fallback"] = ["off_b"]
    sel = selector_fake.crear(cfg)
    r = sel.responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert r.errores[0][0] == "on_a" and "tipo 'online'" in r.errores[0][1]
    assert selector_fake.motores.todos["on_a"].llamadas == []
    assert selector_fake.estado["hosts"] == []  # ni siquiera se comprobó la conectividad


def test_offline_ignora_fallback_offline_y_prioridad(selector_fake):
    cfg = config_base("offline")
    cfg["online"]["prioridad"] = "local"
    assert [c.tipo for c in selector_fake.crear(cfg).candidatos("offline")] == ["offline", "offline"]
    assert [c.tipo for c in selector_fake.crear(cfg).candidatos("offline", fallback_offline=True,
                                                                  prioridad="online")] == ["offline", "offline"]


def test_motor_offline_que_intenta_salir_a_la_red_es_bloqueado_y_descartado(selector_fake):
    """Un motor local mal configurado (p. ej. con descargas activadas) que intente
    conectar con un servicio externo recibe un error de red y se descarta."""
    off_a = selector_fake.motores.todos["off_a"]

    def responder_con_descarga(messages, config):
        socket.create_connection(("gpt4all.io", 443), timeout=1)  # debe fallar
        return "no debería llegar aquí"

    off_a.responder = responder_con_descarga
    r = selector_fake.crear(config_base("offline")).responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert r.errores[0][0] == "off_a" and "gpt4all.io" in r.errores[0][1]


def test_motor_offline_que_traga_el_error_de_red_tambien_se_descarta(selector_fake):
    off_a = selector_fake.motores.todos["off_a"]

    def responder_silencioso(messages, config):
        try:
            socket.getaddrinfo("huggingface.co", 443)
        except OSError:
            pass
        return "respuesta generada tras intentar la red"

    off_a.responder = responder_silencioso
    r = selector_fake.crear(config_base("offline")).responder(mensajes_basicos())
    assert r.motor == "off_b"
    assert r.errores == [("off_a", "intentó acceder a la red durante la generación (huggingface.co)")]


def test_disponible_de_motor_offline_no_puede_usar_la_red(selector_fake):
    off_a = selector_fake.motores.todos["off_a"]

    def disponible_con_red(config):
        try:
            socket.getaddrinfo("gpt4all.io", 443)
        except OSError:
            pass
        return True, ""

    off_a.disponible = disponible_con_red
    sel = selector_fake.crear(config_base("offline"))
    modulo, motivo = sel.comprobar(sel.candidatos()[0])
    assert modulo is None and "intentó acceder a la red al comprobar disponibilidad" in motivo


def test_motor_offline_puede_usar_servicios_locales(selector_fake):
    """Un servidor local (p. ej. Ollama en localhost) sí está permitido."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    direccion = srv.getsockname()
    off_a = selector_fake.motores.todos["off_a"]

    def responder_local(messages, config):
        socket.create_connection(direccion, timeout=2).close()
        return "respuesta vía servicio local"

    off_a.responder = responder_local
    try:
        r = selector_fake.crear(config_base("offline")).responder(mensajes_basicos())
    finally:
        srv.close()
    assert r.motor == "off_a" and r.texto == "respuesta vía servicio local"


def test_guardia_no_afecta_a_motores_online(selector_fake):
    """En modo online el motor online sí puede conectar (la guardia sólo envuelve motores offline)."""
    on_a = selector_fake.motores.todos["on_a"]
    conectados = []

    def responder_online(messages, config):
        try:
            socket.getaddrinfo("api.openai.com", 443)
            conectados.append("intento permitido")
        except AccesoRedBloqueado:
            conectados.append("BLOQUEADO")
        except OSError:
            conectados.append("intento permitido")  # sin red real en el entorno de test
        return "ok online"

    on_a.responder = responder_online
    r = selector_fake.crear(config_base("online")).responder(mensajes_basicos())
    assert r.motor == "on_a" and conectados == ["intento permitido"]


def test_guardia_de_sesion_activa_en_offline_y_liberada_al_autorizar_online(selector_fake):
    from core.network_guard import guardia_activa
    connect = socket.socket.connect
    sel = selector_fake.crear(config_base("offline"))
    assert guardia_activa()                       # modo offline => guardia de sesión instalada
    sel.responder(mensajes_basicos())
    assert guardia_activa()                       # sigue activa entre turnos
    with pytest.raises(AccesoRedBloqueado):
        socket.getaddrinfo("api.openai.com", 443)  # también fuera de la llamada al motor
    sel.set_modo("online")
    assert not guardia_activa() and socket.socket.connect is connect
    sel.set_modo("offline")
    assert guardia_activa()
    sel.cerrar()
    assert not guardia_activa() and socket.socket.connect is connect


def test_selector_online_no_instala_guardia_de_sesion(selector_fake):
    from core.network_guard import guardia_activa
    selector_fake.crear(config_base("online"))
    assert not guardia_activa()


def test_selector_como_context_manager_libera_la_guardia():
    from core.network_guard import guardia_activa
    with ModelSelector(config=config_base("offline"), obtener_motor=lambda n: None) as sel:
        assert sel.modo == "offline" and guardia_activa()
    assert not guardia_activa()


# --------------------------------------------------------------------------- nunca online sin autorización
def test_offline_sin_motores_no_pasa_a_online(selector_fake):
    for nombre in ("off_a", "off_b"):
        selector_fake.motores.todos[nombre].disponible_ok = False
    sel = selector_fake.crear(config_base("offline"))
    with pytest.raises(SinMotorDisponible) as exc:
        sel.responder(mensajes_basicos())
    assert [m for m, _ in exc.value.errores] == ["off_a", "off_b"]
    assert sel.modo == "offline"
    assert selector_fake.motores.todos["on_a"].llamadas == []
    assert selector_fake.estado["hosts"] == []
