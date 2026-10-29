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
    monkeypatch.setattr(os, "mkdir", lambda *a, **kw: (_ for _ in ()).throw(OSError("solo lectura (simulado)")))
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


# --------------------------------------------------------------------------- procesos nuevos con fallo persistente
def _sesion_cli(tmp_path, entradas, historial_inamovible, sin_borrar=False):
    """Una sesión completa de la CLI real (backend controlado) en un intérprete nuevo.
    Con historial_inamovible, CADA proceso simula que historial.json no se puede renombrar;
    con sin_borrar, que ningún fichero del directorio de historial se puede borrar."""
    import subprocess
    import sys
    from tests.test_cli import _programa_sesion
    programa = _programa_sesion(tmp_path, entradas, tmp_path / "recibido.json")
    parches = ""
    if historial_inamovible:
        parches += """_real_replace = os.replace
def _replace(origen, destino):
    if str(origen) == m.SESSION_FILE:
        raise OSError("no se puede renombrar (simulado)")
    return _real_replace(origen, destino)
os.replace = _replace
"""
    if sin_borrar:
        parches += """_real_remove = os.remove
def _remove(ruta):
    if os.path.dirname(str(ruta)) == m.HISTORY_DIR:
        raise OSError("no se puede borrar (simulado)")
    return _real_remove(ruta)
os.remove = _remove
"""
    programa = programa.replace("import os\n", "import os\n" + parches, 1)
    r = subprocess.run([sys.executable, "-c", programa], cwd=str(tmp_path), capture_output=True, text=True,
                       timeout=60, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_sesiones_nuevas_con_historial_corrupto_inamovible_no_duplican(tmp_path):
    hist = tmp_path / "hist"
    hist.mkdir()
    roto = hist / "historial.json"
    roto.write_text('[{"role": "user", "content": "valioso"}, {rot', encoding="utf-8")
    bytes_rotos = roto.read_bytes()

    for n in (1, 2, 3):
        out = _sesion_cli(tmp_path, [f"mensaje {n}", "salir"], historial_inamovible=True)
        assert "no tocaré" in out
        assert roto.read_bytes() == bytes_rotos                               # intacto en cada sesión
        rescates = list(hist.glob("historial-rescate-*.json"))
        assert len(rescates) == 1                                             # el anterior se consolida y se borra
        turnos = [m["content"] for m in json.loads(rescates[0].read_text(encoding="utf-8")) if m["role"] == "user"]
        assert turnos == [f"mensaje {i}" for i in range(1, n + 1)]            # sin duplicados
    # el contexto que recibe el motor en la 3ª sesión tampoco lleva turnos repetidos
    recibido = json.loads((tmp_path / "recibido.json").read_text(encoding="utf-8"))
    assert [m["content"] for m in recibido if m["role"] == "user"] == ["mensaje 1", "mensaje 2", "mensaje 3"]

    # cuando el fichero vuelve a poder apartarse: se conserva como copia y todo se consolida
    out = _sesion_cli(tmp_path, ["mensaje 4", "salir"], historial_inamovible=False)
    assert "conservado en" in out
    copias = list(hist.glob("historial.json.corrupto-*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == bytes_rotos
    assert not list(hist.glob("historial-rescate-*.json"))
    turnos = [m["content"] for m in json.loads(roto.read_text(encoding="utf-8")) if m["role"] == "user"]
    assert turnos == ["mensaje 1", "mensaje 2", "mensaje 3", "mensaje 4"]


# --------------------------------------------------------------------------- consolidación idempotente con borrados fallidos
def _cargar_como_proceso_nuevo():
    memoria._HISTORIAL_PROTEGIDO.clear()     # estado de un intérprete recién arrancado
    return memoria.load_full_history()


def _sin_borrar(mp, directorio):
    real = os.remove

    def remove(ruta):
        if os.path.dirname(str(ruta)) == str(directorio):
            raise OSError("no se puede borrar (simulado)")
        return real(ruta)
    mp.setattr(os, "remove", remove)


def test_borrado_fallido_de_sesiones_antiguas_no_duplica(historial, monkeypatch):
    (historial / "historial.json").write_text("[]", encoding="utf-8")
    (historial / "2024-01-01.json").write_text(json.dumps([{"role": "user", "content": "antigua"}]), encoding="utf-8")
    _sin_borrar(monkeypatch, historial)
    for _ in range(3):
        assert _cargar_como_proceso_nuevo() == [{"role": "user", "content": "antigua"}]
    assert (historial / "2024-01-01.json").exists()                       # no se pudo borrar
    manifiesto = json.loads((historial / "historial.json.absorbidos").read_text())
    assert list(manifiesto) == ["2024-01-01.json"]


def test_ambos_fallos_activos_varias_sesiones_sin_duplicados(historial):
    roto = historial / "historial.json"
    roto.write_text("[{roto", encoding="utf-8")
    real_replace = os.replace
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("simulado"))
                   if str(a) == str(roto) else real_replace(a, b))
        _sin_borrar(mp, historial)
        for n in range(1, 5):
            hist = _cargar_como_proceso_nuevo()
            assert [m["content"] for m in hist] == [f"s{i}" for i in range(1, n)]
            hist.append({"role": "user", "content": f"s{n}"})
            assert memoria.save_chat_history(hist)
    assert roto.read_text() == "[{roto"
    # con los fallos resueltos todo se consolida una sola vez
    assert [m["content"] for m in _cargar_como_proceso_nuevo()] == ["s1", "s2", "s3", "s4"]
    assert sorted(p.name for p in historial.iterdir() if not p.name.startswith("historial.json.corrupto-")) == ["historial.json"]


def test_archivo_absorbido_cuyo_contenido_cambia_se_vuelve_a_cargar(historial, monkeypatch):
    """El manifiesto identifica por contenido: si el fichero cambia, no se pierde lo nuevo."""
    (historial / "historial.json").write_text("[]", encoding="utf-8")
    vieja = historial / "2024-01-01.json"
    vieja.write_text(json.dumps([{"role": "user", "content": "a"}]), encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        _sin_borrar(mp, historial)
        _cargar_como_proceso_nuevo()
    vieja.write_text(json.dumps([{"role": "user", "content": "b"}]), encoding="utf-8")
    assert [m["content"] for m in _cargar_como_proceso_nuevo()] == ["a", "b"]
    assert not vieja.exists() and not (historial / "historial.json.absorbidos").exists()


def test_manifiesto_de_un_principal_ilegible_no_oculta_datos(historial, monkeypatch):
    """Si el destino que dice contener un fichero no se puede leer, ese fichero se carga."""
    roto = historial / "historial.json"
    roto.write_text("[{roto", encoding="utf-8")
    vieja = historial / "2024-01-01.json"
    vieja.write_text(json.dumps([{"role": "user", "content": "a"}]), encoding="utf-8")
    import hashlib
    (historial / "historial.json.absorbidos").write_text(
        json.dumps({"2024-01-01.json": hashlib.sha256(vieja.read_bytes()).hexdigest()}))
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("simulado"))
                        if str(a) == str(roto) else real_replace(a, b))
    assert [m["content"] for m in _cargar_como_proceso_nuevo()] == ["a"]


