"""
Controlador de la interfaz gráfica de B.A.I (sin dependencia de Tk).

Reúne lo que la ventana necesita —enviar un mensaje, cambiar de modo, estado,
limpiar y guardar el historial— usando las mismas funciones que la consola
(`ask`, `save_chat_history`), de modo que la memoria, el modo offline y el
aislamiento se comportan igual en ambas interfaces. Al no importar Tk se puede
probar sin pantalla.
"""
import threading
from collections import namedtuple
from copy import deepcopy

from core.cancelacion import GeneracionCancelada, cancelacion_turno, comprobar_cancelacion

Turno = namedtuple("Turno", "texto avisos guardado limpiado")

COMANDOS_LIMPIAR = ("reset", "limpiar")
MENSAJE_LIMPIADO = "Memoria de sesión limpiada."
MENSAJE_OCUPADO = "B.A.I sigue respondiendo al mensaje anterior."
MENSAJE_CANCELADO = "Generación cancelada. El turno no se ha añadido al historial."


class ControladorChat:
    def __init__(self, historial=None, preguntar=None, guardar=None, describir=None,
                 estado=None):
        """Todas las dependencias son inyectables; por defecto se usan las reales."""
        if historial is None or preguntar is None or guardar is None or describir is None or estado is None:
            from core import ai_engine
            from core.memory_engine import load_full_history, save_chat_history
            historial = load_full_history() if historial is None else historial
            preguntar = preguntar or ai_engine.ask
            guardar = guardar or save_chat_history
            describir = describir or ai_engine.describir_estado
            estado = estado or _estado_barra
        self.historial = historial
        self._preguntar = preguntar
        self._guardar = guardar
        self._describir = describir
        self._estado = estado
        self._cerrojo = threading.Lock()
        self._estado_lock = threading.Lock()
        self._persistencia = threading.Lock()
        self._cancelacion = None

    # ----------------------------------------------------------------- consulta
    def estado_barra(self):
        """Texto breve para la barra de estado: modo y motor activo."""
        return self._estado()

    def estado_completo(self):
        return self._describir()

    @property
    def ocupado(self):
        return self._cerrojo.locked()

    # ------------------------------------------------------------------ envío
    def enviar(self, texto):
        """Procesa un mensaje y devuelve un Turno; None si el texto está vacío.
        Un único mensaje a la vez: si hay otro en curso no se encola ni se pierde el historial."""
        texto = (texto or "").strip()
        if not texto:
            return None
        if not self._cerrojo.acquire(blocking=False):
            return Turno(MENSAJE_OCUPADO, [], True, False)
        with self._estado_lock:
            self._cancelacion = threading.Event()
        return self._ejecutar(texto)

    def _ejecutar(self, texto):
        try:
            with cancelacion_turno(self._cancelacion):
                return self._procesar(texto)
        except GeneracionCancelada:
            return Turno(MENSAJE_CANCELADO, [], True, False)
        finally:
            self._cerrojo.release()

    def cancelar(self):
        with self._estado_lock:
            if self._cancelacion is not None:
                self._cancelacion.set()

    def enviar_en_hilo(self, texto, al_terminar):
        """Ejecuta `enviar` en un hilo y llama a `al_terminar(turno)` desde ese hilo.
        La ventana no debe tocar Tk desde la llamada: debe pasar el turno a su hilo principal."""
        texto = (texto or "").strip()
        if not texto:
            return None
        if not self._cerrojo.acquire(blocking=False):
            al_terminar(Turno(MENSAJE_OCUPADO, [], True, False))
            return None
        with self._estado_lock:
            self._cancelacion = threading.Event()

        def trabajo():
            try:
                turno = self._ejecutar(texto)
            except Exception as e:  # el hilo nunca debe morir en silencio
                turno = Turno(f"Error interno: {e}", [], True, False)
            if turno is not None:
                al_terminar(turno)
        hilo = threading.Thread(target=trabajo, name="bai-ui-turno", daemon=True)
        hilo.start()
        return hilo

    def _procesar(self, texto):
        with self._estado_lock:
            historial = deepcopy(self.historial)
        if texto.lower() in COMANDOS_LIMPIAR:
            with self._estado_lock:
                comprobar_cancelacion()
                self.historial.clear()
            guardado = self._guardar_copia([])
            return Turno(MENSAJE_LIMPIADO, [], guardado, True)

        avisos = []
        antes = _instalar_avisador(avisos.append)
        try:
            respuesta = self._preguntar(texto, historial)
        finally:
            _instalar_avisador(antes)
        with self._estado_lock:
            comprobar_cancelacion()
            self.historial[:] = historial
        guardado = self._guardar_copia(historial)
        return Turno(respuesta, avisos, guardado, False)

    # ----------------------------------------------------------------- cierre
    def _guardar_copia(self, historial):
        if not self._persistencia.acquire(timeout=1):
            raise TimeoutError("El guardado anterior no ha terminado.")
        try:
            return bool(self._guardar(historial))
        finally:
            self._persistencia.release()

    def cerrar(self):
        """Cancela y guarda los turnos completados, sin esperar al backend."""
        self.cancelar()
        with self._estado_lock:
            historial = deepcopy(self.historial)
        return self._guardar_copia(historial)


def _estado_barra():
    from core import ai_engine
    selector = ai_engine.get_selector()
    return f"Modo: {selector.modo.upper()} · {ai_engine.describir_motor_activo(selector)}"


def _instalar_avisador(funcion):
    """Cambia el destino de los avisos de ai_engine y devuelve el anterior."""
    from core import ai_engine
    anterior = ai_engine._avisador
    ai_engine.set_avisador(funcion)
    return anterior
