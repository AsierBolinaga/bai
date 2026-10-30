"""Captura y transcripción locales en un proceso cancelable, sin guardar audio."""
import importlib.util
import json
import math
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

DIRECTORIO_MODELO = Path(__file__).resolve().parents[1] / "models/escucha/whisper-small"
REPOSITORIO = "Systran/faster-whisper-small"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"
ARCHIVOS = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
FRECUENCIA = 16000
MUESTRAS_BLOQUE = 480
SILENCIO_SEGUNDOS = 5
MAXIMO_SEGUNDOS = 90


class DetectorFrase:
    """Delimita frases con VAD: cinco segundos completos desde la última voz."""

    def __init__(self):
        self.bloques = []
        self.previos = []
        self.iniciada = False
        self.silencio = 0
        self.voz = 0
        self.limite_silencio = math.ceil(SILENCIO_SEGUNDOS * FRECUENCIA / MUESTRAS_BLOQUE)
        self.limite_total = math.ceil(MAXIMO_SEGUNDOS * FRECUENCIA / MUESTRAS_BLOQUE)

    def agregar(self, bloque, es_voz):
        if not self.iniciada:
            self.previos.append(bloque)
            self.previos = self.previos[-10:]
            if not es_voz:
                return None
            self.iniciada = True
            self.bloques = self.previos[:-1]
        self.bloques.append(bloque)
        self.silencio = 0 if es_voz else self.silencio + 1
        self.voz += int(es_voz)
        if self.silencio >= self.limite_silencio:
            if self.voz < 10:
                self.__init__()
                return None
            return b"".join(self.bloques[:-self.silencio])
        if len(self.bloques) >= self.limite_total:
            raise RuntimeError("La frase supera 90 segundos. Desactiva y activa Escucha para reintentar con frases más cortas.")
        return None


class EscuchaLocal:
    def __init__(self):
        self._proceso = None
        self._errores = None
        self._hilo = None
        self._eventos = queue.Queue()

    @property
    def motivo_no_disponible(self):
        for modulo in ("faster_whisper", "sounddevice", "webrtcvad"):
            if importlib.util.find_spec(modulo) is None:
                return "Instala la escucha con 'venv/bin/python -m pip install -r requirements-escucha.txt'."
        if not all((DIRECTORIO_MODELO / nombre).is_file() for nombre in ARCHIVOS):
            return "Prepara el modelo con 'venv/bin/python -m core.escucha --preparar' antes de iniciar B.A.I."
        return None

    def iniciar(self, idioma=None):
        self.detener()
        if idioma not in (None, "es", "eu", "en"):
            raise ValueError(f"Idioma de escucha no admitido: {idioma}")
        motivo = self.motivo_no_disponible
        if motivo:
            raise RuntimeError(motivo)
        errores = tempfile.TemporaryFile()
        try:
            proceso = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--capturar", idioma or "auto"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errores,
                text=True, encoding="utf-8")
        except OSError:
            errores.close()
            raise
        self._proceso = proceso
        self._errores = errores
        eventos = self._eventos

        def recibir():
            try:
                for linea in proceso.stdout:
                    try:
                        evento = json.loads(linea)
                        if (not isinstance(evento, list) or len(evento) != 2
                                or not all(isinstance(valor, str) for valor in evento)
                                or evento[0] not in ("estado", "texto")
                                or (evento[0] == "texto" and not evento[1].strip())):
                            raise ValueError("evento de micrófono no válido")
                        eventos.put(tuple(evento))
                    except (ValueError, TypeError) as error:
                        eventos.put(("error", f"Respuesta del proceso de escucha no válida: {error}"))
                codigo = proceso.wait()
                if codigo:
                    errores.seek(0)
                    detalle = errores.read().decode("utf-8", errors="replace").strip()
                    eventos.put(("error", detalle or f"El proceso de escucha terminó con código {codigo}."))
            finally:
                eventos.put(("fin", ""))

        self._hilo = threading.Thread(target=recibir, name="bai-microfono", daemon=True)
        self._hilo.start()

    def comprobar(self):
        eventos = []
        while True:
            try:
                eventos.append(self._eventos.get_nowait())
            except queue.Empty:
                break
        return eventos

    def detener(self):
        if self._proceso is not None:
            if self._proceso.poll() is None:
                self._proceso.terminate()
                try:
                    self._proceso.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    self._proceso.kill()
                    self._proceso.wait()
            self._hilo.join()
            self._proceso.stdout.close()
            self._errores.close()
            self._proceso = self._errores = self._hilo = None
        self._eventos = queue.Queue()


def _emitir(tipo, texto):
    print(json.dumps([tipo, texto], ensure_ascii=True), flush=True)


def capturar_frase():
    import sounddevice as sd
    import webrtcvad

    detector = DetectorFrase()
    vad = webrtcvad.Vad(2)
    with sd.RawInputStream(samplerate=FRECUENCIA, channels=1, dtype="int16",
                           blocksize=MUESTRAS_BLOQUE) as microfono:
        _emitir("estado", "Escuchando")
        while True:
            bloque, desbordado = microfono.read(MUESTRAS_BLOQUE)
            if desbordado:
                raise RuntimeError("El micrófono ha perdido audio. Revisa el dispositivo y vuelve a activar Escucha.")
            pcm = bytes(bloque)
            frase = detector.agregar(pcm, vad.is_speech(pcm, FRECUENCIA))
            if frase is not None:
                return frase


def transcribir(audio, idioma=None):
    import numpy as np
    from faster_whisper import WhisperModel

    modelo = WhisperModel(str(DIRECTORIO_MODELO), device="cpu", compute_type="int8",
                          cpu_threads=4, local_files_only=True)
    segmentos, _ = modelo.transcribe(
        np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768,
        task="transcribe", language=idioma, beam_size=5, condition_on_previous_text=False,
        vad_filter=False)
    return " ".join(segmento.text.strip() for segmento in segmentos).strip()


def main():
    if sys.argv[1:] == ["--preparar"]:
        from huggingface_hub import snapshot_download

        snapshot_download(REPOSITORIO, revision=REVISION, allow_patterns=list(ARCHIVOS),
                          local_dir=str(DIRECTORIO_MODELO))
        print(f"Modelo de escucha preparado en {DIRECTORIO_MODELO}")
    elif len(sys.argv) == 3 and sys.argv[1] == "--capturar" and sys.argv[2] in ("auto", "es", "eu", "en"):
        audio = capturar_frase()
        _emitir("estado", "Transcribiendo")
        texto = transcribir(audio, None if sys.argv[2] == "auto" else sys.argv[2])
        if not texto:
            raise RuntimeError("No he entendido la frase. Vuelve a activar Escucha para reintentar.")
        _emitir("texto", texto)
    else:
        raise SystemExit("Uso: python -m core.escucha --preparar")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"No se ha podido usar la escucha local: {error}", file=sys.stderr)
        raise SystemExit(1)
