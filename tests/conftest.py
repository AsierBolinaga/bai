"""
Fixtures compartidas.

- La raíz del proyecto se añade a sys.path y se usa como CWD (memory_engine
  usa rutas relativas).
- `motor_fake` crea motores en memoria que cumplen el contrato de
  core/motors/base.py, para probar la selección sin modelos reales.
- `libreria_fake` inyecta módulos falsos (openai, llama_cpp, gpt4all) en
  sys.modules, de modo que los motores reales se prueban sin instalar nada.
"""
import importlib.machinery
import os
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from core.motors.base import MotorError  # noqa: E402
from core import network_guard  # noqa: E402


VARIABLES_PROXY = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY",
                   "http_proxy", "https_proxy", "all_proxy", "no_proxy", "ftp_proxy")


@pytest.fixture(autouse=True)
def _sin_proxy(monkeypatch):
    """Los tests no deben depender de la configuración de proxy del entorno
    (urllib/requests/openai la leerían y cambiarían el host de destino)."""
    for variable in VARIABLES_PROXY:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture(autouse=True)
def _sin_guardias_residuales():
    """Ningún test debe dejar una GuardiaRed instalada para el siguiente."""
    yield
    network_guard._reiniciar_para_tests()


# --------------------------------------------------------------------------- config
def config_base(modo="offline", **extra):
    """Configuración normalizada mínima con motores ficticios."""
    cfg = {
        "modo_por_defecto": modo,
        "mostrar_motor": False,  # los tests del etiquetado lo activan explícitamente
        "online": {
            "motor": "on_a",
            "fallback": [],
            "prioridad": "online",   # los tests de la política por defecto (local) usan config_local()
            "fallback_offline": True,
            "max_mensajes_contexto": None,
            "motores": {"on_a": {"modelo": "modelo-online-a"}},
        },
        "offline": {
            "motor": "off_a",
            "fallback": ["off_b"],
            "max_mensajes_contexto": None,
            "motores": {
                "off_a": {"model_path": "models/a.gguf"},
                "off_b": {"model_path": "models/b.gguf"},
            },
        },
    }
    for k, v in extra.items():
        cfg[k] = v
    return cfg


def config_local(modo="online", **extra):
    """Como config_base pero con la política por defecto del proyecto: prioridad local."""
    cfg = config_base(modo, **extra)
    cfg["online"]["prioridad"] = "local"
    return cfg


# --------------------------------------------------------------------------- motores fake
class MotorFake(types.ModuleType):
    """
    Módulo-motor configurable.
      disponible_ok / motivo : resultado de disponible()
      respuesta              : texto devuelto por responder()
      error                  : excepción que lanza responder() (si no es None)
    Registra las llamadas recibidas en `llamadas`.
    """

    def __init__(self, nombre, tipo, disponible_ok=True, motivo="", respuesta=None, error=None):
        super().__init__(f"tests.fakes.{nombre}")
        self.NOMBRE = nombre
        self.TIPO = tipo
        self.disponible_ok = disponible_ok
        self.motivo = motivo
        self.respuesta = respuesta if respuesta is not None else f"respuesta de {nombre}"
        self.error = error
        self.llamadas = []
        if tipo == "online":
            self.HOST_CONECTIVIDAD = f"{nombre}.example"

    def disponible(self, config):
        return self.disponible_ok, self.motivo

    def responder(self, messages, config):
        self.llamadas.append((list(messages), dict(config)))
        if self.error is not None:
            raise self.error
        return self.respuesta


@pytest.fixture
def motores():
    """Diccionario nombre -> MotorFake, con una función `obtener` inyectable en ModelSelector."""
    from core.motors.base import MotorNoDisponible

    almacen = {}

    def obtener(nombre):
        if nombre not in almacen:
            raise MotorNoDisponible(f"Motor '{nombre}' no registrado (fake).")
        return almacen[nombre]

    def crear(nombre, tipo, **kw):
        almacen[nombre] = MotorFake(nombre, tipo, **kw)
        return almacen[nombre]

    almacen_obj = types.SimpleNamespace(crear=crear, obtener=obtener, todos=almacen)
    return almacen_obj


