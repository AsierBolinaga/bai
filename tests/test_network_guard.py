"""Guardia de red (core/network_guard.py): sólo destinos locales durante trabajo offline."""
import socket
import threading

import pytest

from core import network_guard as ng
from core.network_guard import AccesoRedBloqueado, GuardiaRed, es_destino_local, guardia_activa


@pytest.fixture
def servidor_local():
    """Servidor TCP en loopback para comprobar que lo local sigue permitido."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    hilo = threading.Thread(target=lambda: (srv.accept()[0].close() if True else None), daemon=True)
    hilo.start()
    yield srv.getsockname()
    srv.close()


@pytest.mark.parametrize("host,esperado", [
    ("localhost", True), ("127.0.0.1", True), ("::1", True), ("127.5.5.5", True), ("LOCALHOST", True),
    ("ollama.localhost", True), ("/tmp/socket.sock", True), (None, True), (b"127.0.0.1", True), ("", True),
    ("api.openai.com", False), ("gpt4all.io", False), ("192.168.1.10", False), ("8.8.8.8", False),
    ("huggingface.co", False), ("2001:db8::1", False), (12345, False),
    # IPv6: IPv4-mapped, corchetes, forma hexadecimal, zona, no especificada
    ("::ffff:127.0.0.1", True), ("::ffff:7f00:1", True), ("[::1]", True), ("[::1]:8080", True), ("::", True),
    ("::ffff:8.8.8.8", False), ("fe80::1%eth0", False), ("::1%lo", False), ("[2001:db8::1]", False),
    ("127.0.0.1.", True), ("localhost.", True), ("mi-pc.local", False), ("127.0.0.1.evil.com", False),
])
def test_es_destino_local(host, esperado):
    assert es_destino_local(host) is esperado


def test_bloquea_externo_y_registra():
    with GuardiaRed() as g:
        with pytest.raises(AccesoRedBloqueado):
            socket.create_connection(("api.openai.com", 443), timeout=0.5)
        with pytest.raises(OSError):  # también es un OSError normal para las librerías
            socket.getaddrinfo("gpt4all.io", 443)
    assert g.intentos == ["api.openai.com", "gpt4all.io"]


def test_bloquea_connect_directo_por_ip():
    with GuardiaRed() as g:
        s = socket.socket()
        try:
            with pytest.raises(AccesoRedBloqueado):
                s.connect(("93.184.216.34", 80))
            with pytest.raises(AccesoRedBloqueado):
                s.connect_ex(("93.184.216.34", 80))
        finally:
            s.close()
    assert g.intentos == ["93.184.216.34", "93.184.216.34"]


def test_permite_loopback(servidor_local):
    with GuardiaRed() as g:
        c = socket.create_connection(servidor_local, timeout=2)
        c.close()
    assert g.intentos == []


def test_permitir_local_false_bloquea_tambien_loopback(servidor_local):
    with GuardiaRed(permitir_local=False) as g:
        with pytest.raises(AccesoRedBloqueado):
            socket.create_connection(servidor_local, timeout=2)
    assert g.intentos == [servidor_local[0]]


def _instantanea():
    import ssl
    return (socket.socket.connect, socket.socket.send, socket.socket.sendall, socket.socket.sendto,
            socket.socket.sendmsg, socket.socket.sendfile, socket.getaddrinfo, socket.gethostbyname,
            ssl.SSLSocket.send, ssl.SSLSocket.write, ssl.SSLSocket.do_handshake)


def test_restaura_socket_al_salir():
    antes = _instantanea()
    with GuardiaRed():
        assert all(a is not b for a, b in zip(antes, _instantanea())) and guardia_activa()
    assert _instantanea() == antes
    assert not guardia_activa()


def test_restaura_aunque_haya_excepcion():
    connect = socket.socket.connect
    with pytest.raises(RuntimeError):
        with GuardiaRed():
            raise RuntimeError("x")
    assert socket.socket.connect is connect


def test_anidamiento_registra_en_todas_y_restaura_al_final():
    connect = socket.socket.connect
    with GuardiaRed() as externa:
        with GuardiaRed() as interna:
            with pytest.raises(AccesoRedBloqueado):
                socket.getaddrinfo("example.com", 80)
        assert guardia_activa()  # la externa sigue activa
        assert socket.socket.connect is not connect
    assert externa.intentos == ["example.com"] and interna.intentos == ["example.com"]
    assert socket.socket.connect is connect


def test_anidamiento_aplica_la_mas_restrictiva(servidor_local):
    with GuardiaRed(permitir_local=True):
        with GuardiaRed(permitir_local=False) as estricta:
            with pytest.raises(AccesoRedBloqueado):
                socket.create_connection(servidor_local, timeout=2)
        # al salir la estricta, lo local vuelve a permitirse
        socket.create_connection(servidor_local, timeout=2).close()
    assert estricta.intentos == [servidor_local[0]]



# --------------------------------------------------------------------------- UDP (sin connect)
@pytest.fixture
def udp_local():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(2)
    yield srv
    srv.close()


def test_udp_sendto_externo_bloqueado_ipv4_e_ipv6():
    with GuardiaRed() as g:
        s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        try:
            with pytest.raises(AccesoRedBloqueado):
                s4.sendto(b"dns?", ("8.8.8.8", 53))
            with pytest.raises(AccesoRedBloqueado):
                s4.sendto(b"dns?", 0, ("1.1.1.1", 53))          # variante con flags
            with pytest.raises(AccesoRedBloqueado):
                s6.sendto(b"dns?", ("2001:4860:4860::8888", 53))
            with pytest.raises(AccesoRedBloqueado):
                s6.sendto(b"x", ("::ffff:8.8.8.8", 53))          # IPv4 externa mapeada en IPv6
        finally:
            s4.close(); s6.close()
    assert g.intentos == ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "::ffff:8.8.8.8"]


def test_udp_sendmsg_externo_bloqueado():
    with GuardiaRed() as g:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(AccesoRedBloqueado):
                s.sendmsg([b"x"], [], 0, ("8.8.8.8", 53))
        finally:
            s.close()
    assert g.intentos == ["8.8.8.8"]


def test_udp_local_permitido(udp_local):
    with GuardiaRed() as g:
        c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            c.sendto(b"hola", udp_local.getsockname())
            assert udp_local.recvfrom(16)[0] == b"hola"
            c.sendmsg([b"otra"], [], 0, udp_local.getsockname())
            assert udp_local.recvfrom(16)[0] == b"otra"
            c.connect(udp_local.getsockname())               # UDP "conectado"
            c.send(b"tercera")                               # send() sin destino: ya validado en connect
            assert udp_local.recvfrom(16)[0] == b"tercera"
        finally:
            c.close()
    assert g.intentos == []


def test_udp_connect_externo_bloqueado():
    with GuardiaRed() as g:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(AccesoRedBloqueado):
                s.connect(("8.8.8.8", 53))
        finally:
            s.close()
    assert g.intentos == ["8.8.8.8"]


def test_udp_ipv6_loopback_permitido():
    srv = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    try:
        srv.bind(("::1", 0))
    except OSError:
        pytest.skip("IPv6 loopback no disponible")
    srv.settimeout(2)
    with GuardiaRed() as g:
        c = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        c.sendto(b"v6", srv.getsockname()[:2])
        assert srv.recvfrom(8)[0] == b"v6"
        c.close()
    srv.close()
    assert g.intentos == []


# --------------------------------------------------------------------------- DNS: todas las APIs
@pytest.mark.parametrize("llamada,destino", [
    (lambda: socket.getaddrinfo("gpt4all.io", 443), "gpt4all.io"),
    (lambda: socket.getaddrinfo("gpt4all.io", 443, socket.AF_INET6), "gpt4all.io"),
    (lambda: socket.gethostbyname("huggingface.co"), "huggingface.co"),
    (lambda: socket.gethostbyname_ex("huggingface.co"), "huggingface.co"),
    (lambda: socket.gethostbyaddr("8.8.8.8"), "8.8.8.8"),
    (lambda: socket.gethostbyaddr("2001:4860:4860::8888"), "2001:4860:4860::8888"),
    (lambda: socket.getnameinfo(("8.8.8.8", 53), 0), "8.8.8.8"),
    (lambda: socket.getnameinfo(("2001:4860:4860::8888", 53, 0, 0), 0), "2001:4860:4860::8888"),
])
def test_resolucion_dns_externa_bloqueada(llamada, destino):
    with GuardiaRed() as g:
        with pytest.raises(AccesoRedBloqueado):
            llamada()
    assert g.intentos == [destino]


def test_getfqdn_externo_no_resuelve():
    """getfqdn() traga los errores de gethostbyaddr: debe devolver el literal y dejar registrado el intento."""
    with GuardiaRed() as g:
        assert socket.getfqdn("8.8.8.8") == "8.8.8.8"
    assert g.intentos == ["8.8.8.8"]


def test_resolucion_local_permitida():
    with GuardiaRed() as g:
        assert socket.getaddrinfo("localhost", 80)
        assert socket.getaddrinfo("127.0.0.1", 80, socket.AF_INET)
        assert socket.getaddrinfo("::1", 80, socket.AF_INET6)
        assert socket.gethostbyname("localhost") == "127.0.0.1"
        assert socket.getnameinfo(("127.0.0.1", 80), socket.NI_NUMERICHOST)[0] == "127.0.0.1"
        assert socket.getnameinfo(("::1", 80, 0, 0), socket.NI_NUMERICHOST)[0] == "::1"
    assert g.intentos == []


def test_librerias_http_quedan_bloqueadas():
    """http.client / urllib pasan por socket: deben fallar con un OSError y registrar el destino."""
    import http.client
    import urllib.request
    with GuardiaRed() as g:
        with pytest.raises(OSError):
            http.client.HTTPSConnection("api.openai.com", timeout=1).connect()
        with pytest.raises(OSError):
            urllib.request.urlopen("http://gpt4all.io/models/models3.json", timeout=1)
    assert g.intentos == ["api.openai.com", "gpt4all.io"]


# --------------------------------------------------------------------------- familias no INET
def test_sockets_unix_permitidos(tmp_path):
    ruta = str(tmp_path / "s.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(ruta)
    srv.listen(1)
    with GuardiaRed() as g:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.connect(ruta)
        c.close()
        d = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        d.close()
    srv.close()
    assert g.intentos == []


def test_tcp_ipv6_loopback_permitido_y_externo_bloqueado():
    srv = socket.socket(socket.AF_INET6)
    try:
        srv.bind(("::1", 0))
    except OSError:
        pytest.skip("IPv6 loopback no disponible")
    srv.listen(1)
    with GuardiaRed() as g:
        socket.create_connection(srv.getsockname()[:2], timeout=2).close()
        s = socket.socket(socket.AF_INET6)
        with pytest.raises(AccesoRedBloqueado):
            s.connect(("2001:db8::1", 80))
        s.close()
    srv.close()
    assert g.intentos == ["2001:db8::1"]


# --------------------------------------------------------------------------- hilos
def test_afecta_a_todos_los_hilos_del_proceso():
    """Semántica documentada: la guardia es global al proceso (también bloquea otros hilos)."""
    resultados = []

    def otro_hilo():
        try:
            socket.getaddrinfo("api.openai.com", 443)
            resultados.append("permitido")
        except AccesoRedBloqueado:
            resultados.append("bloqueado")

    with GuardiaRed() as g:
        t = threading.Thread(target=otro_hilo)
        t.start()
        t.join()
    assert resultados == ["bloqueado"] and g.intentos == ["api.openai.com"]


def test_activacion_concurrente_desde_varios_hilos_deja_socket_restaurado():
    """Entradas/salidas simultáneas desde muchos hilos no corrompen el estado global."""
    originales = (socket.socket.connect, socket.socket.sendto, socket.getaddrinfo, socket.gethostbyname)
    errores = []

    def trabajo():
        try:
            for _ in range(50):
                with GuardiaRed():
                    with pytest.raises(AccesoRedBloqueado):
                        socket.getaddrinfo("example.com", 80)
        except Exception as e:  # pragma: no cover - sólo si falla
            errores.append(e)

    hilos = [threading.Thread(target=trabajo) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert errores == []
    assert not guardia_activa()
    assert (socket.socket.connect, socket.socket.sendto, socket.getaddrinfo, socket.gethostbyname) == originales


def test_funciones_interceptadas_documentadas():
    from core.network_guard import funciones_interceptadas
    assert set(funciones_interceptadas()) == {
        "socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto", "socket.socket.sendmsg",
        "socket.socket.send", "socket.socket.sendall", "socket.socket.sendfile",
        "ssl.SSLSocket.send", "ssl.SSLSocket.sendall", "ssl.SSLSocket.write", "ssl.SSLSocket.sendfile",
        "ssl.SSLSocket.do_handshake",
        "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr",
        "socket.getnameinfo"}


# --------------------------------------------------------------------------- límites conocidos (documentados)
def test_limite_documentado_subproceso_no_queda_cubierto():
    """La guardia Python NO cubre subprocesos: esto lo resuelve core/aislamiento.py.
    El test fija el límite para que nadie asuma lo contrario."""
    import subprocess
    import sys
    with GuardiaRed():
        r = subprocess.run([sys.executable, "-c",
                            "import socket; s=socket.socket(); s.settimeout(0.3); print(s.connect_ex(('127.0.0.1', 9)))"],
                           capture_output=True, text=True)
    # El hijo ejecuta connect_ex sin ser interceptado (devuelve un errno, no AccesoRedBloqueado)
    assert r.returncode == 0 and r.stdout.strip().isdigit()



# --------------------------------------------------------------------------- sockets conectados ANTES de la guardia
class _SocketPeerExterno(socket.socket):
    """Socket real conectado a loopback que declara un extremo remoto externo:
    simula una conexión abierta hacia fuera antes de activar la guardia."""

    def getpeername(self):
        return ("93.184.216.34", 443)


@pytest.fixture
def servidor_tcp():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    yield srv
    srv.close()


def test_send_sobre_socket_externo_preconectado_bloqueado(servidor_tcp, tmp_path):
    s = _SocketPeerExterno()
    s.connect(servidor_tcp.getsockname())  # antes de la guardia
    fichero = tmp_path / "f.bin"
    fichero.write_bytes(b"datos")
    with GuardiaRed() as g:
        with pytest.raises(AccesoRedBloqueado):
            s.send(b"x")
        with pytest.raises(AccesoRedBloqueado):
            s.sendall(b"x")
        with pytest.raises(AccesoRedBloqueado):
            s.sendmsg([b"x"])                      # sin destino explícito: usa el peer
        with pytest.raises(AccesoRedBloqueado):
            s.sendmsg([b"x"], [], 0, None)
        with open(fichero, "rb") as f:
            with pytest.raises(AccesoRedBloqueado):
                s.sendfile(f)
    s.close()
    assert g.intentos == ["93.184.216.34"] * 5


def test_sendmsg_con_destino_local_pero_peer_externo_se_permite_por_destino(servidor_tcp):
    """Con destino explícito manda el destino (UDP): local -> permitido."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(2)
    c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with GuardiaRed() as g:
        c.sendmsg([b"ok"], [], 0, srv.getsockname())
        assert srv.recvfrom(4)[0] == b"ok"
    c.close(); srv.close()
    assert g.intentos == []


