"""
Aislamiento de proceso (core/aislamiento.py).

La activación es irreversible, así que las pruebas reales se ejecutan en un
proceso hijo que se aísla y verifica desde dentro: tráfico externo TCP/UDP/DNS
bloqueado por el kernel (también en subprocesos), loopback y UNIX operativos.
Se omiten si el sistema no permite namespaces de usuario sin privilegios.
"""
import json
import os
import subprocess
import sys

import pytest

from core import aislamiento

DISPONIBLE, MOTIVO = aislamiento.disponible()
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ejecutar_aislado(codigo, env_extra=None):
    """Ejecuta `codigo` en un hijo (tras aislar_proceso) y devuelve su salida JSON."""
    programa = f"""
import json, os, sys
sys.path.insert(0, {PROJECT_ROOT!r})
from core import aislamiento
ok, detalle = aislamiento.aislar_proceso()
resultado = {{"ok": ok, "detalle": detalle}}
if ok:
{chr(10).join('    ' + l for l in codigo.strip().splitlines())}
print("@@" + json.dumps(resultado))
"""
    env = dict(os.environ, **(env_extra or {}))
    env.pop(aislamiento.MARCA_ENV, None)
    r = subprocess.run([sys.executable, "-c", programa], capture_output=True, text=True, timeout=60, env=env)
    lineas = [l for l in r.stdout.splitlines() if l.startswith("@@")]
    assert lineas, f"sin resultado. stdout={r.stdout!r} stderr={r.stderr!r}"
    return json.loads(lineas[-1][2:])


# --------------------------------------------------------------------------- sin privilegios especiales
def test_disponible_devuelve_tupla():
    ok, motivo = aislamiento.disponible()
    assert isinstance(ok, bool) and isinstance(motivo, str)
    assert ok or motivo


def test_describir_niveles():
    assert "kernel" in aislamiento.describir("proceso")
    assert "NO cubre subprocesos" in aislamiento.describir("python")
    assert "Sin aislamiento" in aislamiento.describir("ninguno")


def test_nivel_activo_sin_nada():
    assert aislamiento.nivel_activo() in ("ninguno", "proceso")  # 'proceso' si pytest corre ya aislado


def test_no_aislado_por_defecto_en_el_test_runner(monkeypatch):
    monkeypatch.delenv(aislamiento.MARCA_ENV, raising=False)
    monkeypatch.setitem(aislamiento._estado, "nivel", None)
    if aislamiento.solo_loopback():
        pytest.skip("el entorno de test no tiene interfaces de red")
    assert aislamiento.en_namespace_aislado() is False


def test_marca_env_sin_namespace_no_engana(monkeypatch):
    """La variable heredada no basta: se comprueba que realmente sólo exista loopback."""
    monkeypatch.setenv(aislamiento.MARCA_ENV, "1")
    monkeypatch.setitem(aislamiento._estado, "nivel", None)
    monkeypatch.setattr(aislamiento, "interfaces_de_red", lambda: ["lo", "eth0"])
    assert aislamiento.en_namespace_aislado() is False
    monkeypatch.setattr(aislamiento, "interfaces_de_red", lambda: ["lo"])
    assert aislamiento.en_namespace_aislado() is True


def test_aislar_falla_limpiamente_con_varios_hilos(monkeypatch):
    import threading
    monkeypatch.setattr(aislamiento, "disponible", lambda: (True, ""))
    monkeypatch.setattr(aislamiento, "en_namespace_aislado", lambda: False)
    monkeypatch.setattr(threading, "active_count", lambda: 3)
    ok, motivo = aislamiento.aislar_proceso()
    assert ok is False and "hilos" in motivo


def test_aislar_falla_limpiamente_si_no_disponible(monkeypatch):
    monkeypatch.setattr(aislamiento, "disponible", lambda: (False, "no soportado"))
    monkeypatch.setattr(aislamiento, "en_namespace_aislado", lambda: False)
    assert aislamiento.aislar_proceso() == (False, "no soportado")


# --------------------------------------------------------------------------- real (proceso hijo)
real = pytest.mark.skipif(not DISPONIBLE, reason=f"aislamiento de proceso no disponible: {MOTIVO}")


