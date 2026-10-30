"""Pruebas de escucha sin activar el micrófono ni descargar modelos."""
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from core import escucha


def test_ruido_que_vad_confunde_con_voz_no_impide_cerrar_frase():
    filtro = escucha.FiltroRuido([100] * escucha.BLOQUES_CALIBRACION)
    detector = escucha.DetectorFrase()
    for _ in range(1000):
        assert detector.agregar(b"ruido", filtro.es_voz(100, True)) is None
    assert not detector.iniciada
    for _ in range(20):
        assert detector.agregar(b"voz", filtro.es_voz(1500, True)) is None
    for _ in range(166):
        assert detector.agregar(b"ruido", filtro.es_voz(100, True)) is None
    frase = detector.agregar(b"ruido", filtro.es_voz(100, True))
    assert frase is not None and b"voz" * 20 in frase


def test_golpes_cortos_no_reinician_silencio_y_vad_sigue_siendo_necesario():
    filtro = escucha.FiltroRuido([100] * 34)
    assert filtro.umbral == 400
    for _ in range(100):
        assert not filtro.es_voz(3000, False)
    for _ in range(4):
        assert not filtro.es_voz(3000, True)
    assert not filtro.es_voz(100, True)
    for _ in range(4):
        assert not filtro.es_voz(3000, True)
    assert filtro.es_voz(3000, True)


def test_calibracion_resiste_pico_aislado_y_no_deja_umbral_cero():
    assert escucha.FiltroRuido([0] * 34).umbral == 200
    assert escucha.FiltroRuido([100] * 33 + [30000]).umbral == 400


def test_envia_solo_tras_cinco_segundos_completos_sin_voz():
    d = escucha.DetectorFrase()
    for _ in range(12):
        assert d.agregar(b"voz", True) is None
    for _ in range(166):
        assert d.agregar(b"silencio", False) is None
    assert 166 * 480 / 16000 < 5
    assert 167 * 480 / 16000 >= 5
    assert d.agregar(b"silencio", False) == b"voz" * 12


def test_hablar_otra_vez_reinicia_los_cinco_segundos():
    d = escucha.DetectorFrase()
    for _ in range(12):
        d.agregar(b"a", True)
    for _ in range(100):
        d.agregar(b"p", False)
    assert d.agregar(b"b", True) is None
    for _ in range(166):
        assert d.agregar(b"s", False) is None
    assert d.agregar(b"s", False) == b"a" * 12 + b"p" * 100 + b"b"


def test_silencio_no_envia_nada_y_preroll_es_acotado():
    d = escucha.DetectorFrase()
    for _ in range(10000):
        assert d.agregar(b"s", False) is None
    assert not d.iniciada and len(d.previos) == 10 and not d.bloques
    for _ in range(10):
        d.agregar(b"v", True)
    for _ in range(166):
        d.agregar(b"s", False)
    assert d.agregar(b"s", False) == b"s" * 9 + b"v" * 10


def test_ruido_muy_corto_no_genera_frase():
    d = escucha.DetectorFrase()
    d.agregar(b"clic", True)
    for _ in range(167):
        assert d.agregar(b"s", False) is None
    assert not d.iniciada


def test_limite_de_frase_informa_sin_enviar_texto_parcial():
    d = escucha.DetectorFrase()
    for _ in range(d.limite_total - 1):
        assert d.agregar(b"v", True) is None
    with pytest.raises(RuntimeError, match="90 segundos"):
        d.agregar(b"v", True)


@pytest.mark.parametrize("modulo", ["sounddevice", "webrtcvad", "faster_whisper"])
def test_dependencia_ausente_es_explicita(monkeypatch, modulo):
    monkeypatch.setattr(escucha.importlib.util, "find_spec",
                        lambda nombre: None if nombre == modulo else object())
    with pytest.raises(RuntimeError, match="requirements-escucha"):
        escucha.EscuchaLocal().iniciar()


