"""Captura y transcripción locales en un proceso cancelable, sin guardar audio."""
import importlib.util
import json
import math
from contextlib import ExitStack
from pathlib import Path
import sys
from config.audio_config import cargar_audio_config
from core.audio_worker import ProcesoAudio

DIRECTORIO_MODELO = Path(__file__).resolve().parents[1] / "models/escucha/whisper-small"
REPOSITORIO = "Systran/faster-whisper-small"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"
ARCHIVOS = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
FRECUENCIA = 16000
MUESTRAS_BLOQUE = 480
SILENCIO_SEGUNDOS = 5
MAXIMO_SEGUNDOS = 90
BLOQUES_CALIBRACION = math.ceil(FRECUENCIA / MUESTRAS_BLOQUE)


class FiltroRuido:
    """Combina VAD con energía relativa al ruido medido antes de la frase."""

    def __init__(self, energias):
        from statistics import median

        self.umbral = max(200, median(energias) * 4)
        self._consecutivos = 0

    def es_voz(self, energia, vad):
        self._consecutivos = self._consecutivos + 1 if vad and energia >= self.umbral else 0
        # Un golpe aislado no debe reiniciar los cinco segundos de silencio.
        return self._consecutivos >= 5


class DetectorFrase:
    """Delimita frases con VAD: cinco segundos completos desde la última voz."""

    def __init__(self, silencio=SILENCIO_SEGUNDOS):
        self._silencio_segundos = silencio
        self.bloques = []
        self.previos = []
        self.iniciada = False
        self.silencio = 0
        self.voz = 0
        self.limite_silencio = math.ceil(silencio * FRECUENCIA / MUESTRAS_BLOQUE)
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
                self.__init__(self._silencio_segundos)
                return None
            return b"".join(self.bloques[:-self.silencio])
        if len(self.bloques) >= self.limite_total:
            raise RuntimeError("La frase supera 90 segundos. Desactiva y activa Escucha para reintentar con frases más cortas.")
        return None


class EscuchaLocal:
    def __init__(self):
        self._worker = ProcesoAudio("escucha")
        self._opciones = None

    @property
    def motivo_no_disponible(self):
        for modulo in ("faster_whisper", "sounddevice", "webrtcvad"):
            if importlib.util.find_spec(modulo) is None:
                return "Instala la escucha con 'venv/bin/python -m pip install -r requirements-escucha.txt'."
        if not all((DIRECTORIO_MODELO / nombre).is_file() for nombre in ARCHIVOS):
            return "Prepara el modelo con 'venv/bin/python -m core.escucha --preparar' antes de iniciar B.A.I."
        return None

    def iniciar(self, idioma=None):
        if idioma not in (None, "es", "eu", "en"):
            raise ValueError(f"Idioma de escucha no admitido: {idioma}")
        motivo = self.motivo_no_disponible
        if motivo:
            raise RuntimeError(motivo)
        if self._opciones is None:
            self._opciones = cargar_audio_config()
        self._worker.iniciar(self._opciones)
        self._worker.enviar("escuchar", idioma)

    def comprobar(self):
        return self._worker.comprobar()

    def pausar(self):
        self._worker.cancelar()

    def detener(self):
        self._worker.cerrar()
        self._opciones = None


def _emitir(tipo, texto):
    print(json.dumps([tipo, texto], ensure_ascii=True), flush=True)


def capturar_frase(*, trabajo=None, silencio=SILENCIO_SEGUNDOS, emitir=_emitir):
    import numpy as np
    import sounddevice as sd
    import webrtcvad

    detector = DetectorFrase(silencio)
    vad = webrtcvad.Vad(2)
    with sd.RawInputStream(samplerate=FRECUENCIA, channels=1, dtype="int16",
                           blocksize=MUESTRAS_BLOQUE) as microfono, ExitStack() as recursos:
        if trabajo is not None:
            trabajo.recurso(microfono.abort)
            recursos.callback(trabajo.liberar)
        emitir("estado", "Calibrando: guarda silencio 1 s")
        energias = []
        filtro = None
        ultimo_estado = None
        while True:
            if trabajo is not None:
                trabajo.comprobar()
            bloque, desbordado = microfono.read(MUESTRAS_BLOQUE)
            if desbordado:
                raise RuntimeError("El micrófono ha perdido audio. Revisa el dispositivo y vuelve a activar Escucha.")
            pcm = bytes(bloque)
            muestras = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
            energia = float(np.sqrt(np.mean(muestras * muestras)))
            if filtro is None:
                energias.append(energia)
                if len(energias) == BLOQUES_CALIBRACION:
                    filtro = FiltroRuido(energias)
                    emitir("estado", "Escuchando")
                continue
            es_voz = filtro.es_voz(energia, vad.is_speech(pcm, FRECUENCIA))
            frase = detector.agregar(pcm, es_voz)
            if frase is not None:
                return frase
            if not detector.iniciada:
                estado = "Escuchando"
            elif es_voz:
                estado = "Voz detectada"
            else:
                restante = math.ceil((detector.limite_silencio - detector.silencio)
                                      * MUESTRAS_BLOQUE / FRECUENCIA)
                estado = f"Silencio: {restante} s"
            if estado != ultimo_estado:
                emitir("estado", estado)
                ultimo_estado = estado


def cargar_modelo():
    from faster_whisper import WhisperModel

    return WhisperModel(str(DIRECTORIO_MODELO), device="cpu", compute_type="int8",
                        cpu_threads=4, local_files_only=True)


def transcribir(audio, idioma=None, *, modelo=None):
    import numpy as np

    if modelo is None:
        modelo = cargar_modelo()
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
