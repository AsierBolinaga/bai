import pytest

from core import procesos


def test_esperar_grupo_no_confunde_senal_enviada_con_proceso_terminado(monkeypatch):
    observados = iter([{123: "R"}, {123: "S"}, {}])
    esperas = []
    monkeypatch.setattr(procesos, "estado_grupo", lambda grupo: next(observados))
    monkeypatch.setattr(procesos.time, "sleep", esperas.append)
    assert procesos.esperar_grupo(123, 1) == {}
    assert esperas == [0.01, 0.01]


def test_esperar_grupo_informa_procesos_que_siguen_activos(monkeypatch):
    monkeypatch.setattr(procesos, "estado_grupo", lambda grupo: {123: "D"})
    with pytest.raises(RuntimeError, match=r"123.*D"):
        procesos.esperar_grupo(123, 0)


def test_zombi_no_ejecuta_pero_su_recogida_no_se_certifica(monkeypatch, caplog):
    monkeypatch.setattr(procesos, "estado_grupo", lambda grupo: {123: "Z"})
    assert procesos.esperar_grupo(123, 0) == {123: "Z"}
    assert "sin recoger" in caplog.text


def test_estado_grupo_parsea_comm_con_espacios_y_parentesis(tmp_path, monkeypatch):
    (tmp_path / "123").mkdir()
    (tmp_path / "123/stat").write_text("123 (nombre con ) espacios) S 1 567 8 9")
    (tmp_path / "124").mkdir()
    (tmp_path / "124/stat").write_text("124 (otro) R 1 888 8 9")
    monkeypatch.setattr(procesos, "Path", lambda ruta: tmp_path)
    monkeypatch.setattr(procesos.os, "getpgid", lambda pid: 567 if pid == 123 else 888)
    assert procesos.estado_grupo(567) == {123: "S"}


def test_error_de_inspeccion_no_se_convierte_en_grupo_vacio(monkeypatch):
    def fallar(grupo):
        raise PermissionError("proc restringido")
    monkeypatch.setattr(procesos, "estado_grupo", fallar)
    with pytest.raises(PermissionError, match="restringido"):
        procesos.esperar_grupo(123, 0)
