"""Lectura local opcional mediante eSpeak NG, aislada en un proceso cancelable."""
import ctypes
import ctypes.util
from pathlib import Path
import subprocess
import sys
import tempfile


class VozLocal:
    def __init__(self):
        self._biblioteca = ctypes.util.find_library("espeak-ng") or ctypes.util.find_library("espeak")
        self._proceso = None
        self._errores = None

    @property
    def disponible(self):
        return self._biblioteca is not None

    def hablar(self, texto):
        self.detener()
        if not self.disponible:
            raise RuntimeError("Voz local no disponible: instala eSpeak NG (paquete espeak-ng en Linux).")
        errores = tempfile.TemporaryFile()
        try:
            # No hay shell ni texto en los argumentos del proceso; stdin no deja copias persistentes.
            with tempfile.TemporaryFile() as entrada:
                entrada.write(texto.encode("utf-8"))
                entrada.seek(0)
                self._proceso = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--reproducir"],
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
                    self._proceso.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self._proceso.kill()
                    self._proceso.wait()
            self._liberar()

    def _liberar(self):
        self._proceso = None
        self._errores.close()
        self._errores = None


def _reproducir(texto):
    biblioteca = ctypes.util.find_library("espeak-ng") or ctypes.util.find_library("espeak")
    if biblioteca is None:
        raise RuntimeError("No se encuentra la biblioteca eSpeak NG.")
    motor = ctypes.CDLL(biblioteca)
    motor.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    motor.espeak_Initialize.restype = ctypes.c_int
    motor.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    motor.espeak_SetVoiceByName.restype = ctypes.c_int
    motor.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    motor.espeak_SetParameter.restype = ctypes.c_int
    motor.espeak_Synth.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
        ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.c_void_p]
    motor.espeak_Synth.restype = ctypes.c_int
    motor.espeak_Synchronize.argtypes = []
    motor.espeak_Synchronize.restype = ctypes.c_int
    motor.espeak_Terminate.argtypes = []
    motor.espeak_Terminate.restype = ctypes.c_int
    if motor.espeak_Initialize(0, 0, None, 0) <= 0:
        raise RuntimeError("No se puede inicializar el audio local.")
    try:
        if motor.espeak_SetVoiceByName(b"es") != 0:
            raise RuntimeError("La voz en español de eSpeak NG no está disponible.")
        # Velocidad pausada, tono grave y rango contenido; no clona ninguna voz.
        for parametro, valor in ((1, 150), (3, 35), (4, 35)):
            if motor.espeak_SetParameter(parametro, valor, 0) != 0:
                raise RuntimeError("No se puede configurar la voz local.")
        datos = ctypes.create_string_buffer(texto.encode("utf-8"))
        if motor.espeak_Synth(datos, len(datos), 0, 1, 0, 1, None, None) != 0:
            raise RuntimeError("No se puede sintetizar el texto.")
        if motor.espeak_Synchronize() != 0:
            raise RuntimeError("No se ha podido completar la reproducción.")
    finally:
        motor.espeak_Terminate()


if __name__ == "__main__":
    if sys.argv[1:] != ["--reproducir"]:
        raise SystemExit("Uso interno: python -m core.voz --reproducir")
    try:
        _reproducir(sys.stdin.read())
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
