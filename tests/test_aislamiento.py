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


def ejecutar_aislado(codigo, env_extra=None, preparar=""):
    """Ejecuta `codigo` en un hijo (tras aislar_proceso) y devuelve su salida JSON.
    `preparar` se ejecuta antes de aislar (p. ej. para simular restricciones)."""
    programa = f"""
import json, os, sys
sys.path.insert(0, {PROJECT_ROOT!r})
from core import aislamiento
{preparar}
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
    # Un crash, una excepción no prevista o la ausencia de resultado es un FALLO, nunca un skip.
    assert r.returncode == 0, f"el proceso hijo terminó con código {r.returncode}.\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    assert "Traceback" not in r.stderr, f"excepción en el proceso hijo:\n{r.stderr}"
    assert lineas, f"sin resultado del proceso hijo. stdout={r.stdout!r} stderr={r.stderr!r}"
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


UID_DESBORDAMIENTO = 65534  # kernel.overflowuid / overflowgid: valor sin mapa de uid/gid

# --------------------------------------------------------------------------- sonda independiente de capacidades
SONDA = """
import json, os, socket, struct, fcntl, tempfile
r = {}
uid, gid = os.getuid(), os.getgid()
def intento(clave, fn):
    try:
        fn(); r[clave] = True
    except OSError as e:
        r[clave] = f"errno={e.errno} {e.strerror}"
def escribir(ruta, txt):
    with open(ruta, "w") as f:
        f.write(txt)
def unix():
    d = tempfile.mkdtemp(); s = socket.socket(socket.AF_UNIX); s.bind(d + "/s.sock"); s.close()
intento("unix_fuera", unix)
intento("unshare", lambda: os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET))
if r["unshare"] is True:
    intento("setgroups", lambda: escribir("/proc/self/setgroups", "deny"))
    intento("uid_map", lambda: escribir("/proc/self/uid_map", f"{uid} {uid} 1"))
    intento("gid_map", lambda: escribir("/proc/self/gid_map", f"{gid} {gid} 1"))
    r["uid_dentro"], r["gid_dentro"] = os.getuid(), os.getgid()
    def lo_up():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ifr = struct.pack("16sH14s", b"lo", 0, b"\\0" * 14)
        flags = struct.unpack("16sH14s", fcntl.ioctl(s, 0x8913, ifr))[1]
        fcntl.ioctl(s, 0x8914, struct.pack("16sH14s", b"lo", flags | 0x41, b"\\0" * 14))
    intento("loopback", lo_up)
    intento("unix_dentro", unix)