def test_modelo_ausente_no_se_descarga(monkeypatch, tmp_path):
    monkeypatch.setattr(escucha.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(escucha, "DIRECTORIO_MODELO", tmp_path)
    with pytest.raises(RuntimeError, match="--preparar"):
        escucha.EscuchaLocal().iniciar()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("idioma", [None, "es", "eu", "en"])
def test_transcripcion_local_multilingue_sin_traduccion(monkeypatch, idioma):
    import numpy as np

    llamadas = {}

    class Modelo:
        def __init__(self, ruta, **kw):
            llamadas["modelo"] = (ruta, kw)

        def transcribe(self, audio, **kw):
            llamadas["audio"] = audio
            llamadas["opciones"] = kw
            return iter([SimpleNamespace(text=" Kaixo "), SimpleNamespace(text=" Boli ")]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Modelo))
    assert escucha.transcribir(b"\0\0\xff\x7f", idioma) == "Kaixo Boli"
    assert llamadas["modelo"][1]["local_files_only"] is True
    assert llamadas["modelo"][1]["compute_type"] == "int8"
    assert llamadas["opciones"]["task"] == "transcribe"
    assert llamadas["opciones"]["language"] == idioma
    assert llamadas["audio"].dtype == np.float32
    assert len(llamadas["audio"]) == 2


@pytest.mark.parametrize("desbordado", [False, True])
def test_captura_cierra_microfono_y_detecta_perdida_audio(monkeypatch, desbordado):
    estado = {"lecturas": 0, "cerrado": False}
    silencio = b"\0\0" * escucha.MUESTRAS_BLOQUE
    bloque = b"\xe8\x03" * escucha.MUESTRAS_BLOQUE

    class Entrada:
        def __init__(self, **kw):
            assert kw == dict(samplerate=16000, channels=1, dtype="int16", blocksize=480)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            estado["cerrado"] = True

        def read(self, muestras):
            estado["lecturas"] += 1
            hablando = escucha.BLOQUES_CALIBRACION < estado["lecturas"] <= escucha.BLOQUES_CALIBRACION + 20
            return bloque if hablando else silencio, desbordado

    class Vad:
        def __init__(self, modo):
            assert modo == 2

        def is_speech(self, pcm, frecuencia):
            return True  # Reproduce ruido que el VAD clasifica erróneamente como habla.

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(RawInputStream=Entrada))
    monkeypatch.setitem(sys.modules, "webrtcvad", SimpleNamespace(Vad=Vad))
    if desbordado:
        with pytest.raises(RuntimeError, match="perdido audio"):
            escucha.capturar_frase()
    else:
        assert escucha.capturar_frase().endswith(bloque * 20)
        assert estado["lecturas"] == escucha.BLOQUES_CALIBRACION + 20 + 167
    assert estado["cerrado"]


@pytest.fixture
def lanzar(monkeypatch):
    from core import audio_worker
    original = subprocess.Popen
    monkeypatch.setattr(escucha.EscuchaLocal, "motivo_no_disponible", property(lambda _: None))

    def crear(codigo, idioma=None):
        def popen(argumentos, **kw):
            assert argumentos[1:4] == ["-m", "core.audio_worker", "escucha"]
            assert not kw.get("shell")
            return original([sys.executable, "-c", codigo], **kw)

        monkeypatch.setattr(audio_worker.subprocess, "Popen", popen)
        micro = escucha.EscuchaLocal()
        micro.iniciar(idioma)
        return micro

    return crear


def recoger(micro):
    eventos = []
    limite = time.monotonic() + 5
    while time.monotonic() < limite:
        eventos.extend(micro.comprobar())
        if any(tipo in ("texto", "error") for tipo, _ in eventos):
            return eventos
        time.sleep(0.01)
    pytest.fail("el proceso de escucha no termina")


