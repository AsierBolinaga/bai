import sys
import types

import pytest

from core.motors import copilot_engine as motor
from core.motors.base import MotorError


@pytest.fixture
def sdk(monkeypatch):
    estado = types.SimpleNamespace(auth=True, contenido="respuesta Copilot", opciones=None,
                                  prompt=None, cliente=None, fallo=None, conexiones=0)

    class Sesion:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def on(self, funcion):
            self.observar = funcion
            return lambda: None

        async def send(self, prompt, **kw):
            estado.prompt = prompt
            if estado.fallo:
                raise estado.fallo
            self.observar(types.SimpleNamespace(type="assistant.message", agent_id=None,
                data=types.SimpleNamespace(content=estado.contenido)))
            self.observar(types.SimpleNamespace(type="session.idle", agent_id=None))
            return "request-id"

    class Cliente:
        def __init__(self, **kw):
            estado.cliente = kw
            estado.conexiones += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_auth_status(self):
            return types.SimpleNamespace(isAuthenticated=estado.auth)

        async def create_session(self, **kw):
            estado.opciones = kw
            return Sesion()

    class Denegado:
        pass

    modulos = {
        "copilot": {"CopilotClient": Cliente},
        "copilot.client": {"StdioRuntimeConnection": lambda **kw: kw},
        "copilot.generated.rpc": {"PermissionDecisionDeniedInteractivelyByUser": Denegado},
        "copilot.session_events": {"SessionEventType": types.SimpleNamespace(
            ASSISTANT_MESSAGE="assistant.message", SESSION_ERROR="session.error", SESSION_IDLE="session.idle")},
    }
    for nombre, contenido in modulos.items():
        modulo = types.ModuleType(nombre)
        modulo.__dict__.update(contenido)
        monkeypatch.setitem(sys.modules, nombre, modulo)
    monkeypatch.setattr(motor, "libreria_instalada", lambda nombre: True)
    monkeypatch.setattr(motor.shutil, "which", lambda nombre: "/usr/bin/copilot")
    estado.denegado = Denegado
    return estado


def mensajes():
    return [{"role": "system", "content": "identidad"},
            {"role": "user", "content": "pregunta vieja"},
            {"role": "assistant", "content": "respuesta vieja"},
            {"role": "system", "content": "memoria e idioma"},
            {"role": "user", "content": "pregunta actual"}]


def test_cuenta_cli_chat_sin_herramientas_ni_workspace(sdk, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "no-utilizar")
    monkeypatch.setenv("GH_TOKEN", "no-utilizar")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "no-utilizar")
    assert motor.responder(mensajes(), {"modelo": "modelo-elegido"}) == "respuesta Copilot"
    cfg = sdk.opciones
    assert cfg["available_tools"] == [] and cfg["tools"] == []
    assert cfg["model"] == "modelo-elegido"
    assert not cfg["enable_config_discovery"] and not cfg["enable_file_hooks"]
    assert not cfg["enable_host_git_operations"] and not cfg["enable_skills"]
    assert not cfg["enable_session_store"] and cfg["memory"] == {"enabled": False}
    assert cfg["skip_custom_instructions"]
    assert isinstance(cfg["on_permission_request"](None, None), sdk.denegado)
    assert "identidad" in cfg["system_message"]["content"]
    assert "memoria e idioma" in cfg["system_message"]["content"]
    assert "pregunta vieja" in sdk.prompt and "respuesta vieja" in sdk.prompt
    assert sdk.prompt.endswith("pregunta actual")
    assert sdk.cliente["use_logged_in_user"] and sdk.cliente["mode"] == "copilot-cli"
    assert sdk.cliente["builtin_plugin_directories"] == []
    assert cfg["plugin_directories"] == [] and cfg["mcp_servers"] == {}
    assert not cfg["enable_session_telemetry"]
    assert all(k not in sdk.cliente["env"] for k in ("GITHUB_TOKEN", "GH_TOKEN", "COPILOT_GITHUB_TOKEN"))
    assert cfg["working_directory"] == cfg["config_directory"]


def test_sin_autenticacion_no_crea_sesion_ni_envia(sdk):
    sdk.auth = False
    with pytest.raises(MotorError, match="copilot login"):
        motor.responder(mensajes(), {})
    assert sdk.opciones is None and sdk.prompt is None


def test_fallo_del_servicio_se_explica(sdk):
    sdk.fallo = TimeoutError("tiempo agotado")
    with pytest.raises(MotorError, match="tiempo agotado"):
        motor.responder(mensajes(), {})


def test_sin_respuesta_no_se_simula_exito(sdk):
    sdk.contenido = None
    with pytest.raises(MotorError, match="sin respuesta"):
        motor.responder(mensajes(), {})


def test_presupuesto_no_envia_pregunta_excesiva(sdk):
    with pytest.raises(MotorError, match="Contexto insuficiente"):
        motor.responder([{"role": "user", "content": "x" * 20000}], {})
    assert sdk.conexiones == 0


def test_disponible_sin_dependencia_o_cli(monkeypatch):
    monkeypatch.setattr(motor, "libreria_instalada", lambda nombre: False)
    assert not motor.disponible({})[0]
    monkeypatch.setattr(motor, "libreria_instalada", lambda nombre: True)
    monkeypatch.setattr(motor.shutil, "which", lambda nombre: None)
    assert "copilot login" in motor.disponible({})[1]