@pytest.fixture
def selector_fake(motores):
    """ModelSelector con motores fake on_a / off_a / off_b y conexión simulada."""
    from core.model_selector import ModelSelector

    motores.crear("on_a", "online")
    motores.crear("off_a", "offline")
    motores.crear("off_b", "offline")
    estado = {"conexion": True, "hosts": []}

    def comprobar_conexion(host):
        estado["hosts"].append(host)
        return estado["conexion"]

    creados = []

    def crear(config=None):
        sel = ModelSelector(config=config or config_base(), comprobar_conexion=comprobar_conexion,
                            obtener_motor=motores.obtener)
        sel._test_estado = estado
        creados.append(sel)
        return sel

    yield types.SimpleNamespace(crear=crear, motores=motores, estado=estado)
    for sel in creados:
        sel.cerrar()


# --------------------------------------------------------------------------- librerías fake
@pytest.fixture
def libreria_fake(monkeypatch):
    """
    Inyecta un módulo falso en sys.modules para que `import <nombre>` y
    `libreria_instalada(<nombre>)` lo encuentren. Con `instalada=False` simula
    que la librería no existe.
    """

    def inyectar(nombre, instalada=True, **atributos):
        if not instalada:
            monkeypatch.setitem(sys.modules, nombre, None)
            return None
        modulo = types.ModuleType(nombre)
        modulo.__spec__ = importlib.machinery.ModuleSpec(nombre, None)
        for k, v in atributos.items():
            setattr(modulo, k, v)
        monkeypatch.setitem(sys.modules, nombre, modulo)
        return modulo

    return inyectar


# --------------------------------------------------------------------------- aislamiento memoria
@pytest.fixture
def memoria_temporal(monkeypatch, tmp_path):
    """Redirige la memoria persistente (hechos y perfil) a tmp_path para que
    ningún test toque config/data/*. Devuelve las rutas temporales."""
    import core.memory_engine as memoria

    perfil = tmp_path / "user_profile.yaml"
    perfil.write_text("aprendido_durante_sesion: {}\n", encoding="utf-8")
    hechos = tmp_path / "facts.yaml"
    monkeypatch.setattr(memoria, "MEMORY_PATH", str(perfil))
    monkeypatch.setattr(memoria, "FACTS_PATH", str(hechos))
    return types.SimpleNamespace(perfil=perfil, hechos=hechos, dir=tmp_path)


@pytest.fixture
def perfil_temporal(monkeypatch, tmp_path):
    """Ruta temporal del perfil heredado (user_profile.yaml, aún sin crear), con el
    almacén de hechos (facts.yaml) y el historial redirigidos al mismo directorio
    temporal. Usada por tests/test_memoria.py."""
    import core.memory_engine as memoria

    perfil = tmp_path / "user_profile.yaml"
    monkeypatch.setattr(memoria, "MEMORY_PATH", str(perfil))
    monkeypatch.setattr(memoria, "FACTS_PATH", str(tmp_path / "facts.yaml"))
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(tmp_path / "history" / "historial.json"))
    return perfil


@pytest.fixture
def ai_engine_aislado(monkeypatch, memoria_temporal):
    """
    core.ai_engine sin efectos secundarios sobre config/data/*: la memoria
    persistente vive en tmp_path (memoria_temporal), el contexto y el prompt
    de sistema son textos fijos.
    """
    import core.ai_engine as ai

    monkeypatch.setattr(ai, "get_memory_context", lambda: "Memoria de prueba.")
    monkeypatch.setattr(ai, "get_system_prompt", lambda: "Prompt de sistema de prueba.")
    monkeypatch.setattr(ai, "_selector", None)
    ai._memoria_temporal = memoria_temporal
    return ai


def escribir_gguf_falso(path, version=3):
    """Crea un fichero con cabecera GGUF válida (firma + versión) pero sin contenido real."""
    import struct
    path.write_bytes(b"GGUF" + struct.pack("<I", version) + b"\0" * 16)
    return path


def mensajes_basicos(user="hola"):
    return [{"role": "system", "content": "sistema"}, {"role": "user", "content": user}]
