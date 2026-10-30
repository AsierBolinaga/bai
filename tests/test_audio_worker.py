"""Workers reales de IPC con modelos y dispositivos simulados."""
import subprocess
import sys
import time

import pytest

from config import audio_config
from core.audio_worker import ProcesoAudio
from core.escucha import DetectorFrase
from core.procesos import estado_grupo


def esperar(worker, tipo):
    limite = time.monotonic() + 10
    while time.monotonic() < limite:
        for evento, texto in worker.comprobar():
            if evento == "error":
                pytest.fail(texto)
            if evento == tipo:
                return texto
        time.sleep(0.01)
    pytest.fail(f"No llegó el evento {tipo}")


@pytest.fixture
def worker(monkeypatch):
    original = subprocess.Popen
    creados = []

    def crear(tipo, codigo):
        def popen(argumentos, **kw):
            assert argumentos[1:4] == ["-m", "core.audio_worker", tipo]
            assert not kw.get("shell")
            return original([sys.executable, "-c", codigo], **kw)

        monkeypatch.setattr(subprocess, "Popen", popen)
        proceso = ProcesoAudio(tipo)
        proceso.iniciar({"silencio_escucha": 0.6, "silencio_reproduccion": 0})
        creados.append(proceso)
        return proceso

    yield crear
    for proceso in creados:
        proceso.cerrar()


def test_whisper_se_carga_una_vez_y_sobrevive_pausas_e_idiomas(worker):
    codigo = """
from core import escucha
from core.audio_worker import servir
cargas = []
def cargar():
    cargas.append(1)
    return object()
def transcribir(audio, idioma, *, modelo):
    assert len(cargas) == 1
    return idioma
escucha.cargar_modelo = cargar
escucha.capturar_frase = lambda **kw: b'audio'
escucha.transcribir = transcribir
servir('escucha', {'silencio_escucha': 0.6})
"""
    w = worker("escucha", codigo)
    esperar(w, "listo")
    pid = w.proceso.pid
    for idioma in ("es", "eu", "en", "es"):
        w.enviar("escuchar", idioma)
        assert esperar(w, "texto") == idioma
        w.cancelar()
        assert w.proceso.pid == pid and w.proceso.poll() is None
    w.cerrar()
    assert w.proceso is None


def test_piper_cache_por_voz_y_silencio_configurado(worker):
    codigo = """
import sys
from types import SimpleNamespace
from core import voz
from core.audio_worker import servir
cargas = {}
def cargar(ruta, **kw):
    cargas[ruta] = cargas.get(ruta, 0) + 1
    assert cargas[ruta] == 1
    return ruta
def reproducir(texto, ruta, *, motor, trabajo, silencio):
    assert motor == ruta and silencio == 0
voz.modelo_para_texto = lambda texto, directorio, **kw: texto
voz._reproducir = reproducir
sys.modules['piper'] = SimpleNamespace(PiperVoice=SimpleNamespace(load=cargar))
servir('voz', {'silencio_reproduccion': 0})
"""
    w = worker("voz", codigo)
    esperar(w, "listo")
    pid = w.proceso.pid
    for modelo in ("castellano", "euskera", "castellano", "ingles", "euskera"):
        w.enviar("hablar", modelo)
        esperar(w, "fin")
        w.cancelar()
        assert w.proceso.pid == pid


def test_voz_ausente_usa_alternativa_con_aviso_y_conserva_cache(worker, tmp_path):
    from core.voz import VOCES
    ruta = tmp_path / VOCES["es"]
    ruta.touch()
    ruta.with_suffix(".onnx.json").touch()
    codigo = f"""
import sys
from pathlib import Path
from types import SimpleNamespace
from core import voz
from core.audio_worker import servir
voz.DIRECTORIO_VOCES = Path({str(tmp_path)!r})
voz.detectar_idioma = lambda texto: texto
cargas = []
def cargar(ruta, **kw):
    cargas.append(ruta)
    assert len(cargas) == 1
    return ruta
def reproducir(texto, ruta, *, motor, **kw):
    assert ruta == motor == {str(ruta)!r}
voz._reproducir = reproducir
sys.modules['piper'] = SimpleNamespace(PiperVoice=SimpleNamespace(load=cargar))
servir('voz', {{'silencio_reproduccion': 0}})
"""
    w = worker("voz", codigo)
    esperar(w, "listo")
    pid = w.proceso.pid
    for idioma in ("eu", "en", "es", "fr"):
        eventos = []
        w.enviar("hablar", idioma)
        limite = time.monotonic() + 5
        while time.monotonic() < limite and not any(t == "fin" for t, _ in eventos):
            eventos.extend(w.comprobar())
            time.sleep(0.01)
        assert any(t == "fin" for t, _ in eventos), eventos
        assert not any(t == "error" for t, _ in eventos), eventos
        avisos = [s for t, s in eventos if t == "aviso"]
        if idioma == "es":
            assert avisos == []
        else:
            assert len(avisos) == 1 and "castellano como alternativa" in avisos[0]
        assert w.proceso.pid == pid


