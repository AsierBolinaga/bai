"""
Guardia de red a nivel de INTÉRPRETE (capa de respaldo y de registro de intentos).

`GuardiaRed` es un context manager que, mientras está activo, intercepta las
APIs del módulo `socket` capaces de iniciar tráfico hacia fuera o de resolver
nombres, y sólo deja pasar destinos locales de esta máquina:

    socket.socket.connect / connect_ex      TCP y UDP "conectado"
    socket.socket.sendto / sendmsg          UDP (y raw) sin connect, destino explícito
    socket.socket.send / sendall / sendfile / sendmsg sin destino
                                            escrituras sobre sockets YA conectados (también
                                            los conectados antes de activar la guardia): se
                                            comprueba el extremo remoto con getpeername()
    ssl.SSLSocket.send / sendall / write / sendfile / do_handshake
                                            escrituras TLS (no pasan por socket.send)
    socket.getaddrinfo / gethostbyname / gethostbyname_ex / gethostbyaddr / getnameinfo
                                            resolución DNS directa e inversa

Destinos locales permitidos (permitir_local=True): loopback IPv4 (127.0.0.0/8) e
IPv6 (::1, incluido el formato IPv4-mapped ::ffff:127.x.x.x), direcciones no
especificadas (0.0.0.0 / ::), 'localhost' y '*.localhost', y sockets UNIX. Las
direcciones con zona (fe80::1%eth0) y cualquier otro nombre de host se bloquean,
porque comprobar si un nombre apunta a loopback exigiría resolverlo (y eso ya
sería una consulta DNS externa). Los intentos bloqueados lanzan
AccesoRedBloqueado (subclase de OSError) y quedan anotados en `intentos`.

LO QUE ESTA CAPA GARANTIZA Y LO QUE NO
---------------------------------------
  Cubre : código Python que use el módulo `socket` (http.client, urllib, requests,
          urllib3, httpx, aiohttp, asyncio, ssl...), en TODOS los hilos del proceso.
  NO cubre:
    - subprocesos (curl, wget, otro intérprete...);
    - código nativo (C/C++) que abra sockets sin pasar por Python;
    - uso directo de `_socket.socket` (tipo C, no parcheable);
    - escrituras directas sobre el descriptor (os.write / os.sendfile sobre sock.fileno());
    - referencias a las funciones originales guardadas antes de activar la guardia.
  Es global al proceso: mientras está activa afecta a todos los hilos (un hilo
  "online" concurrente también vería bloqueadas sus conexiones externas).

Por eso esta capa NO se presenta como aislamiento completo. El aislamiento real
lo proporciona core/aislamiento.py (namespace de red del kernel), y el estado
que se muestra al usuario distingue siempre ambos niveles.
"""
import ipaddress
import socket
import ssl
import threading

HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::", ""}
FAMILIAS_INET = {socket.AF_INET, socket.AF_INET6}


class AccesoRedBloqueado(OSError):
    """Intento de conexión a un servicio externo durante trabajo offline."""


# --------------------------------------------------------------------------- destinos
def _normalizar_host(host):
    if isinstance(host, bytes):
        host = host.decode("utf-8", "ignore")
    host = str(host).strip().lower().rstrip(".")
    if host.startswith("[") and "]" in host:       # "[::1]" / "[::1]:8080"
        host = host[1:host.index("]")]
    return host


def es_destino_local(host):
    """True si `host` designa esta máquina (loopback IPv4/IPv6, nombre local o socket UNIX)."""
    if host is None:
        return True
    if not isinstance(host, (str, bytes)):
        return False
    h = _normalizar_host(host)
    if h in HOSTS_LOCALES or h.endswith(".localhost"):
        return True
    if h.startswith("/") or h.startswith("\0"):    # socket UNIX (ruta o abstracto)
        return True
    if "%" in h:                                   # dirección con zona: nunca loopback
        return False
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False                               # nombre de host no literal: bloquear
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_unspecified


