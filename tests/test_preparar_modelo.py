import hashlib
from types import SimpleNamespace

import pytest

from core import preparar_modelo as pm
from core.motors.base import MotorError


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    datos = b"GGUF" + b"modelo ficticio" * 100
    monkeypatch.setattr(pm, "TAMANO", len(datos))
    monkeypatch.setattr(pm, "SHA256", hashlib.sha256(datos).hexdigest())
    monkeypatch.setattr(pm, "libreria_instalada", lambda nombre: True)
    ruta = tmp_path / pm.ARCHIVO
    cfg = {"offline": {"motor": "llama_cpp", "motores": {"llama_cpp": {
        "descargar_al_arrancar": True, "model_path": str(ruta)}}}}
    llamadas = []

    class Respuesta:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, **kw):
            yield datos[:40]
            yield datos[40:]

    def get(*args, **kw):
        llamadas.append((args, kw))
        return Respuesta()

    monkeypatch.setattr(pm.requests, "get", get)
    return SimpleNamespace(datos=datos, ruta=ruta, cfg=cfg, llamadas=llamadas)


def test_descarga_explicita_atomica_verificada_y_arranque_sin_red(entorno):
    e = entorno
    avisos = []
    pm.preparar_modelo(e.cfg, avisos.append, permitir_descarga=True)
    assert e.ruta.read_bytes() == e.datos
    assert len(e.llamadas) == 1 and e.llamadas[0][0] == (pm.URL,)
    assert any("SHA256 verificado" in a for a in avisos)
    pm.preparar_modelo(e.cfg, avisos.append)
    assert len(e.llamadas) == 1
    assert list(e.ruta.parent.glob("*.part")) == []


@pytest.mark.parametrize("fallo", ["hash", "tamano", "red"])
def test_descarga_fallida_no_instala_archivo_y_limpia_temporal(entorno, monkeypatch, fallo):
    if fallo == "hash":
        monkeypatch.setattr(pm, "SHA256", "0" * 64)
    elif fallo == "tamano":
        monkeypatch.setattr(pm, "TAMANO", 1)
    else:
        def fallar(*args, **kw):
            raise pm.requests.ConnectionError("sin conexión")
        monkeypatch.setattr(pm.requests, "get", fallar)
    with pytest.raises(MotorError):
        pm.preparar_modelo(entorno.cfg, permitir_descarga=True)
    assert not entorno.ruta.exists()
    assert list(entorno.ruta.parent.glob("*.part")) == []


def test_existente_corrupto_no_se_sobrescribe(entorno):
    entorno.ruta.write_bytes(b"corrupto")
    with pytest.raises(MotorError, match="incompleto"):
        pm.preparar_modelo(entorno.cfg, permitir_descarga=True)
    assert entorno.ruta.read_bytes() == b"corrupto" and not entorno.llamadas


def test_sin_espacio_o_libreria_no_descarga(entorno, monkeypatch):
    monkeypatch.setattr(pm.shutil, "disk_usage", lambda ruta: SimpleNamespace(free=0))
    with pytest.raises(MotorError, match="espacio"):
        pm.preparar_modelo(entorno.cfg, permitir_descarga=True)
    monkeypatch.setattr(pm, "libreria_instalada", lambda nombre: False)
    with pytest.raises(MotorError, match="llama-cpp"):
        pm.preparar_modelo(entorno.cfg)
    assert not entorno.llamadas


def test_no_descarga_configuraciones_personalizadas(entorno):
    opciones = entorno.cfg["offline"]["motores"]["llama_cpp"]
    opciones["descargar_al_arrancar"] = False
    pm.preparar_modelo(entorno.cfg)
    assert not entorno.llamadas


def test_arranque_sin_modelo_no_intenta_red_ni_crea_directorios(entorno):
    with pytest.raises(MotorError, match="--preparar-modelo"):
        pm.preparar_modelo(entorno.cfg)
    assert not entorno.llamadas and not entorno.ruta.exists()
    assert list(entorno.ruta.parent.iterdir()) == []


def test_preparacion_explicita_no_depende_de_opcion_legada(entorno):
    entorno.cfg["offline"]["motores"]["llama_cpp"].pop("descargar_al_arrancar")
    pm.preparar_modelo(entorno.cfg, permitir_descarga=True)
    assert entorno.ruta.read_bytes() == entorno.datos
