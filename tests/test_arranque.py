"""Opciones de arranque y activación del aislamiento (core/arranque.py, bai.py)."""
import pytest

from config import motors_config as mc
from core import aislamiento, arranque


@pytest.fixture(autouse=True)
def limpiar_sobrescrituras():
    mc.SOBRESCRITURAS.clear()
    yield
    mc.SOBRESCRITURAS.clear()


@pytest.fixture
def aislar_simulado(monkeypatch):
    llamadas = []
    monkeypatch.setattr(aislamiento, "aislar_proceso", lambda: (llamadas.append(1) or (True, "")))
    return llamadas


def test_por_defecto_offline_activa_aislamiento_de_proceso(aislar_simulado):
    salidas = []
    cfg = arranque.preparar_arranque([], salida=salidas.append)
    assert cfg["modo_por_defecto"] == "offline" and cfg["aislamiento_offline"] == "proceso"
    assert aislar_simulado == [1]
    assert any("Aislamiento de proceso activo" in s and "--online" in s for s in salidas)


def test_online_es_autorizacion_explicita_y_no_aisla(aislar_simulado):
    salidas = []
    cfg = arranque.preparar_arranque(["--online"], salida=salidas.append)
    assert cfg["modo_por_defecto"] == "online"
    assert cfg["online"]["prioridad"] == "local"   # local sigue teniendo prioridad
    assert aislar_simulado == [] and salidas == []


def test_aislamiento_python_por_linea_de_comandos(aislar_simulado):
    cfg = arranque.preparar_arranque(["--aislamiento", "python"])
    assert cfg["aislamiento_offline"] == "python" and cfg["modo_por_defecto"] == "offline"
    assert aislar_simulado == []


def test_offline_explicito(aislar_simulado):
    cfg = arranque.preparar_arranque(["--offline"])
    assert cfg["modo_por_defecto"] == "offline" and aislar_simulado == [1]


def test_online_y_offline_son_excluyentes():
    with pytest.raises(SystemExit):
        arranque.preparar_arranque(["--online", "--offline"])


def test_aislamiento_no_disponible_avisa_honestamente(monkeypatch):
    monkeypatch.setattr(aislamiento, "aislar_proceso", lambda: (False, "sólo disponible en Linux"))
    salidas = []
    arranque.preparar_arranque([], salida=salidas.append)
    assert any("no disponible (sólo disponible en Linux)" in s and "NO cubre subprocesos" in s for s in salidas)


def test_sobrescrituras_afectan_a_cargas_posteriores(aislar_simulado):
    arranque.preparar_arranque(["--online"])
    assert mc.cargar_motors_config()["modo_por_defecto"] == "online"
    mc.SOBRESCRITURAS.clear()
    assert mc.cargar_motors_config()["modo_por_defecto"] == "offline"


def test_config_aislamiento_invalido(tmp_path):
    import yaml
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"aislamiento_offline": "sandbox"}), encoding="utf-8")
    with pytest.raises(mc.ConfigError):
        mc.cargar_motors_config(p)



def test_arranque_informa_incidencias_de_loopback_y_uid(monkeypatch):
    monkeypatch.setattr(aislamiento, "aislar_proceso", lambda: (True, "loopback no activado: EPERM"))
    monkeypatch.setattr(aislamiento, "estado", lambda: {
        "loopback": False, "mapa_uid_gid": False,
        "incidencias": ["uid_map (1000) no aplicado: Permission denied", "loopback no activado: EPERM"]})
    salidas = []
    arranque.preparar_arranque([], salida=salidas.append)
    texto = "\n".join(salidas)
    assert "Aislamiento de proceso activo" in texto
    assert "no se pudo activar la interfaz loopback" in texto
    assert "mapa de uid/gid no se aplicó" in texto
    assert "- uid_map (1000) no aplicado: Permission denied" in texto and "- loopback no activado: EPERM" in texto


def test_arranque_sin_incidencias_no_muestra_avisos(monkeypatch):
    monkeypatch.setattr(aislamiento, "aislar_proceso", lambda: (True, ""))
    monkeypatch.setattr(aislamiento, "estado", lambda: {"loopback": True, "mapa_uid_gid": True, "incidencias": []})
    salidas = []
    arranque.preparar_arranque([], salida=salidas.append)
    assert len(salidas) == 1 and "ATENCIÓN" not in salidas[0]
