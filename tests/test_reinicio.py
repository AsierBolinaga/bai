from types import SimpleNamespace
import signal

import pytest

import bai
from core import ai_engine, reinicio, preparar_modelo


@pytest.mark.parametrize("actual,nuevo,aislamiento,esperado", [
    ("offline", "online", "proceso", "online"),
    ("online", "offline", "proceso", "offline"),
    ("offline", "offline", "proceso", None),
    ("offline", "online", "python", None),
])
def test_transiciones_reinician_solo_si_necesario(monkeypatch, actual, nuevo, aislamiento, esperado):
    monkeypatch.setattr(ai_engine, "_selector", SimpleNamespace(
        modo=actual, config={"aislamiento_offline": aislamiento}))
    assert reinicio.modo_reinicio(f"pasa a modo {nuevo}") == esperado
    assert reinicio.modo_reinicio("no pases a modo online") is None


def test_supervisor_relanza_sin_preparacion_ni_red_en_ningun_modo(monkeypatch):
    codigos = iter([reinicio.ONLINE, reinicio.OFFLINE, 0])
    llamadas, preparados = [], []

    def ejecutar(args):
        assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN
        llamadas.append(args)
        return SimpleNamespace(returncode=next(codigos))

    monkeypatch.setattr(bai.subprocess, "run", ejecutar)
    monkeypatch.setattr(preparar_modelo, "preparar_modelo", lambda cfg: preparados.append(cfg))
    assert bai.main(["--ui"]) == 0
    assert signal.getsignal(signal.SIGINT) == signal.default_int_handler
    assert len(llamadas) == 3 and preparados == []
    assert "--online" in llamadas[1] and "--offline" not in llamadas[1]
    assert "--offline" in llamadas[2] and "--online" not in llamadas[2]
    assert all("--sesion" in c and "--ui" in c for c in llamadas)


@pytest.mark.parametrize("error", ["sin red", "Falta llama-cpp-python", "SHA256 incorrecto", "sin espacio"])
def test_preparacion_explicita_fallida_no_abre_sesion(monkeypatch, capsys, error):
    from core.motors.base import MotorError
    def fallar(cfg, *, permitir_descarga):
        assert permitir_descarga
        raise MotorError(error)
    llamadas = []
    monkeypatch.setattr(preparar_modelo, "preparar_modelo", fallar)
    monkeypatch.setattr(bai.subprocess, "run",
                        lambda args: llamadas.append(args) or SimpleNamespace(returncode=0))
    assert bai.main(["--preparar-modelo"]) == 1
    assert llamadas == []
    assert error in capsys.readouterr().err


def test_preparacion_explicita_termina_sin_abrir_chat(monkeypatch):
    llamadas = []
    monkeypatch.setattr(preparar_modelo, "preparar_modelo",
                        lambda cfg, **kw: llamadas.append(kw))
    monkeypatch.setattr(bai.subprocess, "run", lambda args: pytest.fail("no debe abrir chat"))
    assert bai.main(["--preparar-modelo"]) == 0
    assert llamadas == [{"permitir_descarga": True}]


@pytest.mark.parametrize("ui", [False, True])
def test_sesion_inicia_preparacion_sin_esperar_antes_de_abrir(
        monkeypatch, selector_fake, ui):
    from core import assistant, ui_tk
    cfg = selector_fake.crear().config
    cfg["offline"]["fallback"] = []
    cfg["offline"]["motores"]["off_a"]["descargar_al_arrancar"] = True
    sel = selector_fake.crear(cfg)
    monkeypatch.setattr(ai_engine, "_selector", sel)
    monkeypatch.setattr(bai, "preparar_arranque", lambda argv: cfg)
    cargas = []
    monkeypatch.setattr(sel, "iniciar_carga_local", lambda: cargas.append("segundo plano"))
    monkeypatch.setattr(sel, "precargar", lambda *a: pytest.fail("precarga sincrona"))
    monkeypatch.setattr(preparar_modelo, "preparar_modelo", lambda *a: pytest.fail("verificacion sincrona"))
    raiz = SimpleNamespace(destroy=lambda: pytest.fail("no debe cerrar la ventana"))
    monkeypatch.setattr(ui_tk, "crear_raiz", lambda: raiz)
    inicios = []
    monkeypatch.setattr(ui_tk, "iniciar_ui", lambda **kw: inicios.append(kw) or 0)
    monkeypatch.setattr(assistant, "run_assistant", lambda: inicios.append("cli") or 0)
    argv = ["--sesion", "--ui"] if ui else ["--sesion"]
    assert bai.main(argv) == 0
    assert len(inicios) == 1
    assert cargas == ["segundo plano"]
    if ui:
        assert inicios[0] == {"raiz": raiz}
    assert selector_fake.estado["hosts"] == []


def test_sesion_online_no_inicia_precarga(monkeypatch, selector_fake):
    from core import assistant
    sel = selector_fake.crear()
    cfg = sel.config
    cfg["modo_por_defecto"] = "online"
    monkeypatch.setattr(bai, "preparar_arranque", lambda argv: cfg)
    monkeypatch.setattr(ai_engine, "_selector", sel)
    monkeypatch.setattr(sel, "iniciar_carga_local", lambda: pytest.fail("precarga online"))
    monkeypatch.setattr(assistant, "run_assistant", lambda: 0)
    assert bai.main(["--sesion"]) == 0


def test_sesion_real_sin_modelo_ni_red_permite_ayuda_memoria_y_estado(tmp_path):
    import shutil
    import subprocess
    import sys
    from config.motors_config import PROJECT_ROOT

    for nombre in ("core", "config"):
        shutil.copytree(PROJECT_ROOT / nombre, tmp_path / nombre,
                        ignore=shutil.ignore_patterns("*.local.*", "facts.yaml", "__pycache__"))
    shutil.copy2(PROJECT_ROOT / "bai.py", tmp_path / "bai.py")
    programa = f"""
import builtins
import requests
def prohibido(*a, **kw):
    raise AssertionError("El arranque intentó descargar o comprobar conectividad")
requests.get = prohibido
import socket
socket.create_connection = prohibido
import bai
import time
def entradas():
    yield "estado"
    yield "ayuda"
    yield "recuerda que mi color es azul"
    yield "¿cuál es mi color?"
    from core.ai_engine import get_selector
    limite = time.monotonic() + 5
    while get_selector().estado_carga_local()["estado"] in ("preparando", "cancelando"):
        assert time.monotonic() < limite
        time.sleep(0.01)
    yield "estado"
    yield "salir"
cola = entradas()
builtins.input = lambda *_: next(cola)
raise SystemExit(bai.main(["--sesion", "--offline", "--aislamiento", "python"]))
"""
    resultado = subprocess.run([sys.executable, "-c", programa], cwd=tmp_path,
                               capture_output=True, text=True, timeout=30)
    assert resultado.returncode == 0, resultado.stderr
    assert "Modo degradado" in resultado.stdout
    assert "--preparar-modelo" in resultado.stdout
    assert "Modo actual: OFFLINE" in resultado.stdout
    assert "Boli Artificial Intelligence" in resultado.stdout
    assert "azul" in resultado.stdout
    assert "Agur, Boli" in resultado.stdout
    assert not (tmp_path / "models").exists()
    assert (tmp_path / "config/data/facts.yaml").is_file()
    assert (tmp_path / "history/historial.json").is_file()