@real
def test_real_kernel_bloquea_tcp_udp_dns_y_subprocesos():
    res = ejecutar_aislado('''
import socket, subprocess, errno
def intento(fn):
    try:
        fn(); return "ESCAPA"
    except OSError as e:
        return e.errno if e.errno is not None else type(e).__name__
resultado["interfaces"] = aislamiento.interfaces_de_red()
resultado["nivel"] = aislamiento.nivel_activo()
resultado["uid_conservado"] = os.getuid() == int(os.environ.get("UID_ESPERADO", os.getuid()))
resultado["tcp"] = intento(lambda: socket.create_connection(("93.184.216.34", 80), timeout=3))
resultado["tcp6"] = intento(lambda: socket.socket(socket.AF_INET6).connect(("2001:db8::1", 80)))
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
resultado["udp_sendto"] = intento(lambda: u.sendto(b"x", ("8.8.8.8", 53)))
resultado["udp_sendmsg"] = intento(lambda: u.sendmsg([b"x"], [], 0, ("1.1.1.1", 53)))
resultado["dns"] = intento(lambda: socket.getaddrinfo("api.openai.com", 443))
resultado["gethostbyname"] = intento(lambda: socket.gethostbyname("gpt4all.io"))
import _socket
resultado["_socket"] = intento(lambda: _socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("93.184.216.34", 80)))
hijo = subprocess.run([sys.executable, "-c", "import socket,sys; s=socket.socket(); s.settimeout(3); sys.exit(s.connect_ex(('93.184.216.34',80)))"])
resultado["subproceso_errno"] = hijo.returncode
resultado["marca_heredada"] = subprocess.run([sys.executable, "-c", f"import os; print(os.environ.get({aislamiento.MARCA_ENV!r}))"], capture_output=True, text=True).stdout.strip()
''', env_extra={"UID_ESPERADO": str(os.getuid())})
    assert res["ok"], res
    assert res["interfaces"] == ["lo"]
    assert res["nivel"] == "proceso"
    assert res["uid_conservado"] is True
    ENETUNREACH = 101
    assert res["tcp"] == ENETUNREACH and res["tcp6"] == ENETUNREACH
    assert res["udp_sendto"] == ENETUNREACH and res["udp_sendmsg"] == ENETUNREACH
    assert res["dns"] != "ESCAPA" and res["gethostbyname"] != "ESCAPA"
    assert res["_socket"] == ENETUNREACH            # también lo que la guardia Python no puede ver
    assert res["subproceso_errno"] == ENETUNREACH   # y los subprocesos
    assert res["marca_heredada"] == "1"


@real
def test_real_loopback_y_unix_siguen_funcionando():
    res = ejecutar_aislado('''
import socket, tempfile
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
c = socket.create_connection(srv.getsockname(), timeout=3); resultado["tcp4_local"] = c.getpeername()[0]; c.close()
try:
    srv6 = socket.socket(socket.AF_INET6); srv6.bind(("::1", 0)); srv6.listen(1)
    c6 = socket.create_connection(srv6.getsockname()[:2], timeout=3); resultado["tcp6_local"] = c6.getpeername()[0]; c6.close()
except OSError as e:
    resultado["tcp6_local"] = f"no disponible: {e}"
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(("127.0.0.1", 0)); u.settimeout(3)
socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"udp", u.getsockname()); resultado["udp_local"] = u.recvfrom(8)[0].decode()
ruta = tempfile.mktemp(suffix=".sock")
us = socket.socket(socket.AF_UNIX); us.bind(ruta); us.listen(1)
uc = socket.socket(socket.AF_UNIX); uc.connect(ruta); resultado["unix"] = True
resultado["localhost_resuelve"] = socket.gethostbyname("localhost")
resultado["fichero_accesible"] = os.access(os.path.expanduser("~"), os.R_OK)
''')
    assert res["ok"], res
    assert res["tcp4_local"] == "127.0.0.1"
    assert res["tcp6_local"] in ("::1",) or res["tcp6_local"].startswith("no disponible")
    assert res["udp_local"] == "udp" and res["unix"] is True
    assert res["localhost_resuelve"] == "127.0.0.1"
    assert res["fichero_accesible"] is True


@real
def test_real_selector_rechaza_modo_online_en_proceso_aislado():
    res = ejecutar_aislado('''
from core.model_selector import ModelSelector, AislamientoActivo
from tests.conftest import config_base
sel = ModelSelector(config=config_base("offline"), obtener_motor=lambda n: None)
try:
    sel.set_modo("online"); resultado["cambio"] = "PERMITIDO"
except AislamientoActivo as e:
    resultado["cambio"] = "rechazado"; resultado["mensaje"] = str(e)
resultado["modo"] = sel.modo
resultado["estado_aislamiento"] = sel.aislamiento()["nivel"]
''')
    assert res["ok"], res
    assert res["cambio"] == "rechazado" and res["modo"] == "offline"
    assert "--online" in res["mensaje"]
    assert res["estado_aislamiento"] == "proceso"


