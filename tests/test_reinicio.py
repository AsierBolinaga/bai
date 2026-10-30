from types import SimpleNamespace

import pytest

import bai
from core import ai_engine, reinicio, preparar_modelo


@pytest.mark.parametrize("actual,nuevo,aislamiento,esperado", [
    ("offline", "online", "proceso", "online"),
    ("online", "offline", "proceso", "offline"),
    ("offline", "offline", "proceso", None),
    ("offline", "online", "python", None),
])
def test_transiciones_reinician_solo_si_necesario(monkeypatch, actual, nuevo, aislamiento, esperado):
    monkeypatch.setattr(ai_engine, "_selector", SimpleNamespace(
        modo=actual, config={"aislamiento_offline": aislamiento}))
    assert reinicio.modo_reinicio(f"pasa a modo {nuevo}") == esperado
    assert reinicio.modo_reinicio("no pases a modo online") is None


def test_supervisor_fuera_del_namespace_relanza_y_prepara_solo_offline(monkeypatch):
    codigos = iter([reinicio.ONLINE, reinicio.OFFLINE, 0])
    llamadas, preparados = [], []

    def ejecutar(args):
        llamadas.append(args)
        return SimpleNamespace(returncode=next(codigos))

    monkeypatch.setattr(bai.subprocess, "run", ejecutar)
    monkeypatch.setattr(preparar_modelo, "preparar_modelo", lambda cfg: preparados.append(cfg))
    assert bai.main(["--ui"]) == 0
    assert len(llamadas) == 3 and len(preparados) == 2
    assert "--online" in llamadas[1] and "--offline" not in llamadas[1]
    assert "--offline" in llamadas[2] and "--online" not in llamadas[2]
    assert all("--sesion" in c and "--ui" in c for c in llamadas)


def test_descarga_fallida_no_arranca_sesion_ni_nube(monkeypatch):
    from core.motors.base import MotorError
    def fallar(cfg):
        raise MotorError("sin red")
    monkeypatch.setattr(preparar_modelo, "preparar_modelo", fallar)
    monkeypatch.setattr(bai.subprocess, "run", lambda args: pytest.fail("no debe arrancar"))
    assert bai.main([]) == 1
