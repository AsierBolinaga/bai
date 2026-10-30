"""Cancelacion real de un backend bloqueado, sin modelos, audio ni servicios online."""
import importlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time

import pytest

from core.cancelacion import GeneracionCancelada, cancelacion_turno
from core.generacion_worker import ProcesoMotor
from core.motors.base import MotorError


@pytest.fixture
def motor(tmp_path, monkeypatch):
    modulo = tmp_path / "motor_cancelable_fake.py"
    modulo.write_text("""
import json, os, signal, socket, subprocess, sys, tempfile, time
from pathlib import Path
from core.contexto import notificar_contexto
NOMBRE = "off_a"
TIPO = "offline"
cargas = 0
def disponible(config):
    return True, ""
def cargar_modelo(config):
    global cargas
    cargas += 1
def responder(messages, config):
    global cargas
    if not cargas:
        cargar_modelo(config)
    texto = messages[-1]["content"]
    if texto == "temporal":
        carpeta = tempfile.mkdtemp(prefix="bai-copilot-prueba-")
        Path(carpeta, "prueba.txt").write_text("datos sinteticos")
        return carpeta
    if texto == "ruido":
        os.write(1, b"log nativo\\n")
    if texto == "salir":
        os._exit(9)
    if texto == "bloquear":
        hijo = subprocess.Popen([sys.executable, "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        Path(config["marca"]).write_text(json.dumps([os.getpid(), hijo.pid]))
        while True:
            time.sleep(0.01)
    if texto == "red":
        try:
            socket.create_connection(("203.0.113.1", 443), timeout=0.1)
        except OSError:
            pass
    if texto == "error":
        raise RuntimeError("fallo simulado")
    notificar_contexto("aviso de prueba")
    return f"{os.getpid()}:{cargas}:{texto}"
""", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    importlib.invalidate_caches()
    sys.modules.pop("motor_cancelable_fake", None)
    return importlib.import_module("motor_cancelable_fake"), {"marca": str(tmp_path / "inicio.json")}


@pytest.fixture
def worker():
    proceso = ProcesoMotor()
    yield proceso
    proceso.cerrar()


def esperar_marca(config):
    limite = time.monotonic() + 5
    ruta = Path(config["marca"])
    while time.monotonic() < limite:
        if ruta.exists() and ruta.stat().st_size:
            return json.loads(ruta.read_text())
        time.sleep(0.01)
    pytest.fail("el backend no entró en la generación")


def ejecutando(pid):
    ruta = Path(f"/proc/{pid}/stat")
    return ruta.exists() and ruta.read_text().split()[2] != "Z"


def test_precarga_cache_y_avisos_reutilizan_proceso(worker, motor):
    modulo, config = motor
    worker.ejecutar(modulo.__name__, config, offline=True)
    avisos = []
    uno = worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "uno"}],
                         offline=True, avisar=avisos.append)
    dos = worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "dos"}],
                         offline=True, avisar=avisos.append)
    assert uno.split(":")[:2] == dos.split(":")[:2]
    assert uno.split(":")[1] == "1"
    assert avisos == ["aviso de prueba", "aviso de prueba"]


@pytest.mark.parametrize("offline", [True, False])
def test_cancelar_mata_backend_y_sus_hijos_y_permite_otro_turno(worker, motor, offline):
    modulo, config = motor
    evento, resultado = threading.Event(), []

    def generar():
        with cancelacion_turno(evento):
            try:
                worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "bloquear"}],
                                offline=offline)
            except GeneracionCancelada:
                resultado.append("cancelada")

    hilo = threading.Thread(target=generar, daemon=True)
    hilo.start()
    pid, hijo = esperar_marca(config)
    inicio = time.monotonic()
    evento.set()
    hilo.join(2)
    assert not hilo.is_alive() and resultado == ["cancelada"]
    assert time.monotonic() - inicio < 1.5
    assert not ejecutando(pid) and not ejecutando(hijo)
    texto = worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "nueva"}],
                            offline=offline, avisar=lambda a: None)
    assert texto.endswith(":1:nueva") and int(texto.split(":")[0]) != pid


def test_cerrar_interrumpe_backend_que_ignora_sigterm(worker, motor):
    modulo, config = motor
    errores = []

    def generar():
        try:
            worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "bloquear"}],
                            offline=True)
        except MotorError as error:
            errores.append(str(error))

    hilo = threading.Thread(target=generar, daemon=True)
    hilo.start()
    pid, hijo = esperar_marca(config)
    inicio = time.monotonic()
    worker.cerrar()
    hilo.join(1)
    assert time.monotonic() - inicio < 1.5 and not hilo.is_alive()
    assert errores and not ejecutando(pid) and not ejecutando(hijo)


def test_guardia_offline_del_hijo_descarta_respuesta_tras_intento_de_red(worker, motor):
    modulo, config = motor
    with pytest.raises(MotorError, match="intentó acceder a la red"):
        worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "red"}], offline=True)