def test_proceso_entrega_texto_y_libera_recursos(lanzar):
    codigo = f"print({json.dumps([1, 'texto', 'Hola Boli'])!r}, flush=True)"
    micro = lanzar(codigo)
    try:
        assert ("texto", "Hola Boli") in recoger(micro)
        errores = micro._worker._errores
    finally:
        micro.detener()
    assert errores.closed and micro.comprobar() == []


def test_error_del_subproceso_es_visible(lanzar):
    micro = lanzar("import sys; print('sin dispositivo', file=sys.stderr); sys.exit(1)")
    try:
        assert any(tipo == "error" and "sin dispositivo" in texto for tipo, texto in recoger(micro))
    finally:
        micro.detener()


@pytest.mark.parametrize("salida", ["no es json", '[1, "texto", ""]', '[1, "texto", "   "]'])
def test_evento_invalido_no_parece_una_transcripcion(lanzar, salida):
    micro = lanzar(f"print({salida!r}, flush=True)")
    try:
        eventos = recoger(micro)
        assert any(tipo == "error" for tipo, _ in eventos)
        assert not any(tipo == "texto" for tipo, _ in eventos)
    finally:
        micro.detener()


def test_desactivar_termina_proceso_y_descarta_eventos_pendientes(lanzar):
    micro = lanzar("import time; print('[1, \"estado\", \"listo\"]', flush=True); time.sleep(30)")
    proceso = micro._worker.proceso
    inicio = time.monotonic()
    micro.detener()
    assert proceso.poll() is not None
    assert time.monotonic() - inicio < 2
    assert micro.comprobar() == []
    micro.detener()


def test_idioma_explicito_llega_al_proceso(lanzar):
    micro = lanzar("print('[1, \"texto\", \"Kaixo\"]', flush=True)", "eu")
    try:
        assert ("texto", "Kaixo") in recoger(micro)
    finally:
        micro.detener()


@pytest.mark.parametrize("idioma", ["auto", "es", "eu", "en"])
def test_captura_transcribe_en_idioma_elegido_y_cierra_antes_de_enviar(monkeypatch, idioma):
    eventos = []
    monkeypatch.setattr(sys, "argv", ["escucha", "--capturar", idioma])
    monkeypatch.setattr(escucha, "capturar_frase", lambda: b"audio")

    def transcribir(audio, lenguaje):
        assert audio == b"audio"
        assert lenguaje == (None if idioma == "auto" else idioma)
        assert eventos == [("estado", "Transcribiendo")]
        return "frase reconocida"

    monkeypatch.setattr(escucha, "transcribir", transcribir)
    monkeypatch.setattr(escucha, "_emitir", lambda *e: eventos.append(e))
    escucha.main()
    assert eventos[-1] == ("texto", "frase reconocida")


def test_transcripcion_vacia_no_envia_mensaje(monkeypatch):
    eventos = []
    monkeypatch.setattr(sys, "argv", ["escucha", "--capturar", "auto"])
    monkeypatch.setattr(escucha, "capturar_frase", lambda: b"audio")
    monkeypatch.setattr(escucha, "transcribir", lambda *a: "")
    monkeypatch.setattr(escucha, "_emitir", lambda *e: eventos.append(e))
    with pytest.raises(RuntimeError, match="No he entendido"):
        escucha.main()
    assert eventos == [("estado", "Transcribiendo")]


def test_preparacion_fija_revision_y_solo_descarga_archivos_necesarios(monkeypatch):
    llamadas = []
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        snapshot_download=lambda *a, **kw: llamadas.append((a, kw))))
    monkeypatch.setattr(sys, "argv", ["escucha", "--preparar"])
    escucha.main()
    assert llamadas == [((escucha.REPOSITORIO,), dict(
        revision=escucha.REVISION, allow_patterns=list(escucha.ARCHIVOS),
        local_dir=str(escucha.DIRECTORIO_MODELO)))]
