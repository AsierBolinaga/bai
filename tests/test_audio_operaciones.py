import threading

from core.audio_operaciones import OperacionesAudio


def test_cola_serial_y_error_no_silenciado():
    cola = OperacionesAudio()
    entra, sale = threading.Event(), threading.Event()
    orden = []

    def primera():
        orden.append("primera")
        entra.set()
        assert sale.wait(3)
        raise RuntimeError("pausa fallida")

    callback = lambda valor, error: None
    try:
        cola.enviar(primera, callback)
        assert entra.wait(1)
        cola.enviar(lambda: orden.append("segunda"), callback)
        assert orden == ["primera"]
    finally:
        sale.set()
    resultado, valor, error = cola.resultados.get(timeout=2)
    assert resultado is callback and valor is None and str(error) == "pausa fallida"
    cola.resultados.get(timeout=2)
    hilo = cola.cerrar(lambda: orden.append("limpieza"))
    hilo.join(2)
    assert not hilo.is_alive()
    assert orden == ["primera", "segunda", "limpieza"]


def test_cierre_descarta_pendientes_y_limpia_despues_de_operacion_activa():
    cola = OperacionesAudio()
    entra, sale = threading.Event(), threading.Event()
    orden = []

    def bloquear():
        entra.set()
        assert sale.wait(3)
        orden.append("pausado")

    try:
        cola.enviar(bloquear, lambda *_: None)
        assert entra.wait(1)
        cola.enviar(lambda: orden.append("no reproducir"), lambda *_: None)
        hilo = cola.cerrar(lambda: orden.append("limpieza"))
        assert cola.cerrar(lambda: orden.append("no repetir")) is hilo
        assert hilo.is_alive() and not orden
    finally:
        sale.set()
    hilo.join(2)
    assert not hilo.is_alive() and orden == ["pausado", "limpieza"]
