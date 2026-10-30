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

Turno = namedtuple("Turno", "texto avisos guardado limpiado")

COMANDOS_LIMPIAR = ("reset", "limpiar")
MENSAJE_LIMPIADO = "Memoria de sesión limpiada."
MENSAJE_OCUPADO = "B.A.I sigue respondiendo al mensaje anterior."


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
        self._avisos = []

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
        try:
            return self._procesar(texto)
        finally:
            self._cerrojo.release()

    def enviar_en_hilo(self, texto, al_terminar):
        """Ejecuta `enviar` en un hilo y llama a `al_terminar(turno)` desde ese hilo.
        La ventana no debe tocar Tk desde la llamada: debe pasar el turno a su hilo principal."""
        def trabajo():
            try:
                turno = self.enviar(texto)
            except Exception as e:  # el hilo nunca debe morir en silencio
                turno = Turno(f"Error interno: {e}", [], True, False)
            if turno is not None:
                al_terminar(turno)
        hilo = threading.Thread(target=trabajo, name="bai-ui-turno", daemon=True)
        hilo.start()
        return hilo

    def _procesar(self, texto):
        if texto.lower() in COMANDOS_LIMPIAR:
            self.historial.clear()
            guardado = bool(self._guardar(self.historial))
            return Turno(MENSAJE_LIMPIADO, [], guardado, True)

        self._avisos = []
        antes = _instalar_avisador(self._avisos.append)
        try:
            respuesta = self._preguntar(texto, self.historial)
        finally:
            _instalar_avisador(antes)
        avisos, self._avisos = self._avisos, []
        guardado = bool(self._guardar(self.historial))
        return Turno(respuesta, avisos, guardado, False)

    # ----------------------------------------------------------------- cierre
    def cerrar(self):
        """Guarda el historial al cerrar la ventana (equivale a 'salir' en la consola)."""
        with self._cerrojo:
            return bool(self._guardar(self.historial))


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
