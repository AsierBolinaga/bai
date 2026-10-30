"""Voz neuronal Piper local, experimental y cancelable, sin descargas automáticas."""
import importlib.util
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

DIRECTORIO_VOCES = Path(__file__).resolve().parents[1] / "models/voz"
SILENCIO_INICIAL_SEGUNDOS = 3
VOCES = {
    "es": "es_ES-davefx-medium.onnx",
    "eu": "eu_ES-antton-medium/eu_ES-antton-medium.onnx",
    "en": "en_GB-northern_english_male-medium/en_GB-northern_english_male-medium.onnx",
}


def detectar_idioma(texto):
    from langid.langid import LanguageIdentifier, model

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
    detector = LanguageIdentifier.from_modelstring(model, norm_probs=False)
    idioma, _ = detector.classify(texto)
    return idioma


def modelo_para_texto(texto, directorio):
    idioma = detectar_idioma(texto)
    modelo = Path(directorio) / VOCES.get(idioma, VOCES["en"])
    if not modelo.is_file() or not Path(str(modelo) + ".json").is_file():
        raise RuntimeError(f"Falta la voz automática para el idioma {idioma}: {modelo} (.onnx y .onnx.json).")
    return modelo


class VozLocal:
    def __init__(self):
        self._modelo = (DIRECTORIO_VOCES / VOCES["es"]).resolve()
        self._proceso = None
        self._errores = None

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
        for ruta in VOCES.values():
            modelo = DIRECTORIO_VOCES / ruta
            if not modelo.is_file() or not Path(str(modelo) + ".json").is_file():
                return f"Falta el modelo Piper o su configuración: {modelo} (.onnx y .onnx.json)."
        if shutil.which("aplay") is None:
            return "Falta el reproductor local aplay (paquete alsa-utils en Linux)."
        return None

    def hablar(self, texto):
        self.detener()
        if not self.disponible:
            raise RuntimeError(self.motivo_no_disponible)
        errores = tempfile.TemporaryFile()
        try:
            # No hay shell ni texto en los argumentos del proceso; stdin no deja copias persistentes.
            with tempfile.TemporaryFile() as entrada:
                entrada.write(texto.encode("utf-8"))
                entrada.seek(0)
                self._proceso = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--reproducir", str(DIRECTORIO_VOCES)],
                    stdin=entrada, stdout=subprocess.DEVNULL, stderr=errores)
        except OSError:
            errores.close()
            raise
        self._errores = errores

    def comprobar(self):
        """Devuelve (reproduciendo, error); libera los recursos al terminar."""
        if self._proceso is None:
            return False, None
        codigo = self._proceso.poll()
        if codigo is None:
            return True, None
        self._errores.seek(0)
        detalle = self._errores.read().decode("utf-8", errors="replace").strip()
        self._liberar()
        if codigo != 0 or detalle:
            return False, f"No se ha podido reproducir la voz: {detalle or f'salida {codigo}'}"
        return False, None

    def detener(self):
        if self._proceso is not None:
            if self._proceso.poll() is None:
                self._proceso.terminate()
                try:
                    self._proceso.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._proceso.kill()
                    self._proceso.wait()
            self._liberar()

    def _liberar(self):
        self._proceso = None
        self._errores.close()
        self._errores = None


def _reproducir(texto, modelo):
    from piper import PiperVoice, SynthesisConfig

    motor = PiperVoice.load(modelo, use_cuda=False)
    reproductor = None
    try:
        for audio in motor.synthesize(texto, syn_config=SynthesisConfig(length_scale=1.05)):
            if reproductor is None:
                reproductor = subprocess.Popen(
                    ["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                     "-r", str(audio.sample_rate), "-c", str(audio.sample_channels)],
                    stdin=subprocess.PIPE)
                # La salida de audio puede tardar en activarse y perder las primeras palabras.
                muestras = round(audio.sample_rate * SILENCIO_INICIAL_SEGUNDOS)
                reproductor.stdin.write(b"\0" * (muestras * audio.sample_channels * 2))
            reproductor.stdin.write(audio.audio_int16_bytes)
            reproductor.stdin.flush()
        if reproductor is not None:
            reproductor.stdin.close()
            if reproductor.wait() != 0:
                raise RuntimeError("El reproductor de audio local ha fallado.")
    finally:
        if reproductor is not None and reproductor.poll() is None:
            reproductor.terminate()
            try:
                reproductor.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                reproductor.kill()
                reproductor.wait()


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
