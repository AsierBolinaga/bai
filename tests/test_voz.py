"""Voz local con procesos controlados: no reproduce audio en la suite."""
import subprocess
import io
import sys
from types import SimpleNamespace

import pytest

from core import voz


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
    modelo = tmp_path / "voz.onnx"
    modelo.touch()
    (tmp_path / "voz.onnx.json").touch()
    monkeypatch.setenv("BAI_VOZ_MODELO", str(modelo))
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
    assert proceso.argumentos[-1].endswith("voz.onnx")
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
    monkeypatch.setenv("BAI_VOZ_MODELO", str(tmp_path / "ausente.onnx"))
    assert "Falta el modelo" in voz.VozLocal().motivo_no_disponible


def test_reproductor_ausente_se_informa(proceso, monkeypatch):
    monkeypatch.setattr(voz.shutil, "which", lambda nombre: None)
    assert "aplay" in voz.VozLocal().motivo_no_disponible


@pytest.mark.parametrize("nombre,inicio", [
    ("es_ES-carlfm-x_low.onnx", "Hola"),
    ("en_GB-northern_english_male-medium.onnx", "Hello"),
    ("eu_ES-antton-medium.onnx", "Kaixo"),
])
def test_muestra_en_idioma_del_nombre_del_modelo(monkeypatch, nombre, inicio):
    monkeypatch.setenv("BAI_VOZ_MODELO", nombre)
    assert voz.VozLocal().texto_prueba.startswith(inicio)


def test_listado_modelos_completos_y_seleccion_cancela_audio(proceso, monkeypatch, tmp_path):
    carpeta = tmp_path / "voces con espacios"
    carpeta.mkdir()
    otro = carpeta / "segunda.onnx"
    otro.touch()
    (carpeta / "segunda.onnx.json").touch()
    (carpeta / "incompleta.onnx").touch()
    monkeypatch.setattr(voz, "DIRECTORIO_VOCES", carpeta)
    lector = voz.VozLocal()
    assert set(lector.modelos_instalados()) == {lector.modelo, otro}
    lector.hablar("hola")
    lector.seleccionar_modelo(otro)
    assert lector.modelo == otro and proceso.terminado
    with pytest.raises(ValueError, match="incompleto"):
        lector.seleccionar_modelo(carpeta / "incompleta.onnx")
    assert lector.modelo == otro


def test_fallo_al_arrancar_libera_archivo(proceso, monkeypatch):
    errores = []

    def fallar(*args, **kw):
        errores.append(kw["stderr"])
        raise OSError("no se pudo arrancar")

    monkeypatch.setattr(voz.subprocess, "Popen", fallar)
    with pytest.raises(OSError, match="no se pudo arrancar"):
        voz.VozLocal().hablar("hola")
    assert errores[0].closed


@pytest.mark.parametrize("fallo", [None, "audio", "cancelar"])
def test_worker_reproduce_pcm_y_cancela_reproductor(monkeypatch, fallo):
    procesos = []
    audio = SimpleNamespace(sample_rate=22050, sample_channels=1, audio_int16_bytes=b"\0\0" * 100)

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

    class Reproductor:
        stdin = io.BytesIO()
        codigo = None
        terminado = False

        def poll(self):
            return self.codigo

        def wait(self, timeout=None):
            self.codigo = 1 if fallo == "audio" else 0
            return self.codigo

        def terminate(self):
            self.terminado = True

    def crear(args, **kw):
        assert args == ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "22050", "-c", "1"]
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