print("@@" + json.dumps(r))
"""


@pytest.fixture(scope="module")
def capacidades():
    """
    Qué permite el ENTORNO, medido con llamadas crudas al kernel (sin core/aislamiento):
    unshare, escritura de setgroups/uid_map/gid_map, activación de loopback y
    sockets UNIX dentro y fuera del namespace. Sirve para separar restricciones
    del entorno de defectos de la implementación.
    """
    r = subprocess.run([sys.executable, "-c", SONDA], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "Traceback" not in r.stderr, f"la sonda de capacidades falló:\n{r.stderr}"
    lineas = [l for l in r.stdout.splitlines() if l.startswith("@@")]
    assert lineas, f"la sonda no devolvió resultado: {r.stdout!r}"
    return json.loads(lineas[-1][2:])


def _requiere(capacidades, clave, que):
    """skip SOLO si la sonda independiente demuestra que el entorno no lo permite."""
    if capacidades.get(clave) is not True:
        pytest.skip(f"ENTORNO: {que} no permitido en este sistema ({capacidades.get(clave)})")


CODIGO_ESTADO_RED = '''
import socket, subprocess, errno
def intento(fn):
    try:
        fn(); return "ESCAPA"
    except OSError as e:
        return e.errno if e.errno is not None else type(e).__name__
info = aislamiento.estado()
resultado["informe"] = {k: info[k] for k in ("loopback", "setgroups", "mapa_uid", "mapa_gid", "mapa_uid_gid", "incidencias")}
resultado["interfaces"] = aislamiento.interfaces_de_red()
resultado["nivel"] = aislamiento.nivel_activo()
resultado["uid"], resultado["gid"] = os.getuid(), os.getgid()
resultado["uid_esperado"], resultado["gid_esperado"] = int(os.environ["UID_ESPERADO"]), int(os.environ["GID_ESPERADO"])
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
'''

CODIGO_LOCAL = '''
import socket, tempfile
info = aislamiento.estado()
resultado["informe"] = {k: info[k] for k in ("loopback", "setgroups", "mapa_uid", "mapa_gid", "mapa_uid_gid", "incidencias")}
def intento(fn):
    try:
        return fn()
    except OSError as e:
        return f"ERROR errno={e.errno} {e.strerror}"
def tcp4():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    c = socket.create_connection(srv.getsockname(), timeout=3); r = c.getpeername()[0]; c.close(); return r
def tcp6():
    srv6 = socket.socket(socket.AF_INET6); srv6.bind(("::1", 0)); srv6.listen(1)
    c6 = socket.create_connection(srv6.getsockname()[:2], timeout=3); r = c6.getpeername()[0]; c6.close(); return r
def udp():
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(("127.0.0.1", 0)); u.settimeout(3)
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"udp", u.getsockname()); return u.recvfrom(8)[0].decode()
def unix():
    d = tempfile.mkdtemp(); ruta = d + "/s.sock"
    us = socket.socket(socket.AF_UNIX); us.bind(ruta); us.listen(1)
    uc = socket.socket(socket.AF_UNIX); uc.connect(ruta); return "ok"
resultado["tcp4_local"] = intento(tcp4)
resultado["tcp6_local"] = intento(tcp6)
resultado["udp_local"] = intento(udp)
resultado["unix"] = intento(unix)
resultado["localhost_resuelve"] = intento(lambda: socket.gethostbyname("localhost"))
resultado["fichero_accesible"] = os.access(os.path.expanduser("~"), os.R_OK)
'''

ENV_IDS = {"UID_ESPERADO": str(os.getuid()), "GID_ESPERADO": str(os.getgid())}


def _comprobar_bloqueo_externo(res):
    """Parte de la garantía que no depende de loopback ni de uid: la red externa."""
    # ENETUNREACH (101) con lo activo; EADDRNOTAVAIL (99) si ni siquiera loopback está levantado
    BLOQUEADO = {101, 99}
    assert res["interfaces"] == ["lo"]
    assert res["nivel"] == "proceso"
    assert res["tcp"] in BLOQUEADO and res["tcp6"] in BLOQUEADO
    assert res["udp_sendto"] in BLOQUEADO and res["udp_sendmsg"] in BLOQUEADO
    assert res["dns"] != "ESCAPA" and res["gethostbyname"] != "ESCAPA"
    assert res["_socket"] in BLOQUEADO              # también lo que la guardia Python no puede ver
    assert res["subproceso_errno"] in BLOQUEADO     # y los subprocesos
    assert res["marca_heredada"] == "1"


def _comprobar_identidad(res, capacidades):
    """
    uid y gid se juzgan POR SEPARADO, contrastando el informe de la implementación
    con la realidad del kernel y con lo que la sonda independiente dice que el
    entorno permite. Cualquier contradicción es un defecto (fallo); una
    restricción demostrada por la sonda y bien informada es un skip.
    """
    informe = res["informe"]
    # --- uid
    if informe["mapa_uid"]:
        assert res["uid"] == res["uid_esperado"], f"DEFECTO: informe mapa_uid=True pero getuid()={res['uid']}"
    else:
        assert any(i.startswith("uid_map") for i in informe["incidencias"]), "DEFECTO: mapa_uid=False sin incidencia"
        assert res["uid"] == UID_DESBORDAMIENTO, f"DEFECTO: informe mapa_uid=False pero getuid()={res['uid']}"
        assert capacidades["uid_map"] is not True, "DEFECTO: el entorno permite uid_map pero la implementación no lo aplicó"
    # --- gid (un fallo de gid_map/setgroups NO implica uid 65534)
    if informe["mapa_gid"]:
        assert res["gid"] == res["gid_esperado"], f"DEFECTO: informe mapa_gid=True pero getgid()={res['gid']}"
    else:
        assert any(i.startswith(("gid_map", "setgroups")) for i in informe["incidencias"]), "DEFECTO: mapa_gid=False sin incidencia"
        assert res["gid"] == UID_DESBORDAMIENTO, f"DEFECTO: informe mapa_gid=False pero getgid()={res['gid']}"
        assert capacidades["gid_map"] is not True or capacidades["setgroups"] is not True, \
            "DEFECTO: el entorno permite gid_map pero la implementación no lo aplicó"
    restricciones = [k for k in ("uid_map", "gid_map", "setgroups") if capacidades.get(k) is not True]
    if restricciones:
        pytest.skip("ENTORNO: el sistema no permite " + ", ".join(restricciones) + " en el namespace "
                    "(informado con precisión por la implementación)")


@real
def test_real_kernel_bloquea_tcp_udp_dns_y_subprocesos(capacidades):
    _requiere(capacidades, "unshare", "unshare(CLONE_NEWUSER|CLONE_NEWNET)")
    res = ejecutar_aislado(CODIGO_ESTADO_RED, env_extra=ENV_IDS)
    assert res["ok"], f"DEFECTO: la sonda pudo hacer unshare pero aislar_proceso() falló: {res}"
    _comprobar_bloqueo_externo(res)
    _comprobar_identidad(res, capacidades)


@real
def test_real_loopback_y_unix_siguen_funcionando(capacidades):
    _requiere(capacidades, "unshare", "unshare(CLONE_NEWUSER|CLONE_NEWNET)")
    _requiere(capacidades, "unix_fuera", "crear sockets UNIX en el directorio temporal")
    res = ejecutar_aislado(CODIGO_LOCAL)
    assert res["ok"], f"DEFECTO: {res}"
    informe = res["informe"]
    # Sockets UNIX: si la sonda cruda los crea dentro del namespace, la implementación no puede impedirlo
    if capacidades["unix_dentro"] is True:
        assert res["unix"] == "ok", f"DEFECTO: sockets UNIX permitidos por el entorno pero fallan: {res['unix']}"
    # (si la sonda no pudo crearlos dentro del namespace, es restricción del entorno: se informa en el skip final)
    assert res["fichero_accesible"] is True
    assert res["localhost_resuelve"] == "127.0.0.1"
    # Loopback: contraste informe <-> realidad <-> capacidad del entorno
    if informe["loopback"]:
        assert res["tcp4_local"] == "127.0.0.1", f"DEFECTO: informe loopback=True pero TCP local falla: {res['tcp4_local']}"
        assert res["udp_local"] == "udp"
        assert res["tcp6_local"] == "::1" or res["tcp6_local"].startswith("ERROR")  # IPv6 puede estar deshabilitado
    else:
        assert any(i.startswith("loopback") for i in informe["incidencias"]), "DEFECTO: loopback=False sin incidencia"
        assert str(res["tcp4_local"]).startswith("ERROR"), "DEFECTO: informe loopback=False pero TCP local funciona"
        assert capacidades["loopback"] is not True, "DEFECTO: el entorno permite activar loopback pero la implementación no lo hizo"
    restricciones = [k for k in ("loopback", "unix_dentro") if capacidades.get(k) is not True]
    if restricciones:
        pytest.skip("ENTORNO: no permitido dentro del namespace: " + ", ".join(f"{k} ({capacidades[k]})" for k in restricciones))


def _con_fallos(*claves):
    """Código de preparación que hace fallar sólo los pasos indicados (setgroups/uid_map/gid_map/loopback)."""
    return f'''
_original_escribir = aislamiento._escribir_proc
def _escribir(ruta, contenido):
    if any(ruta.endswith(c) for c in {claves!r}):
        raise OSError(1, "Operation not permitted")
    return _original_escribir(ruta, contenido)
aislamiento._escribir_proc = _escribir
if "loopback" in {claves!r}:
    def _lo():
        raise OSError(1, "Operation not permitted")
    aislamiento._subir_loopback = _lo
'''


@real
def test_real_solo_gid_map_falla_conserva_el_uid(capacidades):
    """Regresión: un fallo de gid_map NO debe implicar uid 65534 ni informarse como fallo de uid."""
    _requiere(capacidades, "unshare", "unshare")
    _requiere(capacidades, "uid_map", "uid_map")
    res = ejecutar_aislado(CODIGO_ESTADO_RED, env_extra=ENV_IDS, preparar=_con_fallos("gid_map"))
    assert res["ok"], res
    _comprobar_bloqueo_externo(res)
    inf = res["informe"]
    assert (inf["setgroups"], inf["mapa_uid"], inf["mapa_gid"], inf["mapa_uid_gid"]) == (True, True, False, False)
    assert [i.split(" ")[0] for i in inf["incidencias"]] == ["gid_map"]
    assert res["uid"] == res["uid_esperado"]            # uid conservado
    assert res["gid"] == UID_DESBORDAMIENTO             # sólo el gid queda sin mapear
    assert res["detalle"].startswith("gid_map (")


@real
def test_real_solo_setgroups_falla_conserva_el_uid(capacidades):
    """Sin setgroups=deny el kernel rechaza gid_map; el uid sigue mapeado."""
    _requiere(capacidades, "unshare", "unshare")
    _requiere(capacidades, "uid_map", "uid_map")
    res = ejecutar_aislado(CODIGO_ESTADO_RED, env_extra=ENV_IDS, preparar=_con_fallos("setgroups"))
    assert res["ok"], res
    inf = res["informe"]
    assert inf["setgroups"] is False and inf["mapa_uid"] is True
    assert inf["mapa_gid"] is False                      # consecuencia real del kernel, informada aparte
    assert [i.split(" ")[0] for i in inf["incidencias"]] == ["setgroups", "gid_map"]
    assert res["uid"] == res["uid_esperado"] and res["gid"] == UID_DESBORDAMIENTO


@real
def test_real_solo_uid_map_falla_conserva_el_gid(capacidades):
    _requiere(capacidades, "unshare", "unshare")
    _requiere(capacidades, "gid_map", "gid_map")
    res = ejecutar_aislado(CODIGO_ESTADO_RED, env_extra=ENV_IDS, preparar=_con_fallos("uid_map"))
    assert res["ok"], res
    inf = res["informe"]
    assert (inf["setgroups"], inf["mapa_uid"], inf["mapa_gid"]) == (True, False, True)
    assert [i.split(" ")[0] for i in inf["incidencias"]] == ["uid_map"]
    assert res["uid"] == UID_DESBORDAMIENTO and res["gid"] == res["gid_esperado"]


@real
def test_real_entorno_restringido_simulado_se_informa_con_precision(capacidades):
    """Reproduce de verdad un entorno que impide mapear uid/gid y activar loopback
    (sin aplicar esos pasos): el kernel sigue aislando, los sockets UNIX funcionan,
    y el informe refleja exactamente la situación real."""
    _requiere(capacidades, "unshare", "unshare")
    res = ejecutar_aislado(CODIGO_ESTADO_RED + CODIGO_LOCAL, env_extra=ENV_IDS,
                           preparar=_con_fallos("setgroups", "uid_map", "gid_map", "loopback"))
    assert res["ok"], res
    _comprobar_bloqueo_externo(res)                     # la garantía principal se mantiene
    informe = res["informe"]
    assert (informe["setgroups"], informe["mapa_uid"], informe["mapa_gid"], informe["loopback"]) == (False, False, False, False)
    assert [i.split(" ")[0] for i in informe["incidencias"]] == ["setgroups", "uid_map", "gid_map", "loopback"]
    assert res["uid"] == UID_DESBORDAMIENTO and res["gid"] == UID_DESBORDAMIENTO
    assert str(res["tcp4_local"]).startswith("ERROR")     # sin loopback no hay TCP local...
    if capacidades["unix_dentro"] is True:
        assert res["unix"] == "ok"                        # ...pero los sockets UNIX sí funcionan
    assert res["detalle"].startswith("setgroups no aplicado") and "loopback no activado" in res["detalle"]


@real
def test_real_un_crash_en_el_hijo_es_un_fallo_no_un_skip(capacidades):
    _requiere(capacidades, "unshare", "unshare")
    with pytest.raises(AssertionError, match="excepción en el proceso hijo|código"):
        ejecutar_aislado("raise RuntimeError('fallo inesperado dentro del namespace')")


@real
def test_real_selector_rechaza_modo_online_en_proceso_aislado(capacidades):
    _requiere(capacidades, "unshare", "unshare")
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
def test_real_motor_offline_real_funciona_aislado_si_hay_libreria(capacidades):
    """Si llama-cpp-python está instalado, el adaptador genera dentro del namespace."""
    _requiere(capacidades, "unshare", "unshare")
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
    aislamiento._estado.update(aislamiento._ESTADO_INICIAL)
    os.environ.pop(aislamiento.MARCA_ENV, None)


def test_informe_sin_incidencias(unshare_simulado):
    ok, detalle = aislamiento.aislar_proceso()
    assert (ok, detalle) == (True, "")
    info = aislamiento.estado()
    assert info["loopback"] is True and info["mapa_uid_gid"] is True and info["incidencias"] == []
    assert (info["setgroups"], info["mapa_uid"], info["mapa_gid"]) == (True, True, True)
    assert "ATENCIÓN" not in info["descripcion"] and "Nota" not in info["descripcion"]


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
    assert (info["setgroups"], info["mapa_uid"], info["mapa_gid"], info["mapa_uid_gid"]) == (True, False, True, False)
    assert info["loopback"] is True
    assert "mapa de uid no aplicado" in info["descripcion"] and "mapa de gid" not in info["descripcion"]


@pytest.mark.parametrize("falla,esperado,texto", [
    ("gid_map", (True, True, False), "mapa de gid no aplicado"),
    ("setgroups", (False, True, True), None),
])
def test_informe_fallos_parciales_independientes(unshare_simulado, falla, esperado, texto):
    """Regresión: cada paso del mapa se informa por separado; un fallo de gid_map o
    setgroups no se presenta como fallo de uid."""
    def escribir(ruta, contenido):
        if ruta.endswith(falla):
            raise OSError(1, "Operation not permitted")
    unshare_simulado.setattr(aislamiento, "_escribir_proc", escribir)
    ok, detalle = aislamiento.aislar_proceso()
    assert ok is True
    info = aislamiento.estado()
    assert (info["setgroups"], info["mapa_uid"], info["mapa_gid"]) == esperado
    assert info["mapa_uid"] is True and "mapa de uid no aplicado" not in info["descripcion"]
    assert [i.split(" ")[0] for i in info["incidencias"]] == [falla]
    if texto:
        assert texto in info["descripcion"]


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
