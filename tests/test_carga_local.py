"""Arranque con un motor bloqueado, sin red ni modelos reales."""
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from core import ai_engine
from core.model_selector import ModelSelector
from core.motors import registry
from tests.conftest import config_local


def esperar(condicion, segundos=5):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return
        time.sleep(0.01)
    pytest.fail("la preparación no alcanzó el estado esperado")


@pytest.fixture
def carga(monkeypatch, tmp_path):
    modulo = tmp_path / "motor_arranque_fake.py"
    modulo.write_text("""
import json, os, signal, socket, time
from pathlib import Path
from core import preparar_modelo
TIPO = "offline"
cargas = 0
def fase(config, nombre):
    if config.get("fase") == nombre:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        Path(config["marca"]).write_text(json.dumps(os.getpid()))
        while True:
            time.sleep(0.01)
def verificar(config, **kw):
    opciones = config["offline"]["motores"]["off_a"]
    fase(opciones, "verificar")
    if opciones.get("error"):
        raise RuntimeError("SHA256 incorrecto simulado")
preparar_modelo.preparar_modelo = verificar
def disponible(config):
    fase(config, "disponible")
    return not config.get("ausente"), "modelo ausente"
def cargar_modelo(config):
    global cargas
    fase(config, "cargar")
    if config.get("red"):
        try:
            socket.create_connection(("203.0.113.1", 443), timeout=0.1)
        except OSError:
            pass
    cargas += 1
def responder(messages, config):
    return f"{os.getpid()}:{cargas}:respuesta"
""")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setitem(registry.MOTORES, "off_a", "motor_arranque_fake")
    cfg = config_local("offline")
    cfg["offline"]["fallback"] = []
    opciones = cfg["offline"]["motores"]["off_a"]
    opciones.update(descargar_al_arrancar=True, marca=str(tmp_path / "marca.json"))
    selectores = []

    def crear(**kw):
        opciones.update(kw)
        sel = ModelSelector(cfg, comprobar_conexion=lambda h: pytest.fail("consulta de red inesperada"))
        selectores.append(sel)
        sel.iniciar_carga_local()
        return sel

    yield crear, opciones
    for sel in selectores:
        sel.cerrar()


@pytest.mark.parametrize("fase", ["disponible", "verificar", "cargar"])
def test_plazo_incluye_disponibilidad_verificacion_y_carga(carga, monkeypatch, fase):
    from core import carga_local
    monkeypatch.setattr(carga_local, "PLAZO_CARGA_SEGUNDOS", 0.8)
    crear, opciones = carga
    inicio = time.monotonic()
    sel = crear(fase=fase)
    assert time.monotonic() - inicio < 0.3
    esperar(lambda: Path(opciones["marca"]).exists())
    pid = json.loads(Path(opciones["marca"]).read_text())
    assert "segundo plano" in ai_engine.describir_estado(sel)
    esperar(lambda: sel.estado_carga_local()["estado"] == "error", segundos=3)
    assert "plazo máximo" in sel.estado_carga_local()["detalle"]
    assert time.monotonic() - inicio < 3
    assert not Path(f"/proc/{pid}").exists()
    assert sel._carga_local.worker._proceso is None
    assert "Modo degradado" in " ".join(sel.avisos_carga_local())
    assert not sel.seleccionar()[0]


def test_carga_correcta_conserva_modelo_y_worker(carga):
    crear, _ = carga
    sel = crear()
    esperar(lambda: sel.estado_carga_local()["estado"] == "listo")
    pid = sel._carga_local.worker._proceso.pid
    for _ in range(2):
        assert sel.responder([{"role": "user", "content": "hola"}]).texto == f"{pid}:1:respuesta"
    assert "preparado" in " ".join(sel.avisos_carga_local())
    assert sel.avisos_carga_local() == []


@pytest.mark.parametrize("opciones", [{"ausente": True}, {"error": True}, {"red": True}])
def test_error_de_preparacion_inhabilita_sin_reintentos(carga, opciones):
    crear, _ = carga
    sel = crear(**opciones)
    esperar(lambda: sel.estado_carga_local()["estado"] == "error")
    detalle = sel.estado_carga_local()["detalle"]
    assert "Modo degradado" in detalle
    assert sel._carga_local.worker._proceso is None
    for _ in range(2):
        assert sel.seleccionar()[0] is None
        assert detalle in ai_engine.describir_estado(sel)


@pytest.mark.parametrize("accion", ["cancelar", "online", "cerrar"])
def test_interrumpir_carga_no_espera_al_modelo(carga, accion):
    crear, opciones = carga
    sel = crear(fase="cargar")
    esperar(lambda: Path(opciones["marca"]).exists())
    inicio = time.monotonic()
    if accion == "online":
        sel.set_modo("online")
        assert sel.modo == "online"
    elif accion == "cancelar":
        sel.cancelar_carga_local()
    else:
        sel.cerrar()
    assert time.monotonic() - inicio < 1.5
    esperar(lambda: sel.estado_carga_local()["estado"] == "error")
    assert "cancelada" in sel.estado_carga_local()["detalle"] or accion == "cerrar"
    assert sel._carga_local.worker._proceso is None


