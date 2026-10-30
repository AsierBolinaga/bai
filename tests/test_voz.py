"""Voz local con procesos controlados: no reproduce audio en la suite."""
import subprocess
import io
import sys
from types import SimpleNamespace

import pytest

from core import voz


def test_davefx_es_modelo_castellano():
    lector = voz.VozLocal()
    assert lector.modelo == (voz.DIRECTORIO_VOCES / "es_ES-davefx-medium.onnx").resolve()


@pytest.fixture
def proceso(monkeypatch, tmp_path):
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
    for ruta in voz.VOCES.values():
        modelo = tmp_path / ruta
        modelo.parent.mkdir(parents=True, exist_ok=True)
        modelo.touch()
        modelo.with_suffix(".onnx.json").touch()
    monkeypatch.setattr(voz, "DIRECTORIO_VOCES", tmp_path)
    monkeypatch.setattr(voz.importlib.util, "find_spec", lambda nombre: object())
    monkeypatch.setattr(voz.shutil, "which", lambda nombre: "/usr/bin/aplay")

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
    assert proceso.argumentos[-3].endswith("/core/voz.py")
    assert proceso.argumentos[-2] == "--reproducir"
    assert proceso.argumentos[-1] == str(voz.DIRECTORIO_VOCES)
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


def test_sin_piper_se_informa(monkeypatch):
    monkeypatch.setattr(voz.importlib.util, "find_spec", lambda nombre: None)
    lector = voz.VozLocal()
    assert not lector.disponible
    with pytest.raises(RuntimeError, match="Instala Piper"):
        lector.hablar("hola")


def test_modelo_ausente_se_informa(proceso, monkeypatch, tmp_path):
    (tmp_path / voz.VOCES["eu"]).unlink()
    assert "Falta el modelo" in voz.VozLocal().motivo_no_disponible


def test_reproductor_ausente_se_informa(proceso, monkeypatch):
    monkeypatch.setattr(voz.shutil, "which", lambda nombre: None)
    assert "aplay" in voz.VozLocal().motivo_no_disponible


@pytest.mark.parametrize("texto,idioma", [
    ("Hola", "es"), ("¡Hola! ¿Cómo puedo ayudarte hoy?", "es"),
    ("Kaixo", "eu"), ("Kaixo, Boli. Zer moduz zaude?", "eu"),
    ("Ondo nago, eskerrik asko. Zertan lagun zaitzaket?", "eu"),
    ("Hello, how can I help you today?", "en"), ("12345", "en"),
])
def test_deteccion_local_de_idioma(texto, idioma):
    pytest.importorskip("langid")
    assert voz.detectar_idioma(texto) == idioma


@pytest.mark.parametrize("idioma,clave", [("es", "es"), ("eu", "eu"), ("en", "en"),
                                        ("fr", "en"), ("ja", "en")])
def test_ruta_automatica_y_error_si_falta(proceso, monkeypatch, tmp_path, idioma, clave):
    monkeypatch.setattr(voz, "detectar_idioma", lambda texto: idioma)
    esperado = tmp_path / voz.VOCES[clave]
    assert voz.modelo_para_texto("texto", tmp_path) == esperado
    esperado.with_suffix(".onnx.json").unlink()
    with pytest.raises(RuntimeError, match="Falta la voz automática"):
        voz.modelo_para_texto("texto", tmp_path)


def test_sin_detector_se_informa(proceso, monkeypatch):
    monkeypatch.setattr(voz.importlib.util, "find_spec",
                        lambda nombre: None if nombre == "langid" else object())
    assert "detector local" in voz.VozLocal().motivo_no_disponible


def test_fallo_al_arrancar_libera_archivo(proceso, monkeypatch):
    errores = []

    def fallar(*args, **kw):
        errores.append(kw["stderr"])
        raise OSError("no se pudo arrancar")

    monkeypatch.setattr(voz.subprocess, "Popen", fallar)
    with pytest.raises(OSError, match="no se pudo arrancar"):
        voz.VozLocal().hablar("hola")
    assert errores[0].closed


@pytest.mark.parametrize("canales", [1, 2])
@pytest.mark.parametrize("fallo", [None, "audio", "cancelar"])
def test_worker_reproduce_pcm_y_cancela_reproductor(monkeypatch, fallo, canales):
    procesos = []
    audio = SimpleNamespace(sample_rate=22050, sample_channels=canales,
                            audio_int16_bytes=b"\x01\x02" * 100 * canales)

    class Motor:
        @staticmethod
        def load(modelo, use_cuda):
            assert modelo == "voz.onnx" and not use_cuda
            return Motor()

        def synthesize(self, texto, syn_config):
            assert texto == "hola" and syn_config["length_scale"] == 1.05
            yield audio
            if fallo == "cancelar":
                voz._cancelar(None, None)
            yield audio

    class Entrada(io.BytesIO):
        def close(self):
            self.contenido = self.getvalue()
            super().close()

    class Reproductor:
        codigo = None
        terminado = False

        def __init__(self):
            self.stdin = Entrada()

        def poll(self):
            return self.codigo

        def wait(self, timeout=None):
            self.codigo = 1 if fallo == "audio" else 0
            return self.codigo

        def terminate(self):
            self.terminado = True

    def crear(args, **kw):
        assert args == ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "22050", "-c", str(canales)]
        reproductor = Reproductor()
        procesos.append(reproductor)
        return reproductor

    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=Motor, SynthesisConfig=lambda **kw: kw))
    monkeypatch.setattr(voz.subprocess, "Popen", crear)
    if fallo == "cancelar":
        with pytest.raises(SystemExit):
            voz._reproducir("hola", "voz.onnx")
        assert procesos[0].terminado
    elif fallo == "audio":
        with pytest.raises(RuntimeError, match="reproductor"):
            voz._reproducir("hola", "voz.onnx")
    else:
        voz._reproducir("hola", "voz.onnx")
        assert procesos[0].codigo == 0
    silencio = b"\0" * (22050 * 3 * canales * 2)
    entrada = procesos[0].stdin
    contenido = entrada.contenido if entrada.closed else entrada.getvalue()
    assert contenido == silencio + audio.audio_int16_bytes * (1 if fallo == "cancelar" else 2)
    assert len(procesos) == 1