def test_manifiesto_ilegible_se_ignora_sin_perder_datos(historial, capsys):
    (historial / "historial.json").write_text(json.dumps([{"role": "user", "content": "x"}]), encoding="utf-8")
    (historial / "historial.json.absorbidos").write_text("{roto", encoding="utf-8")
    assert [m["content"] for m in _cargar_como_proceso_nuevo()] == ["x"]
    assert "lo ignoro" in capsys.readouterr().out


def test_sin_fallos_no_quedan_manifiestos(historial):
    (historial / "historial.json").write_text("[]", encoding="utf-8")
    (historial / "2024-01-01.json").write_text(json.dumps([{"role": "user", "content": "a"}]), encoding="utf-8")
    _cargar_como_proceso_nuevo()
    assert sorted(p.name for p in historial.iterdir()) == ["historial.json"]


def test_procesos_cli_repetidos_con_ambos_fallos_activos(tmp_path):
    """historial.json dañado e inamovible + ningún fichero borrable, en cada proceso:
    el historial que ve el motor y el último rescate no tienen duplicados."""
    hist = tmp_path / "hist"
    hist.mkdir()
    roto = hist / "historial.json"
    roto.write_text('[{"role": "user", "content": "valioso"}, {rot', encoding="utf-8")
    bytes_rotos = roto.read_bytes()
    esperados = []
    for n in range(1, 5):
        out = _sesion_cli(tmp_path, [f"mensaje {n}", "salir"], historial_inamovible=True, sin_borrar=True)
        assert "no tocaré" in out
        assert ("no se puede borrar" in out) == (n > 1)                # desde la 2ª hay rescates que borrar
        esperados.append(f"mensaje {n}")
        recibido = json.loads((tmp_path / "recibido.json").read_text(encoding="utf-8"))
        assert [m["content"] for m in recibido if m["role"] == "user"] == esperados      # contexto sin duplicados
        assert roto.read_bytes() == bytes_rotos
        rescates = sorted(hist.glob("historial-rescate-*.json"))
        assert len(rescates) == n                                                       # no se pueden borrar...
        ultimo = json.loads(rescates[-1].read_text(encoding="utf-8"))
        assert [m["content"] for m in ultimo if m["role"] == "user"] == esperados       # ...pero no se repiten
        if n > 1:
            manifiesto = json.loads((hist / (rescates[-1].name + ".absorbidos")).read_text())
            assert sorted(manifiesto) == [r.name for r in rescates[:-1]]                # acumulativo

    # Fallos resueltos: una sola consolidación, sin duplicados y sin ficheros sobrantes
    out = _sesion_cli(tmp_path, ["mensaje 5", "salir"], historial_inamovible=False, sin_borrar=False)
    turnos = [m["content"] for m in json.loads(roto.read_text(encoding="utf-8")) if m["role"] == "user"]
    assert turnos == esperados + ["mensaje 5"]
    copias = list(hist.glob("historial.json.corrupto-*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == bytes_rotos
    assert sorted(p.name for p in hist.iterdir() if p not in copias) == ["historial.json"]


def test_procesos_cli_main_recuperado_con_borrado_aun_fallido(tmp_path):
    """Fase 1: historial.json dañado e inamovible + borrados imposibles. Fase 2: el
    principal ya se puede apartar pero los rescates siguen sin poder borrarse.
    Fase 3: sin fallos. En ninguna sesión se duplica nada."""
    hist = tmp_path / "hist"
    hist.mkdir()
    roto = hist / "historial.json"
    roto.write_text('[{"role": "user", "content": "valioso"}, {rot', encoding="utf-8")
    bytes_rotos = roto.read_bytes()
    esperados = []

    def sesion(n, inamovible, sin_borrar):
        _sesion_cli(tmp_path, [f"mensaje {n}", "salir"], historial_inamovible=inamovible, sin_borrar=sin_borrar)
        esperados.append(f"mensaje {n}")
        recibido = json.loads((tmp_path / "recibido.json").read_text(encoding="utf-8"))
        assert [m["content"] for m in recibido if m["role"] == "user"] == esperados[:-1] + [f"mensaje {n}"]

    for n in (1, 2, 3):
        sesion(n, inamovible=True, sin_borrar=True)
    rescates = sorted(hist.glob("historial-rescate-*.json"))
    assert len(rescates) == 3 and roto.read_bytes() == bytes_rotos

    for n in (4, 5, 6):                                   # el principal se recupera; los rescates no se pueden borrar
        sesion(n, inamovible=False, sin_borrar=True)
        copias = list(hist.glob("historial.json.corrupto-*.bak"))
        assert len(copias) == 1 and copias[0].read_bytes() == bytes_rotos
        turnos = [m["content"] for m in json.loads(roto.read_text(encoding="utf-8")) if m["role"] == "user"]
        assert turnos == esperados                        # consolidado en historial.json, sin duplicados
        assert sorted(hist.glob("historial-rescate-*.json")) == rescates   # siguen ahí, sin borrar...
        manifiesto = json.loads((hist / "historial.json.absorbidos").read_text())
        assert sorted(manifiesto) == [r.name for r in rescates]             # ...pero anotados como absorbidos

    sesion(7, inamovible=False, sin_borrar=False)        # sin fallos: se limpia todo de una vez
    turnos = [m["content"] for m in json.loads(roto.read_text(encoding="utf-8")) if m["role"] == "user"]
    assert turnos == esperados
    assert sorted(p.name for p in hist.iterdir() if not p.name.startswith("historial.json.corrupto-")) == ["historial.json"]


@pytest.mark.parametrize("destino,absorbido", [("0-primero.json", "9-ultimo.json"), ("9-ultimo.json", "0-primero.json")])
def test_manifiesto_funciona_sea_cual_sea_el_orden_de_carga(historial, destino, absorbido):
    """El fichero absorbido se salta aunque su nombre se ordene antes o después del destino que lo contiene."""
    import hashlib
    (historial / "historial.json").write_text("[]", encoding="utf-8")
    (historial / absorbido).write_text(json.dumps([{"role": "user", "content": "a"}]), encoding="utf-8")
    (historial / destino).write_text(json.dumps([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]),
                                     encoding="utf-8")
    (historial / (destino + ".absorbidos")).write_text(
        json.dumps({absorbido: hashlib.sha256((historial / absorbido).read_bytes()).hexdigest()}))
    assert [m["content"] for m in _cargar_como_proceso_nuevo()] == ["a", "b"]
    assert sorted(p.name for p in historial.iterdir()) == ["historial.json"]


def test_manifiesto_en_cadena_con_borrados_parciales(historial):
    """R1 absorbido por R2 (manifiesto), R2 absorbido por R3; R2 se borró pero R1 y R3 no:
    el manifiesto acumulativo de R3 sigue cubriendo a R1."""
    import hashlib
    (historial / "historial.json").write_text("[]", encoding="utf-8")
    r1 = historial / "historial-rescate-1.json"
    r1.write_text(json.dumps([{"role": "user", "content": "a"}]), encoding="utf-8")
    r3 = historial / "historial-rescate-3.json"
    r3.write_text(json.dumps([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]), encoding="utf-8")
    (historial / "historial-rescate-3.json.absorbidos").write_text(json.dumps({
        "historial-rescate-1.json": hashlib.sha256(r1.read_bytes()).hexdigest(),
        "historial-rescate-2.json": "ya-no-existe"}))
    with pytest.MonkeyPatch.context() as mp:
        _sin_borrar(mp, historial)
        for _ in range(3):
            assert [m["content"] for m in _cargar_como_proceso_nuevo()] == ["a", "b"]
    manifiesto = json.loads((historial / "historial.json.absorbidos").read_text())
    assert sorted(manifiesto) == ["historial-rescate-1.json", "historial-rescate-3.json"]


def test_historial_existente_pero_sin_stat_no_se_trata_como_ausente(historial, monkeypatch, capsys):
    """Si os.stat falla (p. ej. permisos del directorio) el fichero existe igualmente:
    se protege y nunca se sobreescribe."""
    fichero = historial / "historial.json"
    fichero.write_text(json.dumps([{"role": "user", "content": "valioso"}]), encoding="utf-8")
    real_open = open

    def abrir(ruta, *a, **kw):
        if str(ruta) == str(fichero) and (not a or "r" in a[0]):
            raise PermissionError("permiso denegado (simulado)")
        return real_open(ruta, *a, **kw)

    monkeypatch.setattr("builtins.open", abrir)
    monkeypatch.setattr(os.path, "exists", lambda p: False if str(p) == str(fichero) else os.path.lexists(p))
    assert _cargar_como_proceso_nuevo() == []
    assert memoria.save_chat_history([{"role": "user", "content": "nuevo"}]) is True
    monkeypatch.setattr("builtins.open", real_open)
    assert json.loads(fichero.read_text(encoding="utf-8")) == [{"role": "user", "content": "valioso"}]
    assert list(historial.glob("historial-rescate-*.json"))


# --------------------------------------------------------------------------- privacidad de los directorios
@pytest.fixture
def umask_022():
    anterior = os.umask(0o022)
    yield
    os.umask(anterior)


def _modo(ruta):
    import stat
    return stat.S_IMODE(os.stat(ruta).st_mode)


def test_history_se_crea_0700_al_importar_en_un_interprete_nuevo(umask_022, tmp_path):
    """Copia temporal del proyecto (core/ + config/): importar core.memory_engine crea
    history/ como 0700 sin tocar el directorio del proyecto ni config/."""
    import shutil
    import subprocess
    import sys
    from config.motors_config import PROJECT_ROOT
    proyecto = tmp_path / "proyecto"
    for sub in ("core", "config"):
        shutil.copytree(PROJECT_ROOT / sub, proyecto / sub, ignore=shutil.ignore_patterns("__pycache__"))
    antes = (_modo(proyecto), _modo(proyecto / "config"), _modo(proyecto / "config" / "data"))
    r = subprocess.run([sys.executable, "-c", "import os; os.umask(0o022); import core.memory_engine"],
                       cwd=str(proyecto), capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert _modo(proyecto / "history") == 0o700
    assert (_modo(proyecto), _modo(proyecto / "config"), _modo(proyecto / "config" / "data")) == antes
    assert not (proyecto / "history" / "historial.json").exists()      # importar no escribe ficheros


def test_cada_nivel_nuevo_del_directorio_de_historial_es_0700(umask_022, monkeypatch, tmp_path):
    base = tmp_path / "base"
    base.mkdir()                                                        # ya existente: no se toca
    base.chmod(0o755)
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(base / "a" / "b" / "c"))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(base / "a" / "b" / "c" / "historial.json"))
    assert memoria.load_full_history() == []
    assert _modo(base) == 0o755
    assert [_modo(base / "a"), _modo(base / "a" / "b"), _modo(base / "a" / "b" / "c")] == [0o700] * 3
    assert _modo(memoria.SESSION_FILE) == 0o600
    assert os.umask(0o022) == 0o022


def test_escritura_en_historial_recrea_el_directorio_privado(umask_022, monkeypatch, tmp_path):
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(tmp_path / "h"))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(tmp_path / "h" / "historial.json"))
    assert memoria.save_chat_history([{"role": "user", "content": "x"}]) is True   # sin load previo
    assert _modo(tmp_path / "h") == 0o700 and _modo(memoria.SESSION_FILE) == 0o600


def test_directorio_compartido_de_config_no_se_hace_privado(umask_022, monkeypatch, tmp_path):
    """facts.yaml/user_profile.yaml viven en config/data (compartido): el directorio
    se crea con los permisos habituales y sólo los ficheros son 0600."""
    monkeypatch.setattr(memoria, "FACTS_PATH", str(tmp_path / "cfg" / "data" / "facts.yaml"))
    monkeypatch.setattr(memoria, "MEMORY_PATH", str(tmp_path / "cfg" / "data" / "user_profile.yaml"))
    memoria.guardar_hechos({})
    assert _modo(tmp_path / "cfg") == 0o755 and _modo(tmp_path / "cfg" / "data") == 0o755
    assert _modo(memoria.FACTS_PATH) == 0o600


def test_directorio_de_historial_existente_conserva_sus_permisos(umask_022, monkeypatch, tmp_path):
    h = tmp_path / "h"
    h.mkdir()
    h.chmod(0o750)
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(h))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(h / "historial.json"))
    memoria.load_full_history()
    assert _modo(h) == 0o750