def test_cancelar_descarta_resultados_y_permite_otra_orden(worker):
    codigo = """
import time
from core import escucha
from core.audio_worker import servir
escucha.cargar_modelo = lambda: object()
escucha.capturar_frase = lambda **kw: b'audio'
def transcribir(audio, idioma, **kw):
    if idioma == 'es':
        time.sleep(0.3)
    return idioma
escucha.transcribir = transcribir
servir('escucha', {'silencio_escucha': 0.6})
"""
    w = worker("escucha", codigo)
    esperar(w, "listo")
    w.enviar("escuchar", "es")
    esperar(w, "estado")
    w.cancelar()
    w.enviar("escuchar", "eu")
    assert esperar(w, "texto") == "eu"
    time.sleep(0.1)
    assert not any(t == "texto" for t, _ in w.comprobar())


def test_recurso_de_captura_se_aborta_al_pausar(worker):
    codigo = """
import threading
from core import escucha
from core.audio_worker import servir
abortado = threading.Event()
escucha.cargar_modelo = lambda: object()
def capturar(**kw):
    trabajo = kw['trabajo']
    trabajo.recurso(abortado.set)
    kw['emitir']('estado', 'capturando')
    assert abortado.wait(5)
    trabajo.liberar()
    kw['emitir']('estado', 'abortado')
    trabajo.comprobar()
escucha.capturar_frase = capturar
servir('escucha', {'silencio_escucha': 0.6})
"""
    w = worker("escucha", codigo)
    esperar(w, "listo")
    w.enviar("escuchar", "es")
    assert esperar(w, "estado") == "capturando"
    w.cancelar()
    time.sleep(0.1)
    assert w.proceso.poll() is None
    # La orden siguiente confirma que terminó la captura cancelada sin bloquear el worker.
    w.enviar("escuchar", "eu")
    assert esperar(w, "estado") in ("capturando", "abortado")


@pytest.mark.parametrize("demora_registro", [0, 0.15])
def test_pausa_y_cierre_terminan_reproductor_hijo_sin_perder_worker(worker, demora_registro):
    from pathlib import Path

    codigo = """
import json, sys, subprocess, time
from types import SimpleNamespace
from core import voz
from core.audio_worker import servir
original = subprocess.Popen
def crear(args, **kw):
    p = original([sys.executable, '-c',
                  'import sys,time; sys.stdin.buffer.read(); time.sleep(30)'], **kw)
    print(json.dumps([0, 'estado', str(p.pid)]), flush=True)
    time.sleep(DEMORA)
    return p
class Motor:
    def synthesize(self, *a, **kw):
        yield SimpleNamespace(sample_rate=16000, sample_channels=1,
                              audio_int16_bytes=b'\\0\\0'*16000)
sys.modules['piper'] = SimpleNamespace(
    PiperVoice=SimpleNamespace(load=lambda *a, **kw: Motor()),
    SynthesisConfig=lambda **kw: kw)
voz.modelo_para_texto = lambda *a, **kw: 'voz'
voz.subprocess.Popen = crear
servir('voz', {'silencio_reproduccion': 0})
""".replace("DEMORA", repr(demora_registro))
    w = worker("voz", codigo)
    esperar(w, "listo")
    pid_worker = w.proceso.pid
    w.enviar("hablar", "uno")
    hijo = int(esperar(w, "estado"))
    assert Path(f"/proc/{hijo}").exists()
    w.cancelar()
    assert not Path(f"/proc/{hijo}").exists(), estado_grupo(pid_worker)
    assert w.proceso.pid == pid_worker and w.proceso.poll() is None
    w.enviar("hablar", "dos")
    hijo = int(esperar(w, "estado"))
    w.cerrar()
    assert not Path(f"/proc/{hijo}").exists(), estado_grupo(pid_worker)


