import copy

import pytest

from core.contexto import ajustar_contexto, estimar_tokens
from core.motors.base import MotorError


def mensaje(rol, texto):
    return {"role": rol, "content": texto}


def test_frontera_exacta_reserva_respuesta_y_no_muta():
    mensajes = [mensaje("system", "identidad"), mensaje("user", "pregunta")]
    antes = copy.deepcopy(mensajes)
    limite = estimar_tokens(mensajes) + 32
    assert ajustar_contexto(mensajes, limite, 32) == mensajes
    with pytest.raises(MotorError, match="Contexto insuficiente"):
        ajustar_contexto(mensajes, limite - 1, 32)
    assert mensajes == antes


def test_recorta_turnos_completos_conserva_sistemas_y_pregunta():
    mensajes = [mensaje("system", "identidad"), mensaje("user", "viejo" * 100),
                mensaje("assistant", "respuesta vieja"), mensaje("system", "memoria"),
                mensaje("user", "reciente"), mensaje("assistant", "respuesta reciente"),
                mensaje("system", "idioma"), mensaje("user", "actual")]
    antes = copy.deepcopy(mensajes)
    esperados = [mensajes[i] for i in (0, 3, 4, 5, 6, 7)]
    limite = estimar_tokens(esperados) + 50
    with pytest.warns(UserWarning, match="2 mensajes antiguos"):
        resultado = ajustar_contexto(mensajes, limite, 50)
    assert resultado == esperados
    assert estimar_tokens(resultado) + 50 <= limite
    assert mensajes == antes


def test_no_recorta_memoria_o_pregunta_ni_emite_exito_falso():
    mensajes = [mensaje("system", "memoria" * 200), mensaje("user", "hola")]
    with pytest.raises(MotorError, match="memoria y pregunta"):
        ajustar_contexto(mensajes, 256, 64)


def test_estimacion_utf8_cubre_acentos_euskera_emojis_y_codigo():
    texto = "Kaixo, ¿qué tal? 🧠\nprint('hola')" * 15
    mensajes = [mensaje("user", texto)]
    assert estimar_tokens(mensajes) > len(texto.encode("utf-8")) > len(texto)


@pytest.mark.parametrize("campo,valor", [
    ("n_ctx", 0), ("n_ctx", True), ("n_ctx", "2048"),
    ("max_tokens", -1), ("max_tokens", False), ("max_tokens", None),
])
def test_rechaza_limites_invalidos(campo, valor):
    valores = {"n_ctx": 2048, "max_tokens": 256, campo: valor}
    with pytest.raises(MotorError, match=campo):
        ajustar_contexto([mensaje("user", "hola")], **valores)


def test_reserva_no_puede_agotar_la_ventana():
    with pytest.raises(MotorError, match="menor que n_ctx"):
        ajustar_contexto([mensaje("user", "hola")], 256, 256)


def test_turno_huerfano_previo_se_elimina_y_sistemas_intercalados_se_conservan():
    mensajes = [mensaje("assistant", "viejo" * 100), mensaje("system", "identidad"),
                mensaje("user", "actual")]
    esperados = mensajes[1:]
    with pytest.warns(UserWarning):
        assert ajustar_contexto(mensajes, estimar_tokens(esperados) + 20, 20) == esperados


def test_avisador_del_turno_se_restaura_incluso_si_falla():
    from core.contexto import avisos_contexto
    avisos = []
    mensajes = [mensaje("user", "viejo" * 100), mensaje("user", "actual")]
    with pytest.raises(RuntimeError, match="fallo"):
        with avisos_contexto(avisos.append):
            ajustar_contexto(mensajes, 256, 64)
            raise RuntimeError("fallo")
    assert len(avisos) == 1 and "Contexto ajustado" in avisos[0]
    with pytest.warns(UserWarning):
        ajustar_contexto(mensajes, 256, 64)


def test_rechaza_contenido_no_textual_y_contexto_sin_pregunta():
    with pytest.raises(MotorError, match="texto"):
        ajustar_contexto([mensaje("user", None)], 512, 64)
    with pytest.raises(MotorError, match="pregunta"):
        ajustar_contexto([mensaje("system", "identidad")], 512, 64)
