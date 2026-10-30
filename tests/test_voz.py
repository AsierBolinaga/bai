"""Voz local con procesos controlados: no reproduce audio en la suite."""
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
        terminado = False
        eventos = []
        inicios = 0
        ordenes = []

        def iniciar(self, opciones):
            self.inicios += 1

        def enviar(self, orden, contenido):
            self.ordenes.append((orden, contenido))

        def comprobar(self):
            eventos, self.eventos = self.eventos, []
            return eventos

        def cancelar(self):
            self.eventos = []

        def cerrar(self):
            self.terminado = True

    p = Proceso()
    for ruta in voz.VOCES.values():
        modelo = tmp_path / ruta
        modelo.parent.mkdir(parents=True, exist_ok=True)
        modelo.touch()
        modelo.with_suffix(".onnx.json").touch()
    monkeypatch.setattr(voz, "DIRECTORIO_VOCES", tmp_path)
    monkeypatch.setattr(voz.importlib.util, "find_spec", lambda nombre: object())
    monkeypatch.setattr(voz.shutil, "which", lambda nombre: "/usr/bin/aplay")

    monkeypatch.setattr(voz, "ProcesoAudio", lambda tipo: p)
    return p


def test_lectura_usa_worker_y_lo_conserva_al_terminar(proceso):
    lector = voz.VozLocal()
    texto = "--help; $(no ejecutar) español"
    lector.hablar(texto)
    assert proceso.ordenes == [("hablar", texto)]
    assert lector.comprobar() == (True, None)
    proceso.eventos = [("fin", "")]
    assert lector.comprobar() == (False, None)
    assert not proceso.terminado
    lector.hablar("otra frase")
    assert len(proceso.ordenes) == 2


def test_fallo_audio_es_visible(proceso):
    lector = voz.VozLocal()
    lector.hablar("hola")
    proceso.eventos = [("error", "audio no disponible")]
    activo, error = lector.comprobar()
    assert not activo and "audio no disponible" in error


def test_pausar_conserva_worker_y_desactivar_lo_cierra(proceso):
    lector = voz.VozLocal()
    lector.hablar("hola")
    lector.pausar()
    assert not proceso.terminado and lector.comprobar() == (False, None)
    lector.detener()
    assert proceso.terminado
    assert lector.comprobar() == (False, None)
    lector.detener()


def test_sin_piper_se_informa(monkeypatch):
    monkeypatch.setattr(voz.importlib.util, "find_spec", lambda nombre: None)
    lector = voz.VozLocal()
    assert not lector.disponible
    with pytest.raises(RuntimeError, match="Instala Piper"):
        lector.hablar("hola")


def test_modelo_ausente_no_bloquea_otras_voces(proceso, tmp_path):
    (tmp_path / voz.VOCES["eu"]).unlink()
    lector = voz.VozLocal()
    assert lector.disponible and lector.motivo_no_disponible is None
    lector.hablar("hola")
    assert proceso.ordenes == [("hablar", "hola")]


@pytest.mark.parametrize("instaladas", [
    (), ("es",), ("eu",), ("en",), ("es", "eu"), ("es", "en"), ("eu", "en"), ("es", "eu", "en"),
])
@pytest.mark.parametrize("idioma", ["es", "eu", "en", "fr"])
def test_seleccion_independiente_y_prioridad_de_alternativas(
        proceso, monkeypatch, tmp_path, instaladas, idioma):
    for clave, ruta in voz.VOCES.items():
        if clave not in instaladas:
            (tmp_path / ruta).unlink()
    monkeypatch.setattr(voz, "detectar_idioma", lambda texto: idioma)
    lector = voz.VozLocal()
    avisos = []
    assert lector.disponible == bool(instaladas)
    if not instaladas:
        assert "al menos una voz" in lector.motivo_no_disponible
        with pytest.raises(RuntimeError, match="ninguna voz Piper completa"):
            voz.modelo_para_texto("texto", tmp_path, avisar=avisos.append)
        with pytest.raises(RuntimeError, match="ninguna voz Piper completa"):
            lector.activar()
        return
    preferida = idioma if idioma in voz.VOCES else "en"
    elegida = preferida if preferida in instaladas else next(
        clave for clave in voz.PRIORIDAD_ALTERNATIVAS if clave in instaladas)
    assert voz.modelo_para_texto("texto", tmp_path, avisar=avisos.append) == tmp_path / voz.VOCES[elegida]
    if elegida == preferida:
        assert avisos == []
    else:
        assert len(avisos) == 1
        assert f"voz de {voz.NOMBRES_VOCES[elegida]} como alternativa" in avisos[0]
        assert "sin traducir" in avisos[0]