def _host_de_direccion(address):
    if isinstance(address, (tuple, list)):
        return address[0] if address else None
    return address                                 # AF_UNIX: ruta


def _direccion_permitida(sock, address):
    """Sockets no INET (UNIX, NETLINK...) no alcanzan Internet: se permiten."""
    if sock is not None and getattr(sock, "family", None) not in FAMILIAS_INET:
        return True
    return _permitir_local_efectivo() and es_destino_local(_host_de_direccion(address))


def _peer(sock):
    """Extremo remoto de un socket conectado, o None si no está conectado."""
    try:
        return sock.getpeername()
    except OSError:
        return None


def _peer_permitido(sock):
    """
    Comprueba el destino de un socket ya conectado (quizá antes de activar la
    guardia). Sin conexión no hay destino que validar: la operación fallará por
    sí sola (ENOTCONN) y no puede enviar nada.
    """
    if getattr(sock, "family", None) not in FAMILIAS_INET:
        return True
    peer = _peer(sock)
    if peer is None:
        return True
    return _permitir_local_efectivo() and es_destino_local(_host_de_direccion(peer))


# --------------------------------------------------------------------------- estado global
_lock = threading.RLock()
_activas = []          # pila de guardias activas (la más externa primero)
_originales = {}       # (objeto, atributo) -> función original


def _permitir_local_efectivo():
    return all(g.permitir_local for g in list(_activas))


def _bloquear(destino):
    for g in list(_activas):
        g.intentos.append(str(destino))
    raise AccesoRedBloqueado(
        f"B.A.I (modo offline): conexión a {destino!r} bloqueada; sólo se permite trabajo local."
    )


def _envoltorios():
    o = _originales

    def connect(sock, address, *a, **k):
        if _direccion_permitida(sock, address):
            return o[(socket.socket, "connect")](sock, address, *a, **k)
        _bloquear(_host_de_direccion(address))

    def connect_ex(sock, address, *a, **k):
        if _direccion_permitida(sock, address):
            return o[(socket.socket, "connect_ex")](sock, address, *a, **k)
        _bloquear(_host_de_direccion(address))

    def sendto(sock, data, *args):
        # sendto(data, address) | sendto(data, flags, address)
        address = args[-1] if args else None
        if address is None:
            if _peer_permitido(sock):
                return o[(socket.socket, "sendto")](sock, data, *args)
            _bloquear(_host_de_direccion(_peer(sock)))
        if _direccion_permitida(sock, address):
            return o[(socket.socket, "sendto")](sock, data, *args)
        _bloquear(_host_de_direccion(address))

    def sendmsg(sock, buffers, ancdata=(), flags=0, address=None):
        if address is None:
            # sin destino explícito: se envía al extremo conectado -> comprobarlo
            if _peer_permitido(sock):
                return o[(socket.socket, "sendmsg")](sock, buffers, ancdata, flags, address)
            _bloquear(_host_de_direccion(_peer(sock)))
        if _direccion_permitida(sock, address):
            return o[(socket.socket, "sendmsg")](sock, buffers, ancdata, flags, address)
        _bloquear(_host_de_direccion(address))

    def _escritura(clave):
        """Envoltorio genérico para send/sendall/sendfile/write/do_handshake: valida el peer."""
        def envoltorio(sock, *a, **k):
            if _peer_permitido(sock):
                return o[clave](sock, *a, **k)
            _bloquear(_host_de_direccion(_peer(sock)))
        return envoltorio

    def getaddrinfo(host, *a, **k):
        if _permitir_local_efectivo() and es_destino_local(host):
            return o[(socket, "getaddrinfo")](host, *a, **k)
        _bloquear(host)

    def gethostbyname(host):
        if _permitir_local_efectivo() and es_destino_local(host):
            return o[(socket, "gethostbyname")](host)
        _bloquear(host)

    def gethostbyname_ex(host):
        if _permitir_local_efectivo() and es_destino_local(host):
            return o[(socket, "gethostbyname_ex")](host)
        _bloquear(host)

    def gethostbyaddr(ip):
        if _permitir_local_efectivo() and es_destino_local(ip):
            return o[(socket, "gethostbyaddr")](ip)
        _bloquear(ip)

    def getnameinfo(sockaddr, flags):
        host = _host_de_direccion(sockaddr)
        if _permitir_local_efectivo() and es_destino_local(host):
            return o[(socket, "getnameinfo")](sockaddr, flags)
        _bloquear(host)

    envoltorios = {
        (socket.socket, "connect"): connect,
        (socket.socket, "connect_ex"): connect_ex,
        (socket.socket, "sendto"): sendto,
        (socket.socket, "sendmsg"): sendmsg,
        (socket.socket, "send"): _escritura((socket.socket, "send")),
        (socket.socket, "sendall"): _escritura((socket.socket, "sendall")),
        (socket.socket, "sendfile"): _escritura((socket.socket, "sendfile")),
        # TLS: SSLSocket sobrescribe estos métodos y escribe directamente en el
        # objeto SSL (no pasa por socket.send), así que se interceptan aparte.
        (ssl.SSLSocket, "send"): _escritura((ssl.SSLSocket, "send")),
        (ssl.SSLSocket, "sendall"): _escritura((ssl.SSLSocket, "sendall")),
        (ssl.SSLSocket, "write"): _escritura((ssl.SSLSocket, "write")),
        (ssl.SSLSocket, "sendfile"): _escritura((ssl.SSLSocket, "sendfile")),
        (ssl.SSLSocket, "do_handshake"): _escritura((ssl.SSLSocket, "do_handshake")),
        (socket, "getaddrinfo"): getaddrinfo,
        (socket, "gethostbyname"): gethostbyname,
        (socket, "gethostbyname_ex"): gethostbyname_ex,
        (socket, "gethostbyaddr"): gethostbyaddr,
        (socket, "getnameinfo"): getnameinfo,
    }
    return envoltorios


