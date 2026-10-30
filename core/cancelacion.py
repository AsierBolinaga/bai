"""Cancelacion por turno, sin cambiar el contrato de los adaptadores."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event
import signal
import threading


class GeneracionCancelada(Exception):
    """El turno fue interrumpido; no debe activar fallback ni persistirse."""


_actual: ContextVar[Event | None] = ContextVar("cancelacion_turno", default=None)


def comprobar_cancelacion():
    evento = _actual.get()
    if evento is not None and evento.is_set():
        raise GeneracionCancelada()


@contextmanager
def cancelacion_turno(evento):
    token = _actual.set(evento)
    try:
        comprobar_cancelacion()
        yield
    finally:
        _actual.reset(token)


@contextmanager
def interrupcion_generacion(al_cancelar):
    """Difiere Ctrl+C hasta un punto seguro y protege la limpieza de repeticiones."""
    interrumpido = Event()

    def comprobar():
        if interrumpido.is_set():
            raise KeyboardInterrupt()

    principal = threading.current_thread() is threading.main_thread()
    if principal:
        anterior = signal.signal(signal.SIGINT, lambda *_: interrumpido.set())
    try:
        yield comprobar
        # Una señal pudo llegar al completar el turno o esperar al escritor.
        if interrumpido.is_set():
            al_cancelar()
            raise KeyboardInterrupt()
    finally:
        if principal:
            signal.signal(signal.SIGINT, anterior)
