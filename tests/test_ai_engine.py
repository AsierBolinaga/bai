"""Orquestador (core/ai_engine.py): comandos de modo, construcción de contexto y enrutado."""
import pytest

from core.model_selector import SinMotorDisponible
from tests.conftest import config_base


@pytest.fixture
def entorno(ai_engine_aislado, selector_fake):
    sel = selector_fake.crear(config_base("online"))
    ai_engine_aislado.set_selector(sel)
    return ai_engine_aislado, sel, selector_fake


# --------------------------------------------------------------------------- comandos de modo
@pytest.mark.parametrize("texto,esperado", [
    ("pasa a modo offline", "offline"),
    ("Pasa a modo ONLINE", "online"),
    ("cambia a modo offline por favor", "offline"),
    ("switch to offline mode", "offline"),
    ("Switch to online mode", "online"),
])
def test_detectar_comando_modo(ai_engine_aislado, texto, esperado):
    assert ai_engine_aislado.detectar_comando_modo(texto) == esperado


NO_COMANDOS = [
    # negaciones
    "No quiero cambiar a modo online",
    "no pases a modo online",
    "nunca cambies a modo online, por favor",
    "don't switch to online mode",
    "please do not switch to online mode",
    # preguntas sobre el comando / ayuda
    "Explica que significa <<pasa a modo online>>",
    "¿Qué hace 'pasa a modo online'?",
    "¿puedo pasar a modo online?",
    "pasa a modo online?",
    "what does 'switch to online mode' do?",
    "¿qué es el modo online?",
    # ejemplos entrecomillados
    '"pasa a modo online"',
    "«switch to online mode»",
    # comando incrustado en una petición normal
    "antes de pasar a modo online dime la hora",
    "cuando te diga pasa a modo online, ¿qué harás?",
    "me gustaría que pasaras a modo online más tarde",
    "switch to online mode only if I ask twice",
    # otros
    "estoy en modo offline desde ayer",
    "hola",
    "pasa a modo turbo",
    "pasa a modo online y luego apaga la luz",
]

COMANDOS = [
    ("pasa a modo online", "online"),
    ("Pasa a modo ONLINE.", "online"),
    ("pasar a modo offline", "offline"),
    ("cambia a modo offline", "offline"),
    ("cambiar al modo online", "online"),
    ("por favor, pasa a modo offline", "offline"),
    ("pasa a modo online, por favor", "online"),
    ("B.A.I, pasa a modo online", "online"),
    ("bai pasa a modo offline!", "offline"),
    ("switch to online mode", "online"),
    ("Switch to offline mode", "offline"),
    ("please switch to online mode", "online"),
    ("switch to offline mode, please.", "offline"),
    ("  pasa   a  modo   online  ", "online"),
]


@pytest.mark.parametrize("texto", NO_COMANDOS)
def test_frases_normales_no_cambian_el_modo(ai_engine_aislado, texto):
    assert ai_engine_aislado.detectar_comando_modo(texto) is None


@pytest.mark.parametrize("texto,esperado", COMANDOS)
def test_sintaxis_documentada_de_comandos(ai_engine_aislado, texto, esperado):
    assert ai_engine_aislado.detectar_comando_modo(texto) == esperado


def test_ask_cambia_a_offline(entorno):
    ai, sel, fake = entorno
    hist = []
    r = ai.ask("pasa a modo offline", hist)
    assert "OFFLINE" in r
    assert sel.modo == "offline"
    assert hist == []                      # los comandos no van al historial
    assert not ai._memoria_temporal.hechos.exists()   # ni se "aprenden" como hechos
    assert all(m.llamadas == [] for m in fake.motores.todos.values())


def test_ask_vuelve_a_online(entorno):
    ai, sel, _ = entorno
    sel.set_modo("offline")
    r = ai.ask("switch to online mode", [])
    assert "ONLINE" in r and sel.modo == "online"


def test_ask_estado(entorno):
    ai, sel, fake = entorno
    fake.estado["conexion"] = False
    r = ai.ask("estado", [])
    assert "Modo actual: ONLINE" in r
    assert "on_a" in r and "sin conexión" in r
    assert "off_a" in r