def _nombre(objeto):
    return {socket.socket: "socket.socket", ssl.SSLSocket: "ssl.SSLSocket", socket: "socket"}[objeto]


def _instalar():
    for (objeto, atributo), envoltorio in _envoltorios().items():
        _originales[(objeto, atributo)] = getattr(objeto, atributo)
        setattr(objeto, atributo, envoltorio)


def _desinstalar():
    for (objeto, atributo), original in list(_originales.items()):
        setattr(objeto, atributo, original)
    _originales.clear()


class GuardiaRed:
    """
    with GuardiaRed() as g:
        ...trabajo offline...
    g.intentos -> destinos externos bloqueados durante el bloque ([] = ninguno)

    Anidable y seguro frente a hilos en su activación/desactivación (la
    instalación se hace una sola vez bajo cerrojo y se retira cuando sale la
    última guardia). Con varias guardias activas se aplica la más restrictiva.
    """

    def __init__(self, permitir_local=True):
        self.permitir_local = permitir_local
        self.intentos = []

    def __enter__(self):
        with _lock:
            if not _activas:
                _instalar()
            _activas.append(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.desactivar()
        return False

    activar = __enter__

    def desactivar(self):
        with _lock:
            if self in _activas:
                _activas.remove(self)
                if not _activas:
                    _desinstalar()


def guardia_activa():
    return bool(_activas)


def funciones_interceptadas():
    """Nombres de las APIs de socket que esta capa intercepta (para diagnóstico)."""
    return sorted(f"{_nombre(obj)}.{attr}" for obj, attr in _envoltorios())


def _reiniciar_para_tests():
    """Libera cualquier guardia que hubiera quedado activa (uso exclusivo en tests)."""
    with _lock:
        _activas.clear()
        if _originales:
            _desinstalar()