@real
def test_real_motor_offline_real_funciona_aislado_si_hay_libreria():
    """Si llama-cpp-python está instalado, el adaptador genera dentro del namespace."""
    from core.motors.base import libreria_instalada
    if not (libreria_instalada("llama_cpp") and libreria_instalada("gguf") and libreria_instalada("numpy")):
        pytest.skip("llama-cpp-python/gguf/numpy no instalados")
    res = ejecutar_aislado('''
import tempfile
from tests.helpers.gguf_minimo import crear_gguf
from core.motors import llama_cpp_engine as motor
ruta = crear_gguf(tempfile.mktemp(suffix=".gguf"))
texto = motor.responder([{"role": "user", "content": "hola"}], {"model_path": ruta, "n_ctx": 128, "max_tokens": 4})
resultado["respondio"] = isinstance(texto, str) and len(texto) > 0
''')
    assert res["ok"], res
    assert res["respondio"] is True



# --------------------------------------------------------------------------- informe preciso de incidencias (sin unshare real)
@pytest.fixture
def unshare_simulado(monkeypatch):
    """Simula os.unshare y las escrituras en /proc para probar el informe sin aislar de verdad."""
    monkeypatch.setattr(aislamiento, "disponible", lambda: (True, ""))
    # como la función real, pero sin mirar /proc/net/dev (no hay namespace de verdad)
    monkeypatch.setattr(aislamiento, "en_namespace_aislado", lambda: aislamiento._estado["nivel"] == "proceso")
    monkeypatch.setattr(aislamiento.os, "unshare", lambda flags: None)
    monkeypatch.setattr(aislamiento, "_escribir_proc", lambda ruta, contenido: None)
    monkeypatch.setattr(aislamiento, "_subir_loopback", lambda: None)
    monkeypatch.setitem(aislamiento._estado, "nivel", None)
    monkeypatch.delenv(aislamiento.MARCA_ENV, raising=False)
    yield monkeypatch
    aislamiento._estado.update(nivel=None, detalle="", loopback=None, mapa_uid_gid=None, incidencias=[])
    os.environ.pop(aislamiento.MARCA_ENV, None)


def test_informe_sin_incidencias(unshare_simulado):
    ok, detalle = aislamiento.aislar_proceso()
    assert (ok, detalle) == (True, "")
    info = aislamiento.estado()
    assert info["loopback"] is True and info["mapa_uid_gid"] is True and info["incidencias"] == []
    assert "ATENCIÓN" not in info["descripcion"]


def test_informe_fallo_de_loopback(unshare_simulado):
    def loopback_roto():
        raise OSError(1, "Operation not permitted")
    unshare_simulado.setattr(aislamiento, "_subir_loopback", loopback_roto)
    ok, detalle = aislamiento.aislar_proceso()
    assert ok is True                                    # la red externa sí quedó bloqueada
    assert detalle == "loopback no activado: Operation not permitted"
    info = aislamiento.estado()
    assert info["loopback"] is False and info["mapa_uid_gid"] is True
    assert "loopback NO disponible" in info["descripcion"]


def test_informe_fallo_de_mapa_uid_gid(unshare_simulado):
    def escribir(ruta, contenido):
        if ruta.endswith("uid_map"):
            raise OSError(13, "Permission denied")
    unshare_simulado.setattr(aislamiento, "_escribir_proc", escribir)
    ok, detalle = aislamiento.aislar_proceso()
    assert ok is True
    assert detalle.startswith("uid_map (") and "Permission denied" in detalle
    info = aislamiento.estado()
    assert info["mapa_uid_gid"] is False and info["loopback"] is True
    assert "mapa uid/gid no aplicado" in info["descripcion"]


def test_informe_varias_incidencias_en_orden(unshare_simulado):
    def escribir(ruta, contenido):
        raise OSError(13, "Permission denied")
    def loopback_roto():
        raise OSError(19, "No such device")
    unshare_simulado.setattr(aislamiento, "_escribir_proc", escribir)
    unshare_simulado.setattr(aislamiento, "_subir_loopback", loopback_roto)
    ok, detalle = aislamiento.aislar_proceso()
    assert ok is True
    partes = detalle.split("; ")
    assert [p.split(" ")[0] for p in partes] == ["setgroups", "uid_map", "gid_map", "loopback"]
    assert aislamiento.estado()["incidencias"] == partes


def test_fallo_de_unshare_se_informa_con_errno(unshare_simulado):
    def unshare_roto(flags):
        raise OSError(1, "Operation not permitted")
    unshare_simulado.setattr(aislamiento.os, "unshare", unshare_roto)
    ok, motivo = aislamiento.aislar_proceso()
    assert ok is False and "Operation not permitted" in motivo and "errno 1" in motivo
    assert aislamiento._estado["nivel"] is None and aislamiento.MARCA_ENV not in os.environ