def test_ayuda_memoria_y_online_disponibles_durante_carga(carga, monkeypatch, memoria_temporal):
    crear, opciones = carga
    sel = crear(fase="cargar")
    monkeypatch.setattr(ai_engine, "_selector", sel)
    esperar(lambda: Path(opciones["marca"]).exists())
    historial = []
    inicio = time.monotonic()
    assert "Boli Artificial Intelligence" in ai_engine.ask("ayuda", historial)
    assert "Hecho guardado" in ai_engine.ask("recuerda que mi color es azul", historial)
    assert "azul" in ai_engine.ask("¿cuál es mi color?", historial)
    assert "segundo plano" in ai_engine.ask("estado", historial)
    assert not historial
    assert time.monotonic() - inicio < 0.5
    assert "Cancelando" in ai_engine.ask("cancelar carga", historial)
    esperar(lambda: sel.estado_carga_local()["estado"] == "error")


def test_online_responde_sin_esperar_limpieza_de_precarga(carga, monkeypatch):
    crear, opciones = carga
    sel = crear(fase="cargar")
    esperar(lambda: Path(opciones["marca"]).exists())
    motor = SimpleNamespace(
        TIPO="online", disponible=lambda cfg: (True, ""),
        responder=lambda mensajes, cfg: "respuesta online simulada")
    monkeypatch.setattr(sel, "_obtener_motor", lambda nombre: motor)
    monkeypatch.setattr(sel, "_comprobar_conexion", lambda host: True)
    inicio = time.monotonic()
    sel.set_modo("online")
    respuesta = sel.responder([{"role": "user", "content": "hola"}], fallback_offline=False)
    assert respuesta.texto == "respuesta online simulada" and respuesta.tipo == "online"
    assert time.monotonic() - inicio < 0.3
    esperar(lambda: sel.estado_carga_local()["estado"] == "error")


def test_sin_precarga_solo_comprueba_y_no_carga(carga):
    crear, _ = carga
    sel = crear(descargar_al_arrancar=False)
    esperar(lambda: sel.estado_carga_local()["estado"] == "listo")
    assert "bajo demanda" in sel.estado_carga_local()["detalle"]
    pid = sel._carga_local.worker._proceso.pid
    assert sel.responder([{"role": "user", "content": "hola"}]).texto == f"{pid}:0:respuesta"


def test_motor_desconocido_tambien_genera_aviso_visible(carga, monkeypatch):
    crear, _ = carga
    monkeypatch.delitem(registry.MOTORES, "off_a")
    sel = crear()
    esperar(lambda: sel.estado_carga_local()["estado"] == "error")
    assert "no registrado" in " ".join(sel.avisos_carga_local())
    assert sel.seleccionar()[0] is None


def test_ui_real_abre_y_responde_mientras_modelo_bloqueado(carga, monkeypatch, memoria_temporal):
    import gc
    import tkinter as tk
    from core.ui_controlador import ControladorChat
    from core.ui_tk import VentanaBai
    from core import memory_engine
    crear, opciones = carga
    sel = crear(fase="cargar")
    monkeypatch.setattr(ai_engine, "_selector", sel)
    monkeypatch.setattr(memory_engine, "save_chat_history", lambda h: True)
    esperar(lambda: Path(opciones["marca"]).exists())
    gc.collect()
    try:
        raiz = tk.Tk()
    except tk.TclError:
        pytest.skip("sin pantalla")
    v = VentanaBai(ControladorChat(historial=[], guardar=lambda h: True), raiz)
    try:
        raiz.update()
        assert v.boton_cancelar_carga.winfo_ismapped()
        assert "Preparando" in v.estado_carga.cget("text")
        latidos = []
        raiz.after(1, lambda: latidos.append(True))
        v.enviar("ayuda")
        limite = time.monotonic() + 2
        while time.monotonic() < limite:
            raiz.update()
            if "Boli Artificial Intelligence, tu asistente" in v.chat.get("1.0", "end"):
                break
            time.sleep(0.01)
        assert latidos and not v.controlador.ocupado
        assert "Boli Artificial Intelligence, tu asistente" in v.chat.get("1.0", "end")
        v.boton_cancelar_carga._comando()
        esperar(lambda: sel.estado_carga_local()["estado"] == "error")
        v._actualizar_carga_local()
        assert "cancelada" in v.chat.get("1.0", "end")
        assert not v.boton_cancelar_carga.winfo_ismapped()
    finally:
        raiz.destroy()
