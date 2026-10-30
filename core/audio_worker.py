"""Worker persistente de audio: IPC por JSON, sin grabaciones en disco."""
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from core.procesos import esperar_grupo

ESPERA_CIERRE_AUDIO = 0.5


class ProcesoAudio:
    def __init__(self, tipo):
        self.tipo = tipo
        self.proceso = None
        self._errores = None
        self._hilo = None
        self._escritor = None
        self._eventos = queue.Queue()
        self._id = 0
        self._pausa = threading.Event()

    def iniciar(self, opciones):
        if self.proceso is not None:
            return
        errores = tempfile.TemporaryFile()
        try:
            proceso = subprocess.Popen(
                [sys.executable, "-m", "core.audio_worker", self.tipo, json.dumps(opciones)],
                cwd=str(Path(__file__).resolve().parents[1]),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errores,
                text=True, encoding="utf-8", bufsize=1, start_new_session=True)
        except OSError:
            errores.close()
            raise
        self.proceso, self._errores = proceso, errores
        eventos = self._eventos

        def recibir():
            try:
                for linea in proceso.stdout:
                    try:
                        evento = json.loads(linea)
                        if (not isinstance(evento, list) or len(evento) != 3
                                or type(evento[0]) is not int
                                or evento[1] not in ("estado", "texto", "fin", "error", "aviso", "listo", "pausado")
                                or not isinstance(evento[2], str)
                                or (evento[1] == "texto" and not evento[2].strip())):
                            raise ValueError("evento de audio no válido")
                        if evento[1] == "pausado":
                            if evento[0] == self._id:
                                self._pausa.set()
                        else:
                            eventos.put(tuple(evento))
                    except (ValueError, TypeError) as error:
                        eventos.put((0, "error", f"Protocolo de audio inválido: {error}"))
                codigo = proceso.wait(timeout=ESPERA_CIERRE_AUDIO)
                errores.seek(0)
                detalle = errores.read().decode("utf-8", errors="replace").strip()
                eventos.put((0, "error", f"El worker de audio terminó ({codigo}): {detalle}"))
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                eventos.put((0, "error", f"No se puede leer el worker de audio: {error}"))

        self._hilo = threading.Thread(target=recibir, name=f"bai-audio-{self.tipo}", daemon=True)
        self._hilo.start()

    def enviar(self, orden, contenido=None):
        if self.proceso is None or self.proceso.poll() is not None:
            raise RuntimeError("El worker de audio no está disponible; desactiva y activa la función.")
        self._id += 1
        proceso = self.proceso
        mensaje = json.dumps([self._id, orden, contenido], ensure_ascii=True) + "\n"
        resultado = queue.Queue()

        def escribir():
            try:
                proceso.stdin.write(mensaje)
                proceso.stdin.flush()
            except (OSError, ValueError) as error:
                resultado.put(error)
            else:
                resultado.put(None)

        escritor = self._escritor = threading.Thread(target=escribir, name="bai-audio-envio", daemon=True)
        escritor.start()
        try:
            error = resultado.get(timeout=ESPERA_CIERRE_AUDIO)
        except queue.Empty:
            self.cerrar()
            raise RuntimeError("El canal de audio no confirmó el envío; se ha cerrado el worker.")
        if error is not None:
            self.cerrar()
            raise RuntimeError(f"No se pudo enviar la orden de audio: {error}") from error

    def cancelar(self):
        if self.proceso is not None and self.proceso.poll() is None:
            try:
                self._pausa.clear()
                self.enviar("cancelar")
                if not self._pausa.wait(timeout=0.5):
                    self.cerrar()
                    self._eventos.put((0, "error", "El worker no confirmó la pausa; se ha cerrado por seguridad."))
            except (OSError, RuntimeError) as error:
                self._eventos.put((0, "error", f"No se ha podido pausar audio: {error}"))
                raise RuntimeError(f"No se ha podido pausar audio: {error}") from error
        else:
            self._id += 1

    def comprobar(self):
        resultado = []
        while True:
            try:
                identificador, tipo, texto = self._eventos.get_nowait()
            except queue.Empty:
                return resultado
            if identificador in (0, self._id):
                resultado.append((tipo, texto))

    def cerrar(self):
        if self.proceso is not None:
            if self.proceso.poll() is None:
                self.proceso.terminate()
                try:
                    self.proceso.wait(timeout=ESPERA_CIERRE_AUDIO)
                except subprocess.TimeoutExpired:
                    pass
            # Tambien detiene el reproductor si el worker no alcanzo su callback.
            try:
                os.killpg(self.proceso.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                self.proceso.wait(timeout=ESPERA_CIERRE_AUDIO)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("El proceso de audio no confirmó su cierre.") from error
            esperar_grupo(self.proceso.pid, ESPERA_CIERRE_AUDIO)
            self._hilo.join(timeout=ESPERA_CIERRE_AUDIO)
            if self._hilo.is_alive():
                raise RuntimeError("El canal de audio no terminó tras cerrar el proceso.")
            if self._escritor is not None:
                self._escritor.join(timeout=ESPERA_CIERRE_AUDIO)
                if self._escritor.is_alive():
                    raise RuntimeError("El envío de audio no terminó tras cerrar el proceso.")
            self.proceso.stdin.close()
            self.proceso.stdout.close()
            self._errores.close()
            self.proceso = self._errores = self._hilo = None
            self._escritor = None
        self._eventos = queue.Queue()


class Cancelado(Exception):
    pass


class Trabajo:
    def __init__(self):
        self.cancelado = threading.Event()
        self._lock = threading.Lock()
        self._recurso = None

    def comprobar(self):
        if self.cancelado.is_set():
            raise Cancelado()

    def recurso(self, parar):
        with self._lock:
            self.comprobar()
            self._recurso = parar

    def crear_recurso(self, crear, parar):
        # La cancelacion no puede confirmar una pausa entre crear y registrar.
        with self._lock:
            self.comprobar()
            recurso = crear()
            self._recurso = lambda: parar(recurso)
            return recurso

    def liberar(self):
        with self._lock:
            self._recurso = None

    def cancelar(self):
        self.cancelado.set()
        with self._lock:
            if self._recurso is not None:
                self._recurso()


def servir(tipo, opciones, entrada=None):
    from core import escucha, voz
    import signal

    entrada = sys.stdin if entrada is None else entrada
    pendientes = queue.Queue()
    modelos = {}
    actual = None
    salida_lock = threading.Lock()

    def emitir(identificador, evento, texto=""):
        with salida_lock:
            print(json.dumps([identificador, evento, texto], ensure_ascii=True), flush=True)

    def terminar(_senal, _marco):
        if actual is not None:
            actual.cancelar()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminar)

    def procesar():
        try:
            if tipo == "escucha":
                modelos["whisper"] = escucha.cargar_modelo()
            emitir(0, "listo")
        except Exception as error:
            emitir(0, "error", f"No se pudo preparar audio: {error}")
            return
        while True:
            identificador, orden, contenido, trabajo = pendientes.get()
            try:
                trabajo.comprobar()
                if orden == "escuchar":
                    audio = escucha.capturar_frase(
                        trabajo=trabajo, silencio=opciones["silencio_escucha"],
                        emitir=lambda t, s: emitir(identificador, t, s))
                    trabajo.comprobar()
                    emitir(identificador, "estado", "Transcribiendo")
                    texto = escucha.transcribir(audio, contenido, modelo=modelos["whisper"])
                    trabajo.comprobar()
                    if not texto:
                        raise RuntimeError("No he entendido la frase. Vuelve a activar Escucha.")
                    emitir(identificador, "texto", texto)
                elif orden == "hablar":
                    ruta = str(voz.modelo_para_texto(
                        contenido, voz.DIRECTORIO_VOCES,
                        avisar=lambda s: emitir(identificador, "aviso", s)))
                    if ruta not in modelos:
                        from piper import PiperVoice
                        modelos[ruta] = PiperVoice.load(ruta, use_cuda=False)
                    trabajo.comprobar()
                    voz._reproducir(
                        contenido, ruta, motor=modelos[ruta], trabajo=trabajo,
                        silencio=opciones["silencio_reproduccion"])
                    trabajo.comprobar()
                    emitir(identificador, "fin")
                else:
                    raise ValueError(f"Orden de audio desconocida: {orden}")
            except Cancelado:
                pass
            except Exception as error:
                if not trabajo.cancelado.is_set():
                    emitir(identificador, "error", f"Error de audio local: {error}")

    hilo = threading.Thread(target=procesar, name="bai-audio-modelos", daemon=True)
    hilo.start()
    try:
        for linea in entrada:
            identificador, orden, contenido = json.loads(linea)
            if actual is not None:
                actual.cancelar()
            actual = Trabajo()
            if orden != "cancelar":
                pendientes.put((identificador, orden, contenido, actual))
            else:
                emitir(identificador, "pausado")
    finally:
        if actual is not None:
            actual.cancelar()
        hilo.join(timeout=0.5)


if __name__ == "__main__":
    servir(sys.argv[1], json.loads(sys.argv[2]))
