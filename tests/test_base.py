"""Utilidades comunes de los motores (core/motors/base.py)."""
import sys

import pytest

from core.motors import base


def test_recortar_mensajes_conserva_system_y_ultimos_n():
    msgs = [
        {"role": "system", "content": "s1"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "system", "content": "s2"},
        {"role": "user", "content": "u3"},
    ]
    rec = base.recortar_mensajes(msgs, 2)
    assert [m["content"] for m in rec] == ["s1", "u2", "s2", "u3"]


def test_recortar_mensajes_sin_limite_o_por_debajo():
    msgs = [{"role": "user", "content": "u1"}, {"role": "user", "content": "u2"}]
    assert base.recortar_mensajes(msgs, None) == msgs
    assert base.recortar_mensajes(msgs, None) is not msgs  # copia
    assert base.recortar_mensajes(msgs, 5) == msgs


def test_separar_sistema():
    msgs = [
        {"role": "system", "content": "A"},
        {"role": "user", "content": "hola"},
        {"role": "system", "content": "B"},
    ]
    sistema, turnos = base.separar_sistema(msgs)
    assert sistema == "A\n\nB"
    assert turnos == [{"role": "user", "content": "hola"}]


def test_mensajes_a_prompt():
    msgs = [
        {"role": "system", "content": "Eres B.A.I"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "buenas"},
        {"role": "user", "content": "¿qué tal?"},
    ]
    assert base.mensajes_a_prompt(msgs) == (
        "Eres B.A.I\nUsuario: hola\nB.A.I: buenas\nUsuario: ¿qué tal?\nB.A.I:"
    )


@pytest.mark.parametrize("malo", [None, [], "texto", [{"role": "user"}], [{"role": "robot", "content": "x"}]])
def test_validar_mensajes_rechaza_estructuras_invalidas(malo):
    with pytest.raises(ValueError):
        base.validar_mensajes(malo)


def test_validar_mensajes_acepta_lista_correcta():
    msgs = [{"role": "user", "content": "x"}]
    assert base.validar_mensajes(msgs) is msgs


def test_libreria_instalada(monkeypatch):
    assert base.libreria_instalada("os") is True
    assert base.libreria_instalada("paquete_inexistente_bai_xyz") is False
    monkeypatch.setitem(sys.modules, "paquete_bloqueado", None)
    assert base.libreria_instalada("paquete_bloqueado") is False


# --------------------------------------------------------------------------- validar_gguf
def test_validar_gguf_ok(tmp_path):
    from tests.conftest import escribir_gguf_falso
    assert base.validar_gguf(str(escribir_gguf_falso(tmp_path / "ok.gguf"))) == (True, "")


@pytest.mark.parametrize("preparar,fragmento", [
    (lambda d: None, "falta 'model_path'"),
    (lambda d: str(d / "no.gguf"), "no se encuentra"),
    (lambda d: str(d), "no es un fichero"),
    (lambda d: _escribir(d / "html.gguf", b"<!DOCTYPE html><html>Not Found</html>"), "formato GGUF"),
    (lambda d: _escribir(d / "corto.gguf", b"GGU"), "formato GGUF"),
    (lambda d: _escribir(d / "v99.gguf", b"GGUF" + (99).to_bytes(4, "little") + b"\0" * 8), "versión GGUF desconocida"),
])
def test_validar_gguf_rechaza_ficheros_invalidos(tmp_path, preparar, fragmento):
    ok, motivo = base.validar_gguf(preparar(tmp_path))
    assert ok is False and fragmento in motivo


def _escribir(path, datos):
    path.write_bytes(datos)
    return str(path)



# --------------------------------------------------------------------------- consolidar_sistema / contexto_efectivo
MENSAJES_BAI = [
    {"role": "system", "content": "Eres B.A.I, un asistente modular."},
    {"role": "system", "content": "El usuario se llama Test y tiene una furgoneta camper."},
    {"role": "user", "content": "hola"},
    {"role": "assistant", "content": "buenas"},
    {"role": "system", "content": "Responde siempre en el idioma del usuario."},
    {"role": "user", "content": "¿cómo se llama mi vehículo?"},
]


def test_consolidar_sistema_une_todos_los_system_y_conserva_turnos():
    res = base.consolidar_sistema(MENSAJES_BAI)
    assert [m["role"] for m in res] == ["system", "user", "assistant", "user"]
    assert res[0]["content"] == ("Eres B.A.I, un asistente modular.\n\n"
                                 "El usuario se llama Test y tiene una furgoneta camper.\n\n"
                                 "Responde siempre en el idioma del usuario.")
    assert [m["content"] for m in res[1:]] == ["hola", "buenas", "¿cómo se llama mi vehículo?"]
    assert MENSAJES_BAI[0]["content"] == "Eres B.A.I, un asistente modular."  # no muta la entrada


def test_consolidar_sistema_sin_system():
    turnos = [{"role": "user", "content": "x"}]
    assert base.consolidar_sistema(turnos) == turnos


def test_contexto_efectivo_es_igual_consolidado_o_no():
    assert base.contexto_efectivo(MENSAJES_BAI) == base.contexto_efectivo(base.consolidar_sistema(MENSAJES_BAI))
