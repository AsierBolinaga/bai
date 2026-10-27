"""
Pruebas de integración de la CLI (core/assistant.run_assistant) con backend
controlado (motores fake a través del selector y ai_engine reales) y
almacenamiento temporal (historial y perfil de memoria en tmp_path).
Cubren cambios de modo, fallo de generación, fallback e integridad de
historial y memoria.
"""
import builtins
import json

import pytest
import yaml

import core.ai_engine as ai
import core.assistant as assistant
import core.memory_engine as memoria
from tests.conftest import config_local


@pytest.fixture
def cli(monkeypatch, tmp_path, selector_fake):
    """Devuelve una función ejecutar(entradas) -> salida, con almacenamiento temporal."""
    historial_dir = tmp_path / "history"
    historial_dir.mkdir()
    perfil = tmp_path / "user_profile.yaml"
    perfil.write_text("aprendido_durante_sesion: {}\n", encoding="utf-8")
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(historial_dir))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(historial_dir / "historial.json"))
    monkeypatch.setattr(memoria, "MEMORY_PATH", str(perfil))

    cfg = config_local("offline")
    cfg["mostrar_motor"] = True
    sel = selector_fake.crear(cfg)
    monkeypatch.setattr(ai, "_selector", sel)
    monkeypatch.setattr(ai, "ultima_respuesta", None)
    historial = []
    monkeypatch.setattr(assistant, "chat_history", historial)

    def ejecutar(entradas, capsys):
        cola = list(entradas)
        monkeypatch.setattr(builtins, "input", lambda *_: cola.pop(0))
        assistant.run_assistant()
        assert cola == [], f"entradas no consumidas: {cola}"
        return capsys.readouterr().out

    def historial_guardado():
        return json.loads((historial_dir / "historial.json").read_text(encoding="utf-8"))

    def perfil_guardado():
        return yaml.safe_load(perfil.read_text(encoding="utf-8"))

    class Entorno:
        pass

    e = Entorno()
    e.ejecutar, e.historial_guardado, e.perfil_guardado = ejecutar, historial_guardado, perfil_guardado
    e.selector, e.fake, e.historial, e.dir = sel, selector_fake, historial, historial_dir
    return e


# --------------------------------------------------------------------------- arranque y modo
def test_arranque_muestra_politica_y_sale_guardando(cli, capsys):
    out = cli.ejecutar(["salir"], capsys)
    assert "Modo actual: OFFLINE — Sólo motores locales." in out
    assert "Aislamiento PYTHON" in out            # sin aislamiento de proceso en el test runner
    assert "Agur" in out
    assert cli.historial_guardado() == []


def test_frases_sobre_el_comando_no_autorizan_online(cli, capsys):
    out = cli.ejecutar([
        "No quiero cambiar a modo online",
        "Explica que significa <<pasa a modo online>>",
        "estado",
        "salir",
    ], capsys)
    assert "autorizado" not in out.lower() and "Modo cambiado" not in out
    assert out.count("[B.A.I] respuesta de off_a") == 2
    assert "Modo actual: OFFLINE" in out and cli.selector.modo == "offline"
    # sin autorización: ni llamadas al motor online ni comprobaciones de conectividad
    assert cli.fake.motores.todos["on_a"].llamadas == [] and cli.fake.estado["hosts"] == []
    guardado = cli.historial_guardado()
    assert [m["content"] for m in guardado if m["role"] == "user"] == [
        "No quiero cambiar a modo online", "Explica que significa <<pasa a modo online>>"]


def test_cambios_de_modo_solo_con_comandos_explicitos(cli, capsys):
    out = cli.ejecutar([
        "pasa a modo online",                       # comando explícito
        "¿qué hace 'pasa a modo offline'?",         # pregunta: sigue en online
        "estado",
        "pasa a modo offline",
        "salir",
    ], capsys)
    assert out.count("Modo cambiado a ONLINE (autorizado por ti)") == 1
    assert out.count("Modo cambiado a OFFLINE") == 1
    assert out.count("autorizado por ti") == 1
    assert "Modo actual: ONLINE — Uso de servicios online AUTORIZADO" in out
    assert cli.selector.modo == "offline"
    guardado = cli.historial_guardado()
    assert [m["content"] for m in guardado] == ["¿qué hace 'pasa a modo offline'?", "respuesta de off_a"]
    assert cli.fake.motores.todos["on_a"].llamadas == []   # prioridad local: el online no generó nada


