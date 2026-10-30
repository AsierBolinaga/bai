"""Operaciones de audio serializadas; los resultados se consumen desde Tk."""
import queue
import threading


class OperacionesAudio:
    def __init__(self):
        self.resultados = queue.Queue()
        self._pendientes = queue.Queue()
        self._cerrando = threading.Event()
        self._hilo = None

    def _iniciar(self):
        if self._hilo is None:
            self._hilo = threading.Thread(target=self._ejecutar, name="bai-ui-audio", daemon=True)
            self._hilo.start()

    def enviar(self, operacion, resultado):
        if self._cerrando.is_set():
            raise RuntimeError("La cola de audio se está cerrando.")
        self._pendientes.put((operacion, resultado))
        self._iniciar()

    def cerrar(self, limpiar):
        if not self._cerrando.is_set():
            self._cerrando.set()
            self._pendientes.put((limpiar, None))
            self._iniciar()
        return self._hilo

    def _ejecutar(self):
        while True:
            operacion, resultado = self._pendientes.get()
            if resultado is None:
                operacion()
                return
            if self._cerrando.is_set():
                continue
            try:
                valor = operacion()
            except Exception as error:
                self.resultados.put((resultado, None, error))
            else:
                self.resultados.put((resultado, valor, None))