def test_cierre_audio_mata_grupo_si_worker_no_ejecuta_limpieza(worker):
    from pathlib import Path
    codigo = """
import json, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print(json.dumps([0, 'estado', str(p.pid)]), flush=True)
time.sleep(60)
"""
    w = worker("voz", codigo)
    hijo = int(esperar(w, "estado"))
    proceso = w.proceso
    inicio = time.monotonic()
    w.cerrar()
    assert time.monotonic() - inicio < 2
    assert proceso.poll() is not None
    ruta = Path(f"/proc/{hijo}/stat")
    # Un nieto muerto puede quedar zombi hasta que lo recoja el init del entorno.
    assert not ruta.exists() or ruta.read_text().split()[2] == "Z"


def test_cierre_audio_informa_si_lector_no_confirma_sin_join_infinito(worker):
    from types import SimpleNamespace
    w = worker("voz", "import time; print('[0, \"listo\", \"\"]', flush=True); time.sleep(60)")
    esperar(w, "listo")
    hilo = w._hilo
    esperas = []
    w._hilo = SimpleNamespace(join=lambda timeout: esperas.append(timeout), is_alive=lambda: True)
    try:
        inicio = time.monotonic()
        with pytest.raises(RuntimeError, match="canal de audio"):
            w.cerrar()
        assert time.monotonic() - inicio < 2
        assert esperas and all(0 < espera <= 0.5 for espera in esperas)
    finally:
        w._hilo = hilo


def test_envio_audio_bloqueado_no_impide_cierre_acotado(worker):
    w = worker("voz", "import time; print('[0, \"listo\", \"\"]', flush=True); time.sleep(60)")
    esperar(w, "listo")
    proceso = w.proceso
    inicio = time.monotonic()
    with pytest.raises(RuntimeError, match="canal de audio no confirmó el envío"):
        w.enviar("hablar", "x" * 1_000_000)
    assert time.monotonic() - inicio < 2
    assert proceso.poll() is not None and w.proceso is None


def test_pausa_no_oculta_error_si_no_puede_confirmar_cierre(worker, monkeypatch):
    w = worker("voz", "import time; print('[0, \"listo\", \"\"]', flush=True); time.sleep(60)")
    esperar(w, "listo")

    def fallar():
        raise RuntimeError("grupo sigue activo")

    with monkeypatch.context() as m:
        m.setattr(w, "cerrar", fallar)
        with pytest.raises(RuntimeError, match="grupo sigue activo"):
            w.cancelar()


@pytest.mark.parametrize("valor", [-1, True, "2", float("nan"), float("inf"), 31])
def test_configuracion_invalida_se_informa(tmp_path, monkeypatch, valor):
    import yaml

    ruta = tmp_path / "audio.yaml"
    ruta.write_text(yaml.safe_dump({"silencio_escucha": valor, "silencio_reproduccion": 3}))
    monkeypatch.setattr(audio_config, "RUTA", ruta)
    with pytest.raises(ValueError, match="silencio_escucha"):
        audio_config.cargar_audio_config()


@pytest.mark.parametrize("texto", [
    "silencio_escucha: 5\nsilencio_reproduccion: -1\n",
    "silencio_escucha: 5\nsilencio_reproduccion: 11\n",
    "silencio_escucha: 5\nsilencio_reproduccion: true\n",
    "silencio_escucha: 5\n",
    "silencio_escucha: 5\nsilencio_reproduccion: 0\nextra: 1\n",
    "[]",
])
def test_configuracion_de_salida_incompleta_o_desconocida_falla(tmp_path, monkeypatch, texto):
    ruta = tmp_path / "audio.yaml"
    ruta.write_text(texto)
    monkeypatch.setattr(audio_config, "RUTA", ruta)
    with pytest.raises(ValueError):
        audio_config.cargar_audio_config()

def test_configuracion_valida_y_silencio_cero_de_salida(tmp_path, monkeypatch):
    ruta = tmp_path / "audio.yaml"
    ruta.write_text("silencio_escucha: 0.6\nsilencio_reproduccion: 0\n")
    monkeypatch.setattr(audio_config, "RUTA", ruta)
    assert audio_config.cargar_audio_config() == {"silencio_escucha": 0.6, "silencio_reproduccion": 0}
    detector = DetectorFrase(0.6)
    for _ in range(12):
        detector.agregar(b"v", True)
    for _ in range(19):
        assert detector.agregar(b"s", False) is None
    assert detector.agregar(b"s", False) == b"v" * 12


def test_ruido_corto_conserva_silencio_personalizado():
    detector = DetectorFrase(0.6)
    detector.agregar(b"v", True)
    for _ in range(20):
        assert detector.agregar(b"s", False) is None
    assert detector.limite_silencio == 20