def test_prefijo_online_respeta_la_autorizacion(cli, capsys):
    out = cli.ejecutar(["online: dime algo", "pasa a modo online", "online: dime algo", "salir"], capsys)
    assert "Estás en modo OFFLINE: no usaré el motor online" in out
    assert "[on_a · modelo-online-a · online]" in out
    assert cli.fake.motores.todos["on_a"].llamadas[0][0][-1]["content"] == "dime algo"
    assert [m["content"] for m in cli.historial_guardado()] == ["dime algo", "respuesta de on_a"]


# --------------------------------------------------------------------------- generación, fallback y etiqueta
def test_respuesta_normal_con_etiqueta_y_historial(cli, capsys):
    out = cli.ejecutar(["hola", "salir"], capsys)
    assert "[B.A.I] respuesta de off_a\n[off_a · a.gguf · offline]" in out
    assert cli.historial_guardado() == [{"role": "user", "content": "hola"},
                                        {"role": "assistant", "content": "respuesta de off_a"}]


def test_fallback_visible_para_el_usuario(cli, capsys):
    cli.fake.motores.todos["off_a"].disponible_ok = False
    cli.fake.motores.todos["off_a"].motivo = "no se encuentra el modelo"
    out = cli.ejecutar(["hola", "salir"], capsys)
    assert "Aviso: motor principal no disponible (off_a (no se encuentra el modelo)). Respondo con off_b" in out
    assert "[off_b · b.gguf · offline · fallback]" in out
    assert cli.historial_guardado()[-1]["content"] == "respuesta de off_b"


def test_fallo_de_generacion_no_corrompe_historial_ni_memoria(cli, capsys):
    from core.motors.base import MotorError
    out = cli.ejecutar(["mi furgoneta es una camper", "salir"], capsys)   # turno correcto: aprende
    assert cli.perfil_guardado()["vida_personal"]["vehiculo"] == "una camper"

    for nombre in ("off_a", "off_b"):
        cli.fake.motores.todos[nombre].error = MotorError("modelo caído")
    out = cli.ejecutar(["mi pareja es Ana", "salir"], capsys)           # turno fallido
    assert "Ningún motor ha podido responder en modo OFFLINE" in out
    assert "off_a: modelo caído" in out and "off_b: modelo caído" in out
    assert "No se ha contactado con ningún servicio externo" in out and "pasa a modo online" in out
    assert cli.selector.modo == "offline"
    # historial: sólo el turno correcto; memoria: sin 'pareja'
    assert [m["content"] for m in cli.historial_guardado()] == ["mi furgoneta es una camper", "respuesta de off_a"]
    assert "pareja" not in cli.perfil_guardado().get("vida_personal", {})
    assert cli.perfil_guardado()["vida_personal"]["vehiculo"] == "una camper"


def test_comandos_de_control_no_contaminan_la_memoria(cli, capsys):
    cli.ejecutar(["pasa a modo online", "estado", "online: hola", "pasa a modo offline", "salir"], capsys)
    perfil = cli.perfil_guardado()
    assert perfil.get("aprendido_durante_sesion", {}) in ({}, None) or "pasa" not in perfil["aprendido_durante_sesion"]
    assert "estado" not in perfil.get("aprendido_durante_sesion", {})


# --------------------------------------------------------------------------- integridad del historial
def test_historial_persiste_entre_sesiones_y_reset_lo_vacia(cli, capsys):
    cli.ejecutar(["primera pregunta", "salir"], capsys)
    assert len(cli.historial_guardado()) == 2
    cli.ejecutar(["segunda pregunta", "salir"], capsys)
    assert [m["content"] for m in cli.historial_guardado() if m["role"] == "user"] == ["primera pregunta", "segunda pregunta"]
    # el contexto enviado al motor incluye el historial previo
    ultimo = cli.fake.motores.todos["off_a"].llamadas[-1][0]
    assert {"role": "user", "content": "primera pregunta"} in ultimo
    cli.ejecutar(["reset", "tercera", "salir"], capsys)
    assert [m["content"] for m in cli.historial_guardado()] == ["tercera", "respuesta de off_a"]


def test_historial_guardado_no_incluye_etiquetas_ni_mensajes_de_sistema(cli, capsys):
    cli.ejecutar(["hola", "estado", "salir"], capsys)
    guardado = cli.historial_guardado()
    assert all(m["role"] in ("user", "assistant") for m in guardado)
    assert all("[off_a" not in m["content"] for m in guardado)
    assert "estado" not in [m["content"] for m in guardado]


def test_interrupcion_con_ctrl_c_guarda_el_historial(cli, capsys, monkeypatch):
    cola = ["hola"]

    def entrada(*_):
        if cola:
            return cola.pop(0)
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", entrada)
    assistant.run_assistant()
    out = capsys.readouterr().out
    assert "Sesión finalizada" in out
    assert [m["content"] for m in cli.historial_guardado()] == ["hola", "respuesta de off_a"]