def test_send_sobre_socket_local_preconectado_permitido(servidor_tcp):
    c = socket.socket()
    c.connect(servidor_tcp.getsockname())       # antes de la guardia
    conexion, _ = servidor_tcp.accept()
    conexion.settimeout(2)
    with GuardiaRed() as g:
        c.send(b"a")
        c.sendall(b"b")
        c.sendmsg([b"c"])
        assert conexion.recv(3) == b"abc"
    c.close(); conexion.close()
    assert g.intentos == []


def test_send_sobre_socket_no_conectado_no_se_bloquea_pero_falla_solo():
    """Sin peer no hay destino que validar: la operación falla por sí misma (ENOTCONN/EPIPE)."""
    s = socket.socket()
    with GuardiaRed() as g:
        with pytest.raises(OSError) as exc:
            s.send(b"x")
        assert not isinstance(exc.value, AccesoRedBloqueado)
    s.close()
    assert g.intentos == []


# --------------------------------------------------------------------------- TLS
def test_tls_sobre_peer_externo_bloqueado_en_todas_las_escrituras(servidor_tcp):
    import ssl

    class SSLPeerExterno(ssl.SSLSocket):
        def getpeername(self):
            return ("93.184.216.34", 443)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.sslsocket_class = SSLPeerExterno
    base = socket.socket()
    base.connect(servidor_tcp.getsockname())
    tls = ctx.wrap_socket(base, do_handshake_on_connect=False)
    with GuardiaRed() as g:
        for operacion in (lambda: tls.do_handshake(), lambda: tls.send(b"x"), lambda: tls.sendall(b"x"),
                          lambda: tls.write(b"x")):
            with pytest.raises(AccesoRedBloqueado):
                operacion()
    tls.close()
    assert g.intentos == ["93.184.216.34"] * 4


