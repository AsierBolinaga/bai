"""Comprobacion y precarga locales en segundo plano, cancelables y acotadas."""
import queue
import threading

from core.cancelacion import GeneracionCancelada, cancelacion_turno
from core.generacion_worker import ProcesoMotor
from core.motors.base import MotorError

PLAZO_CARGA_SEGUNDOS = 60


class CargaLocal:
    def __init__(self, config, modulo):
        self.nombre = config["offline"]["motor"]
        self.modulo = modulo
        self.worker = ProcesoMotor()
        self._config = config
        self._plazo = PLAZO_CARGA_SEGUNDOS
        self._cancelacion = threading.Event()
        self._lock = threading.Lock()
        self._avisos = queue.Queue()
        self._estado = "preparando"
        self._detalle = f"Preparando {self.nombre} en segundo plano (máximo {self._plazo} s)."
        self._hilo = threading.Thread(target=self._preparar, name="bai-carga-local", daemon=True)

    def iniciar(self):
        self._hilo.start()

    def estado(self):
        with self._lock:
            return {"estado": self._estado, "detalle": self._detalle}

    def _preparar(self):
        opciones = self._config["offline"]["motores"][self.nombre]
        try:
            if self.modulo is None:
                raise MotorError(f"Motor '{self.nombre}' no registrado.")
            with cancelacion_turno(self._cancelacion):
                self.worker.ejecutar(
                    self.modulo, opciones, offline=True, arranque=self._config,
                    tiempo_maximo=self._plazo, avisar=self._avisos.put)
        except GeneracionCancelada:
            self._finalizar("error", "Preparación local cancelada.")
        except Exception as error:
            self._finalizar("error", f"No se pudo preparar el modelo local: {error}")
        else:
            with self._lock:
                if not self._cancelacion.is_set():
                    self._estado = "listo"
                    self._detalle = (f"Motor local {self.nombre} preparado." if opciones.get("descargar_al_arrancar")
                                     else f"Motor local {self.nombre} disponible; carga bajo demanda.")
                    self._avisos.put(self._detalle)
                    return
            # La cancelacion pudo llegar justo despues de recibir la respuesta.
            try:
                self.worker.cerrar()
            except Exception as error:
                self._finalizar("error", f"Error cerrando la preparación cancelada: {error}")
            else:
                self._finalizar("error", "Preparación local cancelada.")

    def _finalizar(self, estado, detalle):
        detalle = (f"Modo degradado: {self.nombre} no disponible. {detalle} "
                   "Puedes usar ayuda, memoria y estado, o autorizar Online. "
                   "Reinicia B.A.I. para reintentar el motor local.")
        with self._lock:
            self._estado, self._detalle = estado, detalle
        self._avisos.put(detalle)

    def cancelar(self):
        with self._lock:
            if self._estado == "preparando":
                self._cancelacion.set()
                self._estado = "cancelando"
                self._detalle = "Cancelando la preparación local…"

    def recoger_avisos(self):
        avisos = []
        while True:
            try:
                avisos.append(self._avisos.get_nowait())
            except queue.Empty:
                return avisos

    def cerrar(self):
        self.cancelar()
        self.worker.cerrar()
        self._hilo.join(timeout=2)
        if self._hilo.is_alive():
            raise RuntimeError("La preparación local no confirmó su cierre.")