def test_aviso_no_apaga_voz_y_se_consume_una_vez(proceso):
    lector = voz.VozLocal()
    lector.hablar("kaixo")
    proceso.eventos = [("aviso", "Uso la voz de castellano como alternativa.")]
    assert lector.comprobar() == (True, None)
    assert lector.recoger_avisos() == ["Uso la voz de castellano como alternativa."]
    assert lector.recoger_avisos() == []
    proceso.eventos = [("fin", "")]
    assert lector.comprobar() == (False, None)
    lector.hablar("hola")
    assert not proceso.terminado


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
def test_ruta_automatica_e_ignora_modelos_incompletos(proceso, monkeypatch, tmp_path, idioma, clave):
    monkeypatch.setattr(voz, "detectar_idioma", lambda texto: idioma)
    esperado = tmp_path / voz.VOCES[clave]
    assert voz.modelo_para_texto("texto", tmp_path) == esperado
    esperado.with_suffix(".onnx.json").unlink()
    avisos = []
    alternativa = voz.modelo_para_texto("texto", tmp_path, avisar=avisos.append)
    assert alternativa != esperado and len(avisos) == 1
    assert clave not in voz.modelos_instalados(tmp_path)


def test_sin_detector_se_informa(proceso, monkeypatch):
    monkeypatch.setattr(voz.importlib.util, "find_spec",
                        lambda nombre: None if nombre == "langid" else object())
    assert "detector local" in voz.VozLocal().motivo_no_disponible


def test_fallo_al_arrancar_libera_archivo(proceso, monkeypatch):
    def fallar(*args):
        raise OSError("no se pudo arrancar")

    monkeypatch.setattr(proceso, "iniciar", fallar)
    with pytest.raises(OSError, match="no se pudo arrancar"):
        voz.VozLocal().hablar("hola")


@pytest.mark.parametrize("canales", [1, 2])
@pytest.mark.parametrize("fallo", [None, "audio", "cancelar", "pausar"])
@pytest.mark.parametrize("segundos", [0, 0.2, 3])
def test_worker_reproduce_pcm_y_cancela_reproductor(monkeypatch, fallo, canales, segundos):
    from core.audio_worker import Trabajo, Cancelado

    trabajo = Trabajo() if fallo == "pausar" else None
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
            if fallo == "pausar":
                trabajo.cancelar()
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
    def reproducir():
        voz._reproducir("hola", "voz.onnx", trabajo=trabajo, silencio=segundos)

    if fallo == "cancelar":
        with pytest.raises(SystemExit):
            reproducir()
        assert procesos[0].terminado
    elif fallo == "pausar":
        with pytest.raises(Cancelado):
            reproducir()
        assert procesos[0].terminado
    elif fallo == "audio":
        with pytest.raises(RuntimeError, match="reproductor"):
            reproducir()
    else:
        reproducir()
        assert procesos[0].codigo == 0
    silencio = b"\0" * (round(22050 * segundos) * canales * 2)
    entrada = procesos[0].stdin
    contenido = entrada.contenido if entrada.closed else entrada.getvalue()
    assert contenido == silencio + audio.audio_int16_bytes * (1 if fallo in ("cancelar", "pausar") else 2)
    assert len(procesos) == 1