def test_error_del_worker_es_explicito(worker, motor):
    modulo, config = motor
    with pytest.raises(MotorError, match="fallo simulado"):
        worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "error"}], offline=True)


def test_salida_nativa_no_contamina_ipc(worker, motor):
    modulo, config = motor
    assert worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "ruido"}],
                           offline=True, avisar=lambda a: None).endswith(":ruido")


def test_fin_inesperado_del_worker_informa_error(worker, motor):
    modulo, config = motor
    with pytest.raises(MotorError, match="terminó sin respuesta"):
        worker.ejecutar(modulo.__name__, config, [{"role": "user", "content": "salir"}], offline=True)


def test_cierre_limpia_temporales_propios_del_motor(worker, motor):
    modulo, config = motor
    carpeta = Path(worker.ejecutar(
        modulo.__name__, config, [{"role": "user", "content": "temporal"}], offline=False))
    assert (carpeta / "prueba.txt").is_file()
    worker.cerrar()
    assert not carpeta.exists()


def test_ctrl_c_termina_worker_y_hijos_y_permite_otra_generacion(motor):
    modulo, config = motor
    programa = f"""
from core.generacion_worker import ProcesoMotor
w = ProcesoMotor()
try:
    try:
        w.ejecutar({modulo.__name__!r}, {config!r},
                   [{{"role": "user", "content": "bloquear"}}], offline=True)
    except KeyboardInterrupt:
        print("cancelado", flush=True)
    print(w.ejecutar({modulo.__name__!r}, {config!r},
                    [{{"role": "user", "content": "nueva"}}], offline=True,
                    avisar=lambda a: None), flush=True)
finally:
    w.cerrar()
"""
    proceso = subprocess.Popen([sys.executable, "-c", programa],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        pid, hijo = esperar_marca(config)
        inicio = time.monotonic()
        proceso.send_signal(signal.SIGINT)
        salida, error = proceso.communicate(timeout=3)
        assert proceso.returncode == 0, error
        assert time.monotonic() - inicio < 2
        assert "cancelado" in salida and ":1:nueva" in salida
        assert not ejecutando(pid) and not ejecutando(hijo)
    finally:
        if proceso.poll() is None:
            proceso.kill()
            proceso.communicate(timeout=2)


@pytest.mark.parametrize("fase", ["crear", "enviar", "recibir", "limpiar", "finalizar"])
def test_ctrl_c_en_transiciones_no_deja_worker_y_restaura_handler(motor, fase):
    modulo, config = motor
    programa = f"""
import os, signal, threading, time
from core.generacion_worker import ProcesoMotor
w = ProcesoMotor()
iniciar = w._iniciar
terminar = w._terminar
fase = {fase!r}
handler = signal.getsignal(signal.SIGINT)
pids = []
def interrumpir():
    os.kill(os.getpid(), signal.SIGINT)
thread_original = threading.Thread
def thread(*a, **kw):
    hilo = thread_original(*a, **kw)
    if fase == 'finalizar' and kw.get('name') == 'bai-motor-envio':
        join = hilo.join
        def esperar(*args, **kwargs):
            join(*args, **kwargs)
            interrumpir()
        hilo.join = esperar
    return hilo
threading.Thread = thread
def crear():
    iniciar()
    pids.append(w._proceso.pid)
    if fase == 'crear':
        interrumpir()
    elif fase == 'enviar':
        stdin = w._proceso.stdin
        class Entrada:
            def write(self, texto):
                interrumpir()
                return stdin.write(texto)
            def flush(self):
                return stdin.flush()
            def close(self):
                return stdin.close()
        w._proceso.stdin = Entrada()
    elif fase in ('recibir', 'limpiar'):
        eventos = w._eventos
        class Eventos:
            def get(self, **kw):
                interrumpir()
                return eventos.get(**kw)
        w._eventos = Eventos()
def limpiar():
    if fase == 'limpiar':
        interrumpir()
        interrumpir()
    terminar()
w._iniciar = crear
w._terminar = limpiar
try:
    try:
        w.ejecutar({modulo.__name__!r}, {config!r},
                   [{{"role": "user", "content": "nueva"}}], offline=True,
                   avisar=lambda a: None)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError('no se recibio Ctrl+C')
    assert w._proceso is None
    assert signal.getsignal(signal.SIGINT) == handler
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError('worker sigue vivo')
    w._iniciar, w._terminar = iniciar, terminar
    threading.Thread = thread_original
    print(w.ejecutar({modulo.__name__!r}, {config!r},
                    [{{"role": "user", "content": "siguiente"}}], offline=True,
                    avisar=lambda a: None), flush=True)
finally:
    threading.Thread = thread_original
    w._terminar = terminar
    w.cerrar()
"""
    resultado = subprocess.run([sys.executable, "-c", programa], capture_output=True,
                               text=True, timeout=8)
    assert resultado.returncode == 0, resultado.stderr
    assert ":1:siguiente" in resultado.stdout


def test_lanzador_real_ctrl_c_cancela_sin_matar_sesion(tmp_path):
    import yaml
    from config.motors_config import PROJECT_ROOT

    for nombre in ("core", "config"):
        shutil.copytree(PROJECT_ROOT / nombre, tmp_path / nombre,
                        ignore=shutil.ignore_patterns("*.local.*", "facts.yaml", "__pycache__"))
    shutil.copy2(PROJECT_ROOT / "bai.py", tmp_path / "bai.py")
    (tmp_path / "config/data/system_prompt.txt").write_text("Eres un asistente de prueba.")
    (tmp_path / "config/data/user_profile.yaml").write_text("{}")
    config_path = tmp_path / "config/motors_config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["offline"]["motor"] = "llama_cpp"
    config["offline"]["fallback"] = []
    config["offline"]["motores"]["llama_cpp"].update({
        "descargar_al_arrancar": False, "model_path": "prueba.gguf"})
    config_path.write_text(yaml.safe_dump(config))
    (tmp_path / "prueba.gguf").write_bytes(b"GGUF\x03\0\0\0")
    marca = tmp_path / "inicio.json"
    (tmp_path / "llama_cpp.py").write_text(f"""
import json, os, signal, time
from pathlib import Path
class Llama:
    def __init__(self, **kw):
        pass
    def create_chat_completion(self, messages, **kw):
        if messages[-1]["content"] == "bloquear":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            Path({str(marca)!r}).write_text(json.dumps([os.getpid()]))
            while True:
                time.sleep(0.01)
        return {{"choices": [{{"message": {{"content": "respuesta sintetica"}}}}]}}
    def close(self):
        pass
""")
    proceso = subprocess.Popen(
        [sys.executable, str(tmp_path / "bai.py"), "--offline", "--aislamiento", "python"],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=str(tmp_path), PYTHONUNBUFFERED="1"),
        start_new_session=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lineas = []
    disponible = threading.Event()

    def leer():
        for linea in proceso.stdout:
            lineas.append(linea)
            if "OK offline" in linea:
                disponible.set()

    lector = threading.Thread(target=leer, daemon=True)
    lector.start()
    pid_motor = None
    try:
        limite = time.monotonic() + 5
        while not disponible.wait(0.05):
            assert time.monotonic() < limite, "".join(lineas)
            proceso.stdin.write("estado\n")
            proceso.stdin.flush()
        proceso.stdin.write("bloquear\n")
        proceso.stdin.flush()
        pid_motor, = esperar_marca({"marca": str(marca)})
        os.killpg(proceso.pid, signal.SIGINT)
        proceso.stdin.write("nueva\nsalir\n")
        proceso.stdin.flush()
        proceso.stdin.close()
        proceso.wait(timeout=10)
        lector.join(timeout=2)
        assert not lector.is_alive()
        salida, error = "".join(lineas), proceso.stderr.read()
        assert proceso.returncode == 0, error
        assert "Generación cancelada" in salida and "respuesta sintetica" in salida
        assert not ejecutando(pid_motor)
        historial = json.loads((tmp_path / "history/historial.json").read_text())
        assert historial == [
            {"role": "user", "content": "nueva"},
            {"role": "assistant", "content": "respuesta sintetica"}]
    finally:
        if proceso.poll() is None:
            os.killpg(proceso.pid, signal.SIGKILL)
            proceso.wait(timeout=2)
        lector.join(timeout=2)
        proceso.stdout.close()
        proceso.stderr.close()
        if not proceso.stdin.closed:
            proceso.stdin.close()
        if pid_motor is not None and ejecutando(pid_motor):
            os.killpg(pid_motor, signal.SIGKILL)


def test_selector_cancelado_no_intenta_fallback_ni_guarda_turno(worker, motor, monkeypatch):
    from core import ai_engine
    from core.model_selector import ModelSelector
    from core.ui_controlador import ControladorChat, MENSAJE_CANCELADO
    from tests.conftest import config_local
    modulo, opciones = motor
    cfg = config_local("offline")
    cfg["offline"]["motores"]["off_a"].update(opciones)
    consultas = []

    def obtener(nombre):
        consultas.append(nombre)
        return modulo

    selector = ModelSelector(cfg, obtener_motor=obtener)
    selector._worker = worker
    monkeypatch.setattr(ai_engine, "_selector", selector)
    monkeypatch.setattr(ai_engine, "get_memory_context", lambda: "")
    guardados = []
    controlador = ControladorChat(historial=[], guardar=lambda h: guardados.append(list(h)) or True)
    recibidos = []
    try:
        hilo = controlador.enviar_en_hilo("bloquear", recibidos.append)
        esperar_marca(opciones)
        controlador.cancelar()
        hilo.join(2)
        assert not hilo.is_alive()
        assert [t.texto for t in recibidos] == [MENSAJE_CANCELADO]
        assert not controlador.historial and not guardados and consultas == ["off_a"]
        turno = controlador.enviar("nueva")
        assert ":1:nueva" in turno.texto and len(controlador.historial) == 2
        assert len(guardados) == 1
    finally:
        selector.cerrar()
