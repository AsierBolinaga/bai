"""
Historial de conversación (core/memory_engine.save_chat_history /
load_full_history): un historial dañado o ilegible se conserva, nunca se
sobreescribe; las entradas malformadas se filtran; la escritura es atómica y
un fallo de escritura no rompe la sesión.
"""
import json
import os

import pytest

import core.memory_engine as memoria


@pytest.fixture
def historial(monkeypatch, tmp_path):
    d = tmp_path / "history"
    d.mkdir()
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(d))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(d / "historial.json"))
    return d


def test_historial_corrupto_se_conserva_y_se_empieza_uno_nuevo(historial, capsys):
    roto = historial / "historial.json"
    roto.write_text('[{"role": "user", "content": "hola"}, {"role": ', encoding="utf-8")   # JSON truncado
    bytes_rotos = roto.read_bytes()
    assert memoria.load_full_history() == []
    copias = list(historial.glob("historial.json.corrupto-*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == bytes_rotos   # conservado byte a byte
    assert json.loads(roto.read_text(encoding="utf-8")) == []             # historial nuevo
    assert "conservado en" in capsys.readouterr().out


@pytest.mark.parametrize("contenido", ['{"role": "user"}', '"texto"', "42", "\xff\xfe".encode("latin-1").decode("latin-1")])
def test_estructura_inesperada_tambien_se_conserva(historial, contenido):
    roto = historial / "historial.json"
    roto.write_text(contenido, encoding="latin-1")
    antes = roto.read_bytes()
    assert memoria.load_full_history() == []
    assert list(historial.glob("historial.json.corrupto-*.bak"))[0].read_bytes() == antes


def test_entradas_malformadas_se_filtran_sin_perder_las_validas(historial):
    (historial / "historial.json").write_text(json.dumps([
        {"role": "user", "content": "hola"},
        {"sin_role": True},
        "cadena suelta",
        {"role": "system", "content": "fuera"},
        {"role": "assistant", "content": 5},
        {"role": "assistant", "content": "respuesta"},
    ]), encoding="utf-8")
    assert memoria.load_full_history() == [{"role": "user", "content": "hola"},
                                           {"role": "assistant", "content": "respuesta"}]


def test_sesion_antigua_ilegible_no_se_borra(historial):
    (historial / "historial.json").write_text("[]", encoding="utf-8")
    vieja = historial / "2024-01-01.json"
    vieja.write_text("{rota", encoding="utf-8")
    buena = historial / "2024-01-02.json"
    buena.write_text(json.dumps([{"role": "user", "content": "antes"}]), encoding="utf-8")
    assert memoria.load_full_history() == [{"role": "user", "content": "antes"}]
    assert vieja.exists() and not buena.exists()                         # la buena se consolida, la rota se conserva


def test_historial_ilegible_no_se_sobreescribe(historial, monkeypatch, capsys):
    fichero = historial / "historial.json"
    fichero.write_text(json.dumps([{"role": "user", "content": "valioso"}]), encoding="utf-8")
    real_open = open

    def abrir(ruta, *a, **kw):
        if str(ruta) == str(fichero) and (not a or "r" in a[0]):
            raise PermissionError("sin permiso (simulado)")
        return real_open(ruta, *a, **kw)

    monkeypatch.setattr("builtins.open", abrir)
    assert memoria.load_full_history() == []
    assert memoria.save_chat_history([{"role": "user", "content": "nuevo"}]) is True   # la CLI guarda después
    monkeypatch.setattr("builtins.open", real_open)
    assert json.loads(fichero.read_text(encoding="utf-8")) == [{"role": "user", "content": "valioso"}]
    rescates = list(historial.glob("historial-rescate-*.json"))
    assert len(rescates) == 1 and json.loads(rescates[0].read_text()) == [{"role": "user", "content": "nuevo"}]
    assert "no tocaré" in capsys.readouterr().out


def test_guardado_atomico_y_fallo_de_escritura_sin_perdida(historial, capsys):
    assert memoria.save_chat_history([{"role": "user", "content": "uno"}]) is True
    fichero = historial / "historial.json"
    antes = fichero.read_bytes()

    def explota(*a, **kw):
        raise OSError("disco lleno (simulado)")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", explota)
        assert memoria.save_chat_history([{"role": "user", "content": "dos"}]) is False
    assert fichero.read_bytes() == antes
    assert not list(historial.glob(".historial-*"))
    assert "no he podido guardar el historial" in capsys.readouterr().out


def test_cli_sobrevive_a_un_historial_que_no_se_puede_guardar(monkeypatch, tmp_path, capsys):
    """Ctrl+C / salir con el historial no escribible: se avisa y la CLI termina sin traza."""
    import builtins
    import core.assistant as assistant
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(tmp_path / "no-existe" / "historial.json"))
    monkeypatch.setattr(assistant, "chat_history", [{"role": "user", "content": "x"}])
    monkeypatch.setattr(assistant, "describir_estado", lambda: "estado de prueba")
    monkeypatch.setattr(os, "makedirs", lambda *a, **kw: (_ for _ in ()).throw(OSError("solo lectura (simulado)")))
    monkeypatch.setattr(builtins, "input", lambda *_: "salir")
    assistant.run_assistant()
    out = capsys.readouterr().out
    assert "Agur" in out and "no he podido guardar el historial" in out


def test_corrupto_sin_respaldo_posible_sobrevive_a_los_guardados_de_la_cli(historial, monkeypatch, capsys):
    """historial.json dañado + no se puede renombrar: ni la carga ni los guardados
    posteriores de la CLI lo sobreescriben; la sesión va a un fichero de rescate."""
    import builtins
    import core.assistant as assistant
    roto = historial / "historial.json"
    roto.write_text('[{"role": "user", "content": "valioso"}, {rot', encoding="utf-8")
    bytes_rotos = roto.read_bytes()
    real_replace = os.replace

    def replace(origen, destino):
        if str(origen) == str(roto):                     # apartar el corrupto falla
            raise OSError("no se puede renombrar (simulado)")
        return real_replace(origen, destino)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(assistant, "chat_history", memoria.load_full_history())
    monkeypatch.setattr(assistant, "describir_estado", lambda: "estado de prueba")
    monkeypatch.setattr(assistant, "ask", lambda texto, hist: (hist.extend([
        {"role": "user", "content": texto}, {"role": "assistant", "content": "ok"}]), "ok")[1])
    entradas = ["hola", "salir"]
    monkeypatch.setattr(builtins, "input", lambda *_: entradas.pop(0))
    assistant.run_assistant()                             # guarda tras el turno y al salir
    assert roto.read_bytes() == bytes_rotos               # intacto byte a byte
    rescates = list(historial.glob("historial-rescate-*.json"))
    assert len(rescates) == 1
    assert json.loads(rescates[0].read_text(encoding="utf-8")) == [
        {"role": "user", "content": "hola"}, {"role": "assistant", "content": "ok"}]
    assert "no tocaré" in capsys.readouterr().out

    # Siguiente arranque, ya con permisos: el corrupto se aparta y el rescate se consolida
    monkeypatch.setattr(os, "replace", real_replace)
    mensajes = memoria.load_full_history()
    assert mensajes == [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "ok"}]
    copias = list(historial.glob("historial.json.corrupto-*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == bytes_rotos
    assert not list(historial.glob("historial-rescate-*.json"))
    assert json.loads(roto.read_text(encoding="utf-8")) == mensajes


def test_proteccion_no_afecta_a_otro_historial(historial, monkeypatch, tmp_path):
    """La protección es por ruta: otro SESSION_FILE sano se guarda con normalidad."""
    roto = historial / "historial.json"
    roto.write_text("{", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("simulado")))
        memoria.load_full_history()
    otro = tmp_path / "otro.json"
    monkeypatch.setattr(memoria, "SESSION_FILE", str(otro))
    assert memoria.save_chat_history([{"role": "user", "content": "x"}]) is True
    assert json.loads(otro.read_text()) == [{"role": "user", "content": "x"}]
    assert roto.read_text() == "{"