# --------------------------------------------------------------------------- arranque desde otro directorio
def test_rutas_de_memoria_son_absolutas_y_del_proyecto():
    import os
    from config.motors_config import PROJECT_ROOT
    for ruta in (memoria.HISTORY_DIR, memoria.SESSION_FILE, memoria.MEMORY_PATH):
        assert os.path.isabs(ruta) and ruta.startswith(str(PROJECT_ROOT))


def test_memoria_funciona_desde_otro_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(tmp_path / "h"))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(tmp_path / "h" / "historial.json"))
    (tmp_path / "otro").mkdir()
    monkeypatch.chdir(tmp_path / "otro")
    assert memoria.load_full_history() == []            # crea el directorio configurado, no uno en el CWD
    assert (tmp_path / "h" / "historial.json").exists()
    assert not (tmp_path / "otro" / "history").exists()
    assert isinstance(memoria.get_memory_context(), str)  # perfil real del proyecto, sólo lectura


def test_arranque_real_de_bai_desde_otro_directorio(tmp_path):
    """Ejecuta el arranque completo (arranque + assistant) con CWD ajeno al proyecto,
    almacenamiento temporal y aislamiento Python (sin namespace)."""
    import subprocess
    import sys
    from config.motors_config import PROJECT_ROOT
    programa = f"""
import sys, builtins
sys.path.insert(0, {str(PROJECT_ROOT)!r})
import core.memory_engine as m
m.HISTORY_DIR = {str(tmp_path / 'hist')!r}; m.SESSION_FILE = m.HISTORY_DIR + "/historial.json"
m.MEMORY_PATH = {str(tmp_path / 'perfil.yaml')!r}
open(m.MEMORY_PATH, "w").write("aprendido_durante_sesion: {{}}\\n")
from core.arranque import preparar_arranque
preparar_arranque(["--aislamiento", "python"])
import core.assistant as a
entradas = iter(["estado", "salir"])
builtins.input = lambda *_: next(entradas)
a.run_assistant()
"""
    r = subprocess.run([sys.executable, "-c", programa], cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert "Hola, Usuario" in r.stdout and "Modo actual: OFFLINE" in r.stdout and "Agur" in r.stdout
    assert (tmp_path / "hist" / "historial.json").exists()
    assert not (tmp_path / "history").exists() and not (tmp_path / "config").exists()


# --------------------------------------------------------------------------- bai.sh desde otro directorio
@pytest.fixture
def entorno_bash(tmp_path):
    import os
    import shutil
    import sys
    if not shutil.which("bash"):
        pytest.skip("bash no disponible")
    # PATH con el intérprete de los tests primero (sirve como 'python3' del sistema)
    env = {"PATH": os.path.dirname(sys.executable) + os.pathsep + "/usr/bin:/bin", "HOME": str(tmp_path)}
    return env


def _ejecutar_bai_sh(ruta_script, args, cwd, env):
    import subprocess
    return subprocess.run(["bash", str(ruta_script)] + args, cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=60)


def test_bai_sh_desde_otro_directorio_reenvia_argumentos(tmp_path, entorno_bash):
    from config.motors_config import PROJECT_ROOT
    r = _ejecutar_bai_sh(PROJECT_ROOT / "bai.sh", ["--online", "--help"], tmp_path, entorno_bash)
    assert r.returncode == 0, r.stderr
    assert "Iniciando sesión" in r.stdout
    assert "usage: bai.py" in r.stdout and "--aislamiento" in r.stdout   # llegó a bai.py con los argumentos
    assert not (tmp_path / "history").exists()


def test_bai_sh_a_traves_de_enlace_simbolico_y_ruta_relativa(tmp_path, entorno_bash):
    import os
    from config.motors_config import PROJECT_ROOT
    enlace = tmp_path / "bai-link.sh"
    os.symlink(PROJECT_ROOT / "bai.sh", enlace)
    r = _ejecutar_bai_sh("./bai-link.sh", ["--help"], tmp_path, entorno_bash)
    assert r.returncode == 0, r.stderr
    assert "usage: bai.py" in r.stdout


def test_bai_sh_usa_el_venv_del_proyecto_si_existe(tmp_path, entorno_bash):
    """Copia mínima del script en un 'proyecto' temporal con venv simulado: debe
    activar ESE venv (relativo al script) y ejecutar ESE bai.py, no los del CWD."""
    import os
    import stat
    from config.motors_config import PROJECT_ROOT
    proyecto = tmp_path / "proyecto"
    (proyecto / "venv" / "bin").mkdir(parents=True)
    (proyecto / "venv" / "bin" / "activate").write_text('export BAI_VENV_ACTIVADO="$PWD"\n')
    (proyecto / "bai.py").write_text('import os, sys; print("venv:", os.environ.get("BAI_VENV_ACTIVADO"), "args:", sys.argv[1:])\n')
    script = proyecto / "bai.sh"
    script.write_text((PROJECT_ROOT / "bai.sh").read_text())
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    otro = tmp_path / "otro"
    otro.mkdir()
    (otro / "bai.py").write_text('print("bai.py EQUIVOCADO")\n')
    r = _ejecutar_bai_sh(script, ["--offline", "x y"], otro, entorno_bash)
    assert r.returncode == 0, r.stderr
    assert "EQUIVOCADO" not in r.stdout
    assert f"venv: {otro} args: ['--offline', 'x y']" in r.stdout
    assert "Aviso: no existe" not in r.stdout


# --------------------------------------------------------------------------- persistencia entre procesos
def _programa_sesion(tmp_path, entradas, fichero_recibido):
    """Programa Python autónomo: backend controlado + almacenamiento temporal + CLI real."""
    from config.motors_config import PROJECT_ROOT
    return f"""
import sys, builtins, json, types
sys.path.insert(0, {str(PROJECT_ROOT)!r})
import core.memory_engine as m
m.HISTORY_DIR = {str(tmp_path / 'hist')!r}; m.SESSION_FILE = m.HISTORY_DIR + "/historial.json"
m.MEMORY_PATH = {str(tmp_path / 'perfil.yaml')!r}
import os
if not os.path.exists(m.MEMORY_PATH):
    open(m.MEMORY_PATH, "w").write("aprendido_durante_sesion: {{}}\\n")

# backend controlado: registra lo que recibe y responde de forma determinista
motor = types.ModuleType("tests.fakes.registrador")
motor.NOMBRE, motor.TIPO = "registrador", "offline"
motor.disponible = lambda cfg: (True, "")
def responder(messages, cfg):
    json.dump(messages, open({str(fichero_recibido)!r}, "w"))
    return "respuesta a: " + messages[-1]["content"]
motor.responder = responder
sys.modules["tests.fakes.registrador"] = motor
from core.motors import registry
registry.registrar_motor("registrador", "tests.fakes.registrador")

from config import motors_config as mc
mc.SOBRESCRITURAS["aislamiento_offline"] = "python"
from core.model_selector import ModelSelector
cfg = mc.cargar_motors_config()
cfg["offline"] = {{"motor": "registrador", "fallback": [], "max_mensajes_contexto": None, "motores": {{"registrador": {{"modelo": "reg-1"}}}}}}
cfg["mostrar_motor"] = False
import core.ai_engine as ai
ai.set_selector(ModelSelector(config=cfg))
import core.assistant as a
entradas = iter({entradas!r})
builtins.input = lambda *_: next(entradas)
a.run_assistant()
"""


def test_historial_persiste_entre_dos_procesos_independientes(tmp_path):
    import json
    import subprocess
    import sys
    (tmp_path / "hist").mkdir()
    recibido = tmp_path / "recibido.json"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}

    # Proceso 1: una conversación y salida normal (guarda el historial)
    r1 = subprocess.run([sys.executable, "-c", _programa_sesion(tmp_path, ["mi furgoneta es una camper", "salir"], recibido)],
                        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=60)
    assert r1.returncode == 0, r1.stderr
    guardado = json.loads((tmp_path / "hist" / "historial.json").read_text(encoding="utf-8"))
    assert guardado == [{"role": "user", "content": "mi furgoneta es una camper"},
                        {"role": "assistant", "content": "respuesta a: mi furgoneta es una camper"}]

    # Proceso 2 (intérprete nuevo): la segunda petición debe llevar la conversación guardada
    r2 = subprocess.run([sys.executable, "-c", _programa_sesion(tmp_path, ["¿cómo se llama mi vehículo?", "salir"], recibido)],
                        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0, r2.stderr
    mensajes = json.loads(recibido.read_text(encoding="utf-8"))
    turnos = [(m["role"], m["content"]) for m in mensajes if m["role"] != "system"]
    assert turnos == [("user", "mi furgoneta es una camper"),
                      ("assistant", "respuesta a: mi furgoneta es una camper"),
                      ("user", "¿cómo se llama mi vehículo?")]
    # y la memoria aprendida en el proceso 1 llega como contexto de sistema en el proceso 2
    assert any("una camper" in m["content"] for m in mensajes if m["role"] == "system")
    # el historial acumulado en disco contiene ambas sesiones, en orden
    guardado = json.loads((tmp_path / "hist" / "historial.json").read_text(encoding="utf-8"))
    assert [m["content"] for m in guardado if m["role"] == "user"] == ["mi furgoneta es una camper", "¿cómo se llama mi vehículo?"]
