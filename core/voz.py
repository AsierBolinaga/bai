"""Voz neuronal Piper local, experimental y cancelable, sin descargas automáticas."""
import importlib.util
from functools import lru_cache
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
from config.audio_config import cargar_audio_config
from core.audio_worker import ProcesoAudio

DIRECTORIO_VOCES = Path(__file__).resolve().parents[1] / "models/voz"
SILENCIO_INICIAL_SEGUNDOS = 3
VOCES = {
    "es": "es_ES-davefx-medium.onnx",
    "eu": "eu_ES-antton-medium/eu_ES-antton-medium.onnx",
    "en": "en_GB-northern_english_male-medium/en_GB-northern_english_male-medium.onnx",
}
NOMBRES_VOCES = {"es": "castellano", "eu": "euskera", "en": "inglés"}
PRIORIDAD_ALTERNATIVAS = ("es", "eu", "en")


def modelos_instalados(directorio):
    return {
        idioma: Path(directorio) / ruta
        for idioma, ruta in VOCES.items()
        if (Path(directorio) / ruta).is_file()
        and Path(str(Path(directorio) / ruta) + ".json").is_file()
    }


@lru_cache(maxsize=1)
def _detector_idioma():
    from langid.langid import LanguageIdentifier, model

    return LanguageIdentifier.from_modelstring(model, norm_probs=False)


def detectar_idioma(texto):

    palabras = re.findall(r"[^\W\d_]+", texto.casefold())
    breve = " ".join(palabras)
    if len(palabras) <= 3:
        if breve in ("kaixo", "kaixo boli", "egun on", "gabon", "agur", "eskerrik asko",
                     "bai", "ez", "ondo", "zer moduz"):
            return "eu"
        if breve in ("hola", "hola boli", "buenos dias", "buenos días", "buenas tardes",
                     "buenas noches", "gracias", "adios", "adiós", "si", "sí", "vale"):
            return "es"
    if not palabras:
        return "en"
    # La detección se ejecuta en el proceso de voz, nunca en el hilo de Tk.
    detector = _detector_idioma()
    idioma, _ = detector.classify(texto)
    return idioma


def modelo_para_texto(texto, directorio, *, avisar=None):
    idioma = detectar_idioma(texto)
    preferida = idioma if idioma in VOCES else "en"
    instalados = modelos_instalados(directorio)
    if preferida in instalados:
        return instalados[preferida]
    for alternativa in PRIORIDAD_ALTERNATIVAS:
        if alternativa in instalados:
            aviso = (f"Falta la voz de {NOMBRES_VOCES[preferida]} para el idioma detectado "
                     f"'{idioma}'. Uso la voz de {NOMBRES_VOCES[alternativa]} como alternativa, "
                     "sin traducir el texto; la pronunciación puede no ser adecuada.")
            if avisar is None:
                print(aviso, file=sys.stderr)
            else:
                avisar(aviso)
            return instalados[alternativa]
    raise RuntimeError(
        f"No hay ninguna voz Piper completa en {directorio}. "
        "Instala al menos una voz (.onnx y .onnx.json).")


class VozLocal:
    def __init__(self):
        self._modelo = (DIRECTORIO_VOCES / VOCES["es"]).resolve()
        self._worker = ProcesoAudio("voz")
        self._hablando = False
        self._opciones = None
        self._avisos = []

    @property
    def modelo(self):
        return self._modelo

    @property
    def disponible(self):
        return self.motivo_no_disponible is None

    @property
    def motivo_no_disponible(self):
        if importlib.util.find_spec("piper") is None:
            return "Instala Piper con 'venv/bin/python -m pip install -r requirements-voz.txt'."
        if importlib.util.find_spec("langid") is None:
            return "Instala el detector local con 'venv/bin/python -m pip install -r requirements-voz.txt'."
        if not modelos_instalados(DIRECTORIO_VOCES):
            return (f"No hay ninguna voz Piper completa en {DIRECTORIO_VOCES}. "
                    "Instala al menos una voz (.onnx y .onnx.json).")
        if shutil.which("aplay") is None:
            return "Falta el reproductor local aplay (paquete alsa-utils en Linux)."
        return None

    def hablar(self, texto):
        self.activar()
        self._worker.enviar("hablar", texto)
        self._hablando = True

    def activar(self):
        if not self.disponible:
            raise RuntimeError(self.motivo_no_disponible)
        if self._opciones is None:
            self._opciones = cargar_audio_config()
        self._worker.iniciar(self._opciones)

    def comprobar(self):
        error = None
        for tipo, texto in self._worker.comprobar():
            if tipo in ("fin", "error"):
                self._hablando = False
            if tipo == "error":
                error = texto
            elif tipo == "aviso":
                self._avisos.append(texto)
        return self._hablando, error

    def recoger_avisos(self):
        avisos, self._avisos = self._avisos, []
        return avisos

    def pausar(self):
        self._worker.cancelar()
        self._hablando = False
        self._avisos = []

    def detener(self):
        self._worker.cerrar()
        self._hablando = False
        self._opciones = None
        self._avisos = []


def _reproducir(texto, modelo, *, motor=None, trabajo=None, silencio=SILENCIO_INICIAL_SEGUNDOS):
    from piper import PiperVoice, SynthesisConfig

    if motor is None:
        motor = PiperVoice.load(modelo, use_cuda=False)
    reproductor = None
    try:
        for audio in motor.synthesize(texto, syn_config=SynthesisConfig(length_scale=1.05)):
            if trabajo is not None:
                trabajo.comprobar()
            if reproductor is None:
                def crear():
                    return subprocess.Popen(
                        ["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                         "-r", str(audio.sample_rate), "-c", str(audio.sample_channels)],
                        stdin=subprocess.PIPE)

                def parar(proceso):
                    if proceso.poll() is None:
                        proceso.terminate()
                        try:
                            proceso.wait(timeout=0.2)
                        except subprocess.TimeoutExpired:
                            proceso.kill()
                            proceso.wait(timeout=0.2)

                reproductor = (crear() if trabajo is None
                               else trabajo.crear_recurso(crear, parar))
                # La salida de audio puede tardar en activarse y perder las primeras palabras.
                muestras = round(audio.sample_rate * silencio)
                reproductor.stdin.write(b"\0" * (muestras * audio.sample_channels * 2))
            reproductor.stdin.write(audio.audio_int16_bytes)
            reproductor.stdin.flush()
        if reproductor is not None:
            reproductor.stdin.close()
            if reproductor.wait() != 0:
                raise RuntimeError("El reproductor de audio local ha fallado.")
    finally:
        try:
            if reproductor is not None:
                parar(reproductor)
        finally:
            if trabajo is not None:
                trabajo.liberar()


def _cancelar(_senal, _marco):
    raise SystemExit(0)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--reproducir":
        raise SystemExit("Uso interno: python -m core.voz --reproducir DIRECTORIO_VOCES")
    signal.signal(signal.SIGTERM, _cancelar)
    try:
        texto = sys.stdin.read()
        _reproducir(texto, str(modelo_para_texto(texto, sys.argv[2])))
    except (OSError, RuntimeError, ValueError, ImportError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
