"""Voz local con procesos controlados: no reproduce audio en la suite."""
import subprocess

import pytest

from core import voz


@pytest.fixture
def proceso(monkeypatch):
    class Proceso:
        codigo = None
        terminado = False
        matado = False
        atasco = False

        def poll(self):
            return self.codigo

        def terminate(self):
            self.terminado = True

        def wait(self, timeout=None):
            if self.atasco and not self.matado:
                raise subprocess.TimeoutExpired("voz", timeout)
            self.codigo = -15

        def kill(self):
            self.matado = True

    p = Proceso()
    monkeypatch.setattr(voz.ctypes.util, "find_library", lambda nombre: "libespeak-ng.so.1")

    def crear(argumentos, **kw):
        p.argumentos = argumentos
        p.entrada = kw["stdin"].read()
        p.errores = kw["stderr"]
        return p

    monkeypatch.setattr(voz.subprocess, "Popen", crear)
    return p


def test_lectura_usa_stdin_sin_shell_y_libera_recursos(proceso):
    lector = voz.VozLocal()
    texto = "--help; $(no ejecutar) español"
    lector.hablar(texto)
    assert proceso.entrada == texto.encode("utf-8")
    assert texto not in proceso.argumentos
    assert proceso.argumentos[-2].endswith("/core/voz.py")
    assert proceso.argumentos[-1] == "--reproducir"
    assert lector.comprobar() == (True, None)
    proceso.codigo = 0
    assert lector.comprobar() == (False, None)
    assert proceso.errores.closed


def test_fallo_audio_es_visible_y_libera_recursos(proceso):
    lector = voz.VozLocal()
    lector.hablar("hola")
    proceso.errores.write(b"audio no disponible")
    proceso.codigo = 1
    activo, error = lector.comprobar()
    assert not activo and "audio no disponible" in error
    assert proceso.errores.closed


@pytest.mark.parametrize("atasco", [False, True])
def test_detener_cancela_solo_el_proceso_propio(proceso, atasco):
    lector = voz.VozLocal()
    lector.hablar("hola")
    proceso.atasco = atasco
    lector.detener()
    assert proceso.terminado and proceso.matado == atasco
    assert proceso.errores.closed
    assert lector.comprobar() == (False, None)
    lector.detener()


def test_sin_biblioteca_se_informa(monkeypatch):
    monkeypatch.setattr(voz.ctypes.util, "find_library", lambda nombre: None)
    lector = voz.VozLocal()
    assert not lector.disponible
    with pytest.raises(RuntimeError, match="instala eSpeak NG"):
        lector.hablar("hola")


def test_fallo_al_arrancar_libera_archivo(proceso, monkeypatch):
    errores = []

    def fallar(*args, **kw):
        errores.append(kw["stderr"])
        raise OSError("no se pudo arrancar")

    monkeypatch.setattr(voz.subprocess, "Popen", fallar)
    with pytest.raises(OSError, match="no se pudo arrancar"):
        voz.VozLocal().hablar("hola")
    assert errores[0].closed
