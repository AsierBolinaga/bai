"""Presupuesto conservador de contexto, sin descargar tokenizadores."""
import warnings
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar

from core.motors.base import MotorError, validar_mensajes

_avisador: ContextVar[Callable[[str], None] | None] = ContextVar("avisador_contexto", default=None)


@contextmanager
def avisos_contexto(avisador):
    """Dirige los recortes al canal de avisos del turno, sin cambiar otros hilos."""
    token = _avisador.set(avisador)
    try:
        yield
    finally:
        _avisador.reset(token)


def entero_positivo(valor, nombre):
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise MotorError(f"'{nombre}' debe ser un entero positivo, recibido: {valor!r}.")
    return valor


def estimar_tokens(messages):
    """Un token por byte UTF-8 más margen de formato; no es tokenización exacta."""
    return 64 + sum(len(m["content"].encode("utf-8")) + len(m["role"]) + 16 for m in messages)


def ajustar_contexto(messages, n_ctx, max_tokens, contar=estimar_tokens):
    """Conserva sistemas y última pregunta; elimina primero turnos antiguos.

    El contador debe incluir el formato del adaptador. Nunca modifica los
    mensajes originales ni trunca instrucciones, memoria o pregunta.
    """
    validar_mensajes(messages)
    if any(not isinstance(m["content"], str) for m in messages):
        raise MotorError("El presupuesto de contexto sólo admite mensajes de texto.")
    limite = entero_positivo(n_ctx, "n_ctx")
    reserva = entero_positivo(max_tokens, "max_tokens")
    presupuesto = limite - reserva
    if presupuesto <= 0:
        raise MotorError("Contexto insuficiente: max_tokens debe ser menor que n_ctx.")
    resultado = [dict(m) for m in messages]
    usuarios = [i for i, m in enumerate(resultado) if m["role"] == "user"]
    if not usuarios:
        raise MotorError("No hay una pregunta de usuario para presupuestar el contexto.")
    ultima = usuarios[-1]
    obligatorios = [m for i, m in enumerate(resultado) if m["role"] == "system" or i >= ultima]
    minimo = contar(obligatorios)
    if minimo > presupuesto:
        raise MotorError(
            f"Contexto insuficiente: instrucciones, memoria y pregunta requieren "
            f"{minimo} tokens estimados; quedan {presupuesto} de n_ctx={limite} "
            f"tras reservar {reserva} para responder. Reduce la pregunta o el contexto "
            "de memoria, o configura un n_ctx compatible mayor.")
    eliminados = 0
    while contar(resultado) > presupuesto:
        # Retirar un turno completo evita comenzar el historial por un assistant huérfano.
        primero = next(i for i, m in enumerate(resultado) if m["role"] != "system")
        siguiente = next(i for i in range(primero + 1, len(resultado))
                         if resultado[i]["role"] == "user")
        descartar = {i for i in range(primero, siguiente) if resultado[i]["role"] != "system"}
        resultado = [m for i, m in enumerate(resultado) if i not in descartar]
        eliminados += len(descartar)
    if eliminados:
        aviso = (f"Contexto ajustado: {eliminados} mensajes antiguos omitidos sólo de "
                 "esta petición; el historial guardado y los hechos no se borran.")
        avisador = _avisador.get()
        if avisador is None:
            warnings.warn(aviso, UserWarning, stacklevel=2)
        else:
            avisador(aviso)
    return resultado