# --------------------------------------------------------------------------- construcción de contexto
def test_construir_mensajes_estructura(ai_engine_aislado):
    hist = [
        {"role": "system", "content": "viejo system que debe desaparecer"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    msgs = ai_engine_aislado.construir_mensajes("nueva pregunta", hist)
    assert msgs == [
        {"role": "system", "content": "Prompt de sistema de prueba."},
        {"role": "system", "content": "Memoria de prueba."},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "system", "content": "Responde siempre en el idioma del usuario."},
        {"role": "user", "content": "nueva pregunta"},
    ]
    assert hist[0]["content"].startswith("viejo")  # el historial original no se modifica


def test_construir_mensajes_sin_memoria(ai_engine_aislado):
    msgs = ai_engine_aislado.construir_mensajes("hola", None, memory_context="   ")
    assert [m["role"] for m in msgs] == ["system", "system", "user"]


def test_get_system_prompt_real_independiente_del_cwd(tmp_path, monkeypatch):
    import core.ai_engine as ai
    monkeypatch.chdir(tmp_path)
    assert "B.A.I" in ai.get_system_prompt()


# --------------------------------------------------------------------------- enrutado
def test_ask_online_envia_contexto_completo_y_guarda_historial(entorno):
    ai, sel, fake = entorno
    hist = [{"role": "user", "content": "antes"}, {"role": "assistant", "content": "ok"}]
    r = ai.ask("¿qué hora es?", hist)
    assert r == "respuesta de on_a"
    recibidos, _ = fake.motores.todos["on_a"].llamadas[0]
    assert [m["role"] for m in recibidos] == ["system", "system", "user", "assistant", "system", "user"]
    assert recibidos[-1]["content"] == "¿qué hora es?"
    assert hist[-2:] == [{"role": "user", "content": "¿qué hora es?"},
                         {"role": "assistant", "content": "respuesta de on_a"}]
    assert not ai._memoria_temporal.hechos.exists()   # conversar no escribe hechos


def test_ask_offline_recibe_el_mismo_contexto_que_online(entorno):
    """Antes, el modo offline sólo recibía el texto del usuario."""
    ai, sel, fake = entorno
    sel.set_modo("offline")
    hist = [{"role": "user", "content": "antes"}, {"role": "assistant", "content": "ok"}]
    r = ai.ask("hola local", hist)
    assert r == "respuesta de off_a"
    recibidos, _ = fake.motores.todos["off_a"].llamadas[0]
    assert recibidos[0]["content"] == "Prompt de sistema de prueba."
    assert recibidos[1]["content"] == "Memoria de prueba."
    assert {"role": "user", "content": "antes"} in recibidos
    assert fake.motores.todos["on_a"].llamadas == []


def test_ask_online_sin_conexion_avisa_y_usa_offline(entorno, capsys):
    ai, sel, fake = entorno
    fake.estado["conexion"] = False
    hist = []
    r = ai.ask("hola", hist)
    assert r == "respuesta de off_a"
    salida = capsys.readouterr().out
    assert "Aviso" in salida and "off_a" in salida and "sin conexión" in salida
    assert len(hist) == 2


def test_ask_sin_motores_devuelve_mensaje_y_no_toca_historial(entorno):
    ai, sel, fake = entorno
    fake.estado["conexion"] = False
    for nombre in ("off_a", "off_b"):
        fake.motores.todos[nombre].disponible_ok = False
        fake.motores.todos[nombre].motivo = "apagado"
    hist = [{"role": "user", "content": "x"}]
    r = ai.ask("hola", hist)
    assert r.startswith("Ningún motor ha podido responder en modo ONLINE")
    assert not r.startswith("[B.A.I]")  # el prefijo lo añade assistant.py
    assert "- on_a: sin conexión" in r and "- off_a: apagado" in r
    assert hist == [{"role": "user", "content": "x"}]


def test_ask_con_historial_none(entorno):
    ai, _, _ = entorno
    assert ai.ask("hola", None) == "respuesta de on_a"


def test_ask_acepta_selector_explicito(ai_engine_aislado, selector_fake):
    sel = selector_fake.crear(config_base("offline"))
    assert ai_engine_aislado.ask("hola", [], selector=sel) == "respuesta de off_a"


def test_get_selector_es_perezoso_y_unico(ai_engine_aislado, monkeypatch):
    creados = []

    class SelectorDummy:
        def __init__(self):
            creados.append(self)

    monkeypatch.setattr(ai_engine_aislado, "ModelSelector", SelectorDummy)
    assert ai_engine_aislado.get_selector() is ai_engine_aislado.get_selector()
    assert len(creados) == 1


def test_describir_estado_formato(entorno):
    ai, sel, fake = entorno
    texto = ai.describir_estado(sel)
    lineas = texto.splitlines()
    assert lineas[0].startswith("Modo actual: ONLINE — Uso de servicios online AUTORIZADO. Prioridad online")
    assert lineas[1].startswith("  OK online  on_a")
    assert "modelo=modelo-online-a" in lineas[1]


# --------------------------------------------------------------------------- efectos en memoria según éxito/fallo
def test_turno_fallido_no_aprende_ni_modifica_historial(entorno):
    """Un fallo del motor no deja rastro: ni historial ni memoria persistente."""
    ai, sel, fake = entorno
    fake.estado["conexion"] = False
    for nombre in ("off_a", "off_b"):
        fake.motores.todos[nombre].disponible_ok = False
    hist = []
    r = ai.ask("mi furgoneta es una camper", hist)
    assert r.startswith("Ningún motor")
    assert hist == [] and not ai._memoria_temporal.hechos.exists()
    assert ai.ultima_respuesta is None


def test_turno_normal_nunca_escribe_memoria_persistente(entorno):
    """Regresión fase 7: antes CADA mensaje pasaba por learn_from_input() y
    modificaba el perfil. Ahora la conversación normal no escribe nada."""
    import yaml
    ai, sel, fake = entorno
    hist = []
    for frase in ("mi furgoneta es una camper", "tengo 30 años", "me gusta el monte"):
        ai.ask(frase, hist)
    assert ai.ultima_respuesta is not None and ai.ultima_respuesta.motor == "on_a"
    assert not ai._memoria_temporal.hechos.exists()
    perfil = yaml.safe_load(ai._memoria_temporal.perfil.read_text(encoding="utf-8"))
    assert perfil == {"aprendido_durante_sesion": {}}


def test_fallo_en_generacion_tras_exito_previo_deja_estado_coherente(entorno):
    ai, sel, fake = entorno
    hist = []
    ai.ask("primera", hist)
    fake.motores.todos["on_a"].error = RuntimeError("caída")
    fake.estado["conexion"] = False
    for nombre in ("off_a", "off_b"):
        fake.motores.todos[nombre].disponible_ok = False
    ai.ask("segunda", hist)
    assert [m["content"] for m in hist] == ["primera", "respuesta de on_a"]
    assert not ai._memoria_temporal.hechos.exists()
    assert ai.ultima_respuesta is None


# --------------------------------------------------------------------------- backend visible
@pytest.fixture
def entorno_visible(ai_engine_aislado, selector_fake):
    cfg = config_base("online")
    cfg["mostrar_motor"] = True
    sel = selector_fake.crear(cfg)
    ai_engine_aislado.set_selector(sel)
    return ai_engine_aislado, sel, selector_fake


def test_respuesta_lleva_etiqueta_del_backend(entorno_visible):
    ai, sel, fake = entorno_visible
    hist = []
    r = ai.ask("hola", hist)
    assert r == "respuesta de on_a\n[on_a · modelo-online-a · online]"
    # El historial guarda el texto limpio, sin etiqueta
    assert hist[-1] == {"role": "assistant", "content": "respuesta de on_a"}


def test_etiqueta_indica_fallback(entorno_visible):
    ai, sel, fake = entorno_visible
    fake.estado["conexion"] = False
    r = ai.ask("hola", [])
    assert r.endswith("[off_a · a.gguf · offline · fallback]")


def test_etiqueta_desactivable(entorno):
    ai, sel, fake = entorno  # config_base() lleva mostrar_motor=False
    assert ai.ask("hola", []) == "respuesta de on_a"


def test_config_real_muestra_motor_por_defecto():
    from config.motors_config import cargar_motors_config
    assert cargar_motors_config()["mostrar_motor"] is True


def test_cambio_de_modo_informa_del_motor_activo(entorno):
    ai, sel, fake = entorno
    r = ai.ask("pasa a modo offline", [])
    assert "Motor activo: off_a [a.gguf] (offline)." in r
    fake.motores.todos["off_a"].disponible_ok = False
    fake.motores.todos["off_a"].motivo = "sin modelo"
    r = ai.ask("pasa a modo online", [])
    assert "Motor activo: on_a [modelo-online-a] (online)." in r


def test_cambio_de_modo_avisa_si_no_hay_motor(entorno):
    ai, sel, fake = entorno
    for nombre in ("off_a", "off_b"):
        fake.motores.todos[nombre].disponible_ok = False
        fake.motores.todos[nombre].motivo = "sin modelo"
    r = ai.ask("pasa a modo offline", [])
    assert "ATENCIÓN: ningún motor disponible" in r and "off_a: sin modelo" in r
    assert sel.modo == "offline"  # el modo cambia igualmente; el usuario queda avisado


# --------------------------------------------------------------------------- política de modos y autorización
from tests.conftest import config_local  # noqa: E402


@pytest.fixture
def entorno_local(ai_engine_aislado, selector_fake):
    """Configuración por defecto del proyecto: arranque offline, prioridad local."""
    sel = selector_fake.crear(config_local("offline"))
    ai_engine_aislado.set_selector(sel)
    return ai_engine_aislado, sel, selector_fake


def test_offline_sin_motor_informa_y_pide_autorizacion_sin_cambiar_modo(entorno_local):
    ai, sel, fake = entorno_local
    for nombre in ("off_a", "off_b"):
        fake.motores.todos[nombre].disponible_ok = False
        fake.motores.todos[nombre].motivo = "sin modelo"
    r = ai.ask("hola", [])
    assert "Ningún motor ha podido responder en modo OFFLINE" in r
    assert "No se ha contactado con ningún servicio externo" in r
    assert "pasa a modo online" in r
    assert sel.modo == "offline"
    assert fake.motores.todos["on_a"].llamadas == [] and fake.estado["hosts"] == []


def test_online_sin_motor_no_incluye_pista_de_autorizacion(entorno_local):
    ai, sel, fake = entorno_local
    sel.set_modo("online")
    fake.estado["conexion"] = False
    for nombre in ("off_a", "off_b"):
        fake.motores.todos[nombre].disponible_ok = False
    r = ai.ask("hola", [])
    assert "modo ONLINE" in r and "pasa a modo online" not in r


def test_prefijo_online_en_modo_offline_se_rechaza_sin_contactar(entorno_local):
    ai, sel, fake = entorno_local
    hist = []
    r = ai.ask("online: dime el tiempo en Bilbao", hist)
    assert r.startswith("Estás en modo OFFLINE") and "pasa a modo online" in r
    assert hist == [] and not ai._memoria_temporal.hechos.exists()
    assert all(m.llamadas == [] for m in fake.motores.todos.values())
    assert fake.estado["hosts"] == []
    assert sel.modo == "offline"


@pytest.mark.parametrize("prefijo", ["online:", "Online :", "en línea:", "en linea:"])
def test_prefijo_online_en_modo_online_usa_motor_online(entorno_local, prefijo):
    ai, sel, fake = entorno_local
    sel.set_modo("online")
    hist = []
    r = ai.ask(f"{prefijo} dime el tiempo", hist)
    assert r == "respuesta de on_a"
    assert fake.motores.todos["off_a"].llamadas == []
    recibidos, _ = fake.motores.todos["on_a"].llamadas[0]
    assert recibidos[-1]["content"] == "dime el tiempo"   # el prefijo no llega al modelo
    assert hist[0]["content"] == "dime el tiempo"


def test_modo_online_prioridad_local_responde_con_motor_local(entorno_local):
    ai, sel, fake = entorno_local
    sel.set_modo("online")
    assert ai.ask("hola", []) == "respuesta de off_a"
    assert fake.motores.todos["on_a"].llamadas == []


def test_modo_online_prioridad_local_avisa_cuando_usa_el_online(entorno_local, capsys):
    ai, sel, fake = entorno_local
    sel.set_modo("online")
    for nombre in ("off_a", "off_b"):
        fake.motores.todos[nombre].disponible_ok = False
    assert ai.ask("hola", []) == "respuesta de on_a"
    assert "ningún motor local ha respondido" in capsys.readouterr().out


def test_estado_explica_la_politica(entorno_local):
    ai, sel, fake = entorno_local
    r = ai.ask("estado", [])
    assert r.startswith("Modo actual: OFFLINE — Sólo motores locales")
    assert "No se pasará a online sin tu orden explícita" in r
    sel.set_modo("online")
    r = ai.ask("estado", [])
    assert "AUTORIZADO" in r and "Prioridad local" in r


def test_cambio_a_online_deja_claro_que_es_autorizacion(entorno_local):
    ai, sel, fake = entorno_local
    r = ai.ask("pasa a modo online", [])
    assert r.startswith("Modo cambiado a ONLINE (autorizado por ti).")
    assert "Prioridad local" in r and "Motor activo: off_a" in r
    r = ai.ask("pasa a modo offline", [])
    assert r.startswith("Modo cambiado a OFFLINE.") and "Aislamiento" in r


def test_get_selector_real_arranca_en_offline(ai_engine_aislado, monkeypatch):
    """Con la configuración del proyecto B.A.I arranca en modo offline."""
    monkeypatch.setattr(ai_engine_aislado, "_selector", None)
    assert ai_engine_aislado.get_selector().modo == "offline"


# --------------------------------------------------------------------------- aislamiento de proceso
def test_en_proceso_aislado_no_se_puede_autorizar_online_sin_reiniciar(entorno_local, monkeypatch):
    from core import aislamiento
    ai, sel, fake = entorno_local
    monkeypatch.setattr(aislamiento, "en_namespace_aislado", lambda: True)
    r = ai.ask("pasa a modo online", [])
    assert r.startswith("Sigo en modo OFFLINE.") and "python bai.py --online" in r
    assert sel.modo == "offline"
    assert fake.motores.todos["on_a"].llamadas == [] and fake.estado["hosts"] == []


def test_estado_distingue_el_nivel_de_aislamiento(entorno_local, monkeypatch):
    from core import aislamiento
    ai, sel, fake = entorno_local
    r = ai.ask("estado", [])
    assert "Aislamiento PYTHON" in r and "NO cubre subprocesos ni código nativo" in r
    monkeypatch.setattr(aislamiento, "en_namespace_aislado", lambda: True)
    r = ai.ask("estado", [])
    assert "Aislamiento de PROCESO" in r and "kernel" in r



# --------------------------------------------------------------------------- autorización explícita a través de ask()
@pytest.mark.parametrize("texto", NO_COMANDOS)
def test_ask_no_autoriza_online_con_frases_que_solo_mencionan_el_comando(entorno_local, texto):
    """Regresión: 'No quiero cambiar a modo online' y similares cambiaban el modo y
    respondían 'autorizado por ti'. Deben tratarse como mensajes normales en modo
    offline: responde el motor local, el modo no cambia y no se toca la red."""
    ai, sel, fake = entorno_local
    hist = []
    r = ai.ask(texto, hist)
    assert "autorizado" not in r.lower() and "Modo cambiado" not in r
    assert r == "respuesta de off_a"                         # fue al motor local como mensaje normal
    assert sel.modo == "offline"
    assert fake.motores.todos["on_a"].llamadas == [] and fake.estado["hosts"] == []
    assert hist[0]["content"] == texto and len(hist) == 2    # y queda en el historial como conversación


@pytest.mark.parametrize("texto,esperado", COMANDOS)
def test_ask_solo_los_comandos_explicitos_cambian_el_modo(entorno_local, texto, esperado):
    ai, sel, fake = entorno_local
    sel.set_modo("offline" if esperado == "online" else "online")
    hist = []
    r = ai.ask(texto, hist)
    assert r.startswith("Modo cambiado a " + esperado.upper())
    assert ("autorizado por ti" in r) == (esperado == "online")
    assert sel.modo == esperado and hist == []


def test_ask_pregunta_sobre_el_comando_en_modo_online_no_cambia_a_offline(entorno_local):
    ai, sel, fake = entorno_local
    sel.set_modo("online")
    r = ai.ask("¿qué pasa si digo 'pasa a modo offline'?", [])
    assert r == "respuesta de off_a" and sel.modo == "online"
