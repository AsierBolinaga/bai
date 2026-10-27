"""
Aislamiento de red a nivel de PROCESO: namespace de red propio (Linux).

`aislar_proceso()` mueve el proceso actual a un namespace de usuario + red
nuevos (os.unshare(CLONE_NEWUSER | CLONE_NEWNET)), sin privilegios ni binarios
externos. Dentro del namespace sólo existe la interfaz `lo`, que se activa por
ioctl: el KERNEL impide cualquier tráfico hacia fuera (TCP, UDP, DNS, raw) para
este proceso y para todos sus subprocesos y librerías nativas, mientras que las
conexiones a loopback (IPv4/IPv6, TCP/UDP) y los sockets UNIX siguen funcionando.
No hace falta parchear nada en Python.

Propiedades y límites (honestos):
  - Garantía: kernel. Cubre subprocesos, código nativo, `_socket`, UDP, DNS...
  - Irreversible durante la vida del proceso: para autorizar servicios online
    hay que reiniciar B.A.I (p. ej. `python bai.py --online`).
  - Debe activarse con un único hilo (exigencia de CLONE_NEWUSER): al arrancar,
    antes de cargar modelos. Si el proceso ya tiene hilos, falla limpiamente.
  - Servicios locales que corran FUERA del namespace (p. ej. un Ollama del
    sistema en 127.0.0.1:11434) no son alcanzables; los sockets UNIX sí.
  - Requiere Linux con namespaces de usuario sin privilegios (habitual en
    distribuciones de escritorio; puede estar restringido en kernels endurecidos)
    y Python >= 3.12 (os.unshare). Si no se cumple, se informa del motivo y B.A.I
    recurre a la guardia Python (core/network_guard.py), indicándolo en `estado`.
"""
import os
import platform
import socket
import struct
import threading

NIVELES_VALIDOS = ("proceso", "python")
MARCA_ENV = "BAI_AISLAMIENTO_PROCESO"     # heredada por subprocesos

_SIOCGIFFLAGS, _SIOCSIFFLAGS = 0x8913, 0x8914
_IFF_UP, _IFF_RUNNING = 0x1, 0x40

_estado = {"nivel": None, "detalle": "", "loopback": None, "mapa_uid_gid": None, "incidencias": []}


# --------------------------------------------------------------------------- consultas
def disponible():
    """(True, "") si este sistema permite el aislamiento de proceso; (False, motivo) si no."""
    if platform.system() != "Linux":
        return False, f"sólo disponible en Linux (sistema: {platform.system()})"
    if not hasattr(os, "unshare") or not hasattr(os, "CLONE_NEWNET"):
        return False, f"se necesita Python >= 3.12 (os.unshare); esta versión es {platform.python_version()}"
    try:
        with open("/proc/sys/kernel/unprivileged_userns_clone") as f:
            if f.read().strip() == "0":
                return False, "namespaces de usuario sin privilegios deshabilitados (kernel.unprivileged_userns_clone=0)"
    except OSError:
        pass  # el sysctl no existe en la mayoría de kernels: no es un error
    try:
        with open("/proc/sys/kernel/apparmor_restrict_unprivileged_userns") as f:
            if f.read().strip() == "1":
                return False, "AppArmor restringe los namespaces de usuario sin privilegios"
    except OSError:
        pass
    return True, ""


def interfaces_de_red():
    """Nombres de las interfaces visibles por el proceso (según /proc/net/dev)."""
    try:
        with open("/proc/net/dev") as f:
            lineas = f.read().splitlines()[2:]
    except OSError:
        return None
    return [l.split(":", 1)[0].strip() for l in lineas if ":" in l]


def solo_loopback():
    """True si el proceso sólo ve la interfaz de loopback (namespace aislado o máquina sin red)."""
    ifaces = interfaces_de_red()
    return ifaces is not None and all(i == "lo" for i in ifaces) and bool(ifaces)


def en_namespace_aislado():
    """True si este proceso (o un antecesor) activó el aislamiento de proceso."""
    if _estado["nivel"] == "proceso":
        return True
    return os.environ.get(MARCA_ENV) == "1" and solo_loopback()


def nivel_activo():
    """'proceso' | 'python' | 'ninguno' — qué aislamiento está vigente ahora mismo."""
    if en_namespace_aislado():
        return "proceso"
    from core.network_guard import guardia_activa
    return "python" if guardia_activa() else "ninguno"


