"""Motores persistentes en un proceso terminable, sin historial ni memoria propios."""
import contextlib
import importlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading

from core.cancelacion import comprobar_cancelacion
from core.motors.base import MotorError

ESPERA_TERMINAR = 0.3


class ProcesoMotor:
    def __init__(self):
        self._proceso = None
        self._errores = None
        self._carpeta = None
        self._lector = None
        self._eventos = None
        self._lock = threading.Lock()
        self._cerrando = threading.Event()

    def _iniciar(self):
        if self._proceso is not None:
            return
        errores = tempfile.TemporaryFile()
        carpeta = tempfile.TemporaryDirectory(prefix="bai-motor-")
        try:
            proceso = subprocess.Popen(
                [sys.executable, "-m", "core.generacion_worker"],
                cwd=str(Path(__file__).resolve().parents[1]),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errores,
                text=True, encoding="utf-8", bufsize=1, start_new_session=True,
                env=dict(os.environ, TMPDIR=carpeta.name))
        except OSError:
            errores.close()
            carpeta.cleanup()
            raise
        self._proceso, self._errores = proceso, errores
        self._carpeta = carpeta
        eventos = self._eventos = queue.Queue()

        def leer():
            try:
                for linea in proceso.stdout:
                    eventos.put(json.loads(linea))
                eventos.put({"error": f"El proceso del motor terminó sin respuesta (código {proceso.poll()})."})
            except (OSError, ValueError) as error:
                eventos.put({"error": f"IPC del motor inválido: {error}"})

        self._lector = threading.Thread(target=leer, name="bai-motor-ipc", daemon=True)
        self._lector.start()

    def ejecutar(self, modulo, config, mensajes=None, *, offline, avisar=print):
        with self._lock:
            comprobar_cancelacion()
            if self._cerrando.is_set():
                raise MotorError("El proceso del motor se está cerrando.")
            self._iniciar()
            proceso, eventos = self._proceso, self._eventos
            peticion = json.dumps({
                "modulo": modulo, "config": config, "mensajes": mensajes, "offline": offline,
            }, ensure_ascii=True) + "\n"

            def escribir():
                try:
                    proceso.stdin.write(peticion)
                    proceso.stdin.flush()
                except (OSError, ValueError) as error:
                    eventos.put({"error": f"No se puede enviar la petición al motor: {error}"})

            escritor = threading.Thread(target=escribir, name="bai-motor-envio", daemon=True)
            escritor.start()
            try:
                while True:
                    comprobar_cancelacion()
                    if self._cerrando.is_set():
                        raise MotorError("Generación interrumpida por el cierre del motor.")
                    try:
                        respuesta = eventos.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    comprobar_cancelacion()
                    if not isinstance(respuesta, dict):
                        raise MotorError("Respuesta IPC del motor inválida.")
                    if "error" in respuesta:
                        raise MotorError(respuesta["error"])
                    if ("texto" not in respuesta or not isinstance(respuesta.get("avisos"), list)
                            or any(not isinstance(a, str) for a in respuesta["avisos"])):
                        raise MotorError("Respuesta IPC del motor incompleta.")
                    for aviso in respuesta["avisos"]:
                        avisar(aviso)
                    return respuesta["texto"]
            except BaseException:
                # Incluye Ctrl+C: nunca dejar el motor o la CLI Copilot generando.
                self._terminar()
                raise
            finally:
                escritor.join(timeout=ESPERA_TERMINAR)

    def _terminar(self):
        proceso = self._proceso
        if proceso is None:
            return
        # La CLI Copilot y otros hijos pertenecen a este grupo, no al de B.A.I.
        for senal in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proceso.pid, senal)
            except ProcessLookupError:
                pass
            try:
                proceso.wait(timeout=ESPERA_TERMINAR)
            except subprocess.TimeoutExpired:
                if senal == signal.SIGKILL:
                    raise MotorError("El sistema no confirmó el cierre del proceso del motor.")
        self._lector.join(timeout=ESPERA_TERMINAR)
        if self._lector.is_alive():
            raise MotorError("El canal del motor no terminó tras cerrar el proceso.")
        proceso.stdin.close()
        proceso.stdout.close()
        self._errores.close()
        self._carpeta.cleanup()
        self._carpeta = None
        self._proceso = self._errores = self._lector = self._eventos = None

    def cerrar(self):
        self._cerrando.set()
        if not self._lock.acquire(timeout=2):
            raise MotorError("El motor no liberó el turno durante el cierre.")
        try:
            self._terminar()
        finally:
            self._lock.release()


def servir(entrada=None, salida=None):
    from core.contexto import avisos_contexto
    from core.network_guard import GuardiaRed

    entrada = sys.stdin if entrada is None else entrada
    salida = sys.stdout if salida is None else salida
    # Los mensajes de los adaptadores no deben mezclarse con el protocolo JSON.
    with contextlib.redirect_stdout(sys.stderr):
        for linea in entrada:
            try:
                peticion = json.loads(linea)
                avisos = []
                guardia = GuardiaRed() if peticion["offline"] else contextlib.nullcontext()
                with guardia, avisos_contexto(avisos.append):
                    motor = importlib.import_module(peticion["modulo"])
                    if peticion["mensajes"] is None:
                        motor.cargar_modelo(peticion["config"])
                        texto = None
                    else:
                        texto = motor.responder(peticion["mensajes"], peticion["config"])
                if peticion["offline"] and guardia.intentos:
                    raise MotorError("El motor intentó acceder a la red durante la generación.")
                respuesta = {"texto": texto, "avisos": avisos}
            except Exception as error:
                respuesta = {"error": f"{type(error).__name__}: {error}"}
            salida.write(json.dumps(respuesta, ensure_ascii=True) + "\n")
            salida.flush()


if __name__ == "__main__":
    # Tambien aisla los prints de librerias nativas y de procesos hijos.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8") as protocolo:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        servir(salida=protocolo)
