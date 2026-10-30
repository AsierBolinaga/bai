"""Cancelacion por turno, sin cambiar el contrato de los adaptadores."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event


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