def describir(nivel=None):
    """Descripción honesta del nivel de aislamiento, para mostrar al usuario."""
    nivel = nivel or nivel_activo()
    if nivel == "proceso":
        texto = ("Aislamiento de PROCESO (namespace de red del kernel): sin acceso externo para "
                 "este proceso, sus subprocesos y librerías nativas; sólo loopback y sockets UNIX.")
        if _estado["loopback"] is False:
            texto += " ATENCIÓN: loopback NO disponible (los servicios locales por TCP/UDP no funcionarán)."
        if _estado["mapa_uid_gid"] is False:
            texto += " Nota: mapa uid/gid no aplicado (los ficheros pueden aparecer como 'nobody')."
        return texto
    if nivel == "python":
        return ("Aislamiento PYTHON (intercepción de socket): bloquea conexiones y DNS externos del "
                "código Python; NO cubre subprocesos ni código nativo.")
    return "Sin aislamiento de red activo."


# --------------------------------------------------------------------------- activación
def _subir_loopback():
    """Activa `lo` en el namespace actual (equivale a `ip link set lo up`)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        ifr = struct.pack("16sH14s", b"lo", 0, b"\0" * 14)
        import fcntl
        flags = struct.unpack("16sH14s", fcntl.ioctl(s, _SIOCGIFFLAGS, ifr))[1]
        if not flags & _IFF_UP:
            fcntl.ioctl(s, _SIOCSIFFLAGS, struct.pack("16sH14s", b"lo", flags | _IFF_UP | _IFF_RUNNING, b"\0" * 14))


def _escribir_proc(ruta, contenido):
    with open(ruta, "w") as f:
        f.write(contenido)


def _mapear_identidad(uid, gid):
    """
    Conserva uid/gid dentro del namespace de usuario (como `unshare --map-user`).
    Devuelve la lista de incidencias (vacía si todo se aplicó). No es crítico
    para el aislamiento de red, pero sin mapa os.getuid() devuelve el uid de
    desbordamiento (65534) y los ficheros propios aparecen como 'nobody'.
    """
    incidencias = []
    for ruta, contenido, descripcion in (
        ("/proc/self/setgroups", "deny", "setgroups"),
        ("/proc/self/uid_map", f"{uid} {uid} 1", f"uid_map ({uid})"),
        ("/proc/self/gid_map", f"{gid} {gid} 1", f"gid_map ({gid})"),
    ):
        try:
            _escribir_proc(ruta, contenido)
        except OSError as e:
            incidencias.append(f"{descripcion} no aplicado: {e.strerror or e}")
    return incidencias


def aislar_proceso():
    """
    Activa el aislamiento de proceso. Devuelve (True, detalle) si el proceso queda
    aislado (o ya lo estaba) y (False, motivo) si no es posible; en ese caso el
    proceso no cambia. Irreversible.
    """
    if en_namespace_aislado():
        _estado.update(nivel="proceso", detalle="ya aislado")
        return True, "ya aislado"
    ok, motivo = disponible()
    if not ok:
        return False, motivo
    if threading.active_count() > 1:
        return False, (f"el proceso ya tiene {threading.active_count()} hilos; el aislamiento de proceso "
                       f"debe activarse al arrancar, antes de cargar modelos")
    uid, gid = os.getuid(), os.getgid()
    try:
        os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
    except OSError as e:
        return False, f"unshare(CLONE_NEWUSER|CLONE_NEWNET) falló: {e.strerror or e} (errno {e.errno})"

    # A partir de aquí la red externa YA está bloqueada por el kernel. El resto
    # son ajustes de comodidad cuyo fallo se informa por separado y con precisión.
    incidencias = _mapear_identidad(uid, gid)
    mapa_ok = not incidencias
    try:
        _subir_loopback()
        loopback_ok = True
    except OSError as e:
        loopback_ok = False
        incidencias.append(f"loopback no activado: {e.strerror or e}")
    os.environ[MARCA_ENV] = "1"
    detalle = "; ".join(incidencias)
    _estado.update(nivel="proceso", detalle=detalle, loopback=loopback_ok,
                   mapa_uid_gid=mapa_ok, incidencias=list(incidencias))
    return True, detalle


def estado():
    nivel = nivel_activo()
    disp, motivo = disponible()
    return {
        "nivel": nivel,
        "descripcion": describir(nivel),
        "proceso_disponible": disp,
        "motivo_no_disponible": motivo,
        "interfaces": interfaces_de_red(),
        "detalle": _estado["detalle"],
        "loopback": _estado["loopback"],
        "mapa_uid_gid": _estado["mapa_uid_gid"],
        "incidencias": list(_estado["incidencias"]),
    }