@pytest.fixture(scope="module")
def certificado(tmp_path_factory):
    import shutil
    import subprocess
    if not shutil.which("openssl"):
        pytest.skip("openssl no disponible para generar un certificado de prueba")
    d = tmp_path_factory.mktemp("tls")
    cert, key = d / "cert.pem", d / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                    "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"], check=True, capture_output=True)
    return str(cert), str(key)


def test_tls_real_sobre_loopback_permitido(certificado):
    """Un servidor TLS local: handshake y escritura cifrada deben funcionar bajo la guardia."""
    import ssl
    cert, key = certificado
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    recibido = []

    def servidor():
        conn, _ = srv.accept()
        with sctx.wrap_socket(conn, server_side=True) as tls_srv:
            recibido.append(tls_srv.recv(32))
            tls_srv.sendall(b"pong")

    hilo = threading.Thread(target=servidor, daemon=True)
    hilo.start()
    cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cctx.load_verify_locations(cert)
    with GuardiaRed() as g:
        with cctx.wrap_socket(socket.create_connection(srv.getsockname(), timeout=5),
                              server_hostname="localhost") as tls:
            tls.sendall(b"ping")
            assert tls.recv(4) == b"pong"
    hilo.join(5)
    srv.close()
    assert recibido == [b"ping"] and g.intentos == []
