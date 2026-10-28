"""
Fase 7 — Aprendizaje natural local (core/memory_commands.py + almacén de
hechos de core/memory_engine.py).

Todo se prueba con backends controlados y almacenamiento temporal: sin
credenciales, sin red y sin modelos. Cobertura:

- peticiones explícitas (recordar / consultar / actualizar / olvidar) con
  variantes naturales en español e inglés;
- NUNCA se aprende de conversación normal, preguntas, negaciones, citas ni
  respuestas del asistente;
- duplicados, conflictos y ambigüedad (aclaraciones y confirmaciones);
- robustez: fichero dañado intacto, fallo de escritura sin confirmación falsa,
  escritura atómica;
- integración con ai_engine (sin motores ni conectividad) y contexto;
- persistencia real entre procesos de intérprete independientes.
"""
import os
import subprocess
import sys

import pytest
import yaml

import core.memory_engine as memoria
from core.memory_commands import procesar_comando_memoria
from tests.conftest import config_base


@pytest.fixture(autouse=True)
def _almacen_temporal(memoria_temporal):
    """Todos los tests de este módulo usan memoria en tmp_path."""
    return memoria_temporal


def _almacen_temporal_bytes():
    with open(memoria.FACTS_PATH, "rb") as f:
        return f.read()


def hechos_en_disco():
    if not os.path.exists(memoria.FACTS_PATH):
        return {}
    with open(memoria.FACTS_PATH, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return {clave: e["valor"] for clave, e in (datos.get("hechos") or {}).items()}


# --------------------------------------------------------------------------- recordar: variantes naturales
@pytest.mark.parametrize("frase", [
    "recuerda que mi furgoneta es una camper",
    "Recuerda: mi furgoneta es una camper",
    "B.A.I, recuerda que la furgoneta es una camper.",
    "por favor, recuerda que mi furgoneta es una camper",
    "recuerda que mi furgoneta es una camper, por favor",
    "no olvides que mi furgoneta es una camper",
    "memoriza que mi furgoneta es una camper",
    "ten en cuenta que mi furgoneta es una camper",
    "quiero que recuerdes que mi furgoneta es una camper",
    "acuérdate de que mi furgoneta es una camper",
    "aprende que mi furgoneta es una camper",
    "aprende: mi furgoneta es una camper",
    "recuerda que mi furgoneta: una camper",
    # verbos genéricos: sólo con objeto de memoria explícito
    "guarda en tu memoria que mi furgoneta es una camper",
    "guarda este dato: mi furgoneta es una camper",
    "graba en memoria: mi furgoneta es una camper",
    "anota como hecho que la furgoneta es una camper",
    "apunta en tu memoria que mi furgoneta es una camper",
    "toma nota en tu memoria: la furgoneta es una camper",
])
def test_recordar_variantes_es(frase):
    r = procesar_comando_memoria(frase)
    assert r is not None and "furgoneta" in r and "una camper" in r
    assert hechos_en_disco() == {"furgoneta": "una camper"}


@pytest.mark.parametrize("frase", [
    "remember that my van is a camper",
    "remember my van is a camper",
    "please remember that my van is a camper",
    "don't forget that my van is a camper",
    "do not forget my van is a camper",
    "keep in mind that my van is a camper",
    "bear in mind that my van is a camper",
    "memorize that my van is a camper",
    "learn that my van is a camper",
    # generic verbs: only with an explicit memory object
    "save to memory that my van is a camper",
    "store in your memory: my van is a camper",
    "note in your memory that my van is a camper",
    "write down as a fact that my van is a camper",
    "keep in memory that my van is a camper",
])
def test_recordar_variantes_en(frase):
    r = procesar_comando_memoria(frase)
    assert r is not None and "van" in r and "a camper" in r
    assert hechos_en_disco() == {"van": "a camper"}


def test_recordar_se_llama_y_nombre_propio():
    assert "Mishi" in procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    assert "Ane" in procesar_comando_memoria("remember that my boss's name is Ane")
    assert hechos_en_disco() == {"gato": "Mishi", "boss": "Ane"}


def test_la_clave_se_normaliza_y_conserva_el_valor_original():
    procesar_comando_memoria("recuerda que Mi Número de la Suerte es 7")
    assert hechos_en_disco() == {"numero de la suerte": "7"}
    assert "7" in procesar_comando_memoria("¿cuál es mi número de la suerte?")
    assert "7" in procesar_comando_memoria("¿Cuál es MI NÚMERO DE LA SUERTE?")


# --------------------------------------------------------------------------- nunca se aprende en silencio
NO_COMANDOS = [
    # conversación normal (antes de la fase 7 TODO esto modificaba el perfil)
    "hola",
    "mi furgoneta es una camper",
    "tengo treinta años y vivo en Bilbao",
    "me gusta la montaña",
    "la capital de Francia es París",
    # preguntas normales (no son consultas de memoria)
    "¿puedes recordar cosas?",
    "¿cómo funciona tu memoria?",
    "recuerda que mi coche es rojo?",      # con '?' es una pregunta, no una orden
    "¿mi furgoneta es una camper?",
    "what can you remember?",
    # negaciones de OTRAS cosas (las de memoria tienen respuesta local: ver test_negaciones_*)
    "no quiero cambiar a modo online",
    "no me gusta el frío",
    # ejemplos entrecomillados que NO son peticiones de memoria (los que lo son: test_cita_reconocible_*)
    '"hola"',
    "«pasa a modo online»",
    # comando incrustado en otra frase
    "Explica qué significa 'recuerda que X es Y'",
    "cuando te diga recuerda que algo es algo, ¿qué harás?",
    "me gustaría que algún día recuerdes mis gustos",
    "antes de olvidar mi coche dime la hora",
    # verbos genéricos sin objeto de memoria: comandos normales, no peticiones de memoria
    "guarda silencio",
    "save the whales",
    "nota mucho frío hoy",
    "guarda que mi talla es 44",
    "apunta que mi talla es 44",
    "anota que la furgoneta es una camper",
    "anota mi talla: 44",
    "graba esto: mi furgoneta es una camper",
    "toma nota: la furgoneta es una camper",
    "save that my van is a camper",
    "note down that my van is a camper",
    "save my size: 44",
    "set my size to 44",
    "note that my size is 44",
    "actualiza mi coche a azul",
    "cambia mi coche por una moto",
    "update my car to blue",
    "set car to blue",
    "borra mi coche",
    "elimina el coche",
    "delete my car",
    "remove the car",
    "borra el historial",
]


@pytest.mark.parametrize("frase", NO_COMANDOS)
def test_mensajes_normales_no_son_comandos_ni_escriben(frase):
    assert procesar_comando_memoria(frase) is None
    assert not os.path.exists(memoria.FACTS_PATH)   # ni siquiera se crea el fichero


@pytest.mark.parametrize("frase", [
    '"recuerda que mi coche es rojo"',
    "'olvida mi coche'",
    "«recuerda que mi coche es rojo»",
    "<<forget my car>>",
    "«¿qué recuerdas?»",
    "'actualiza en tu memoria coche a azul'",
])
def test_cita_reconocible_se_rechaza_localmente_sin_tocar_la_memoria(frase):
    procesar_comando_memoria("recuerda que mi coche es azul")
    r = procesar_comando_memoria(frase)
    assert r is not None and ("comillas" in r or "quotes" in r)
    assert hechos_en_disco() == {"coche": "azul"}


def test_la_consulta_no_crea_el_fichero():
    assert "No tengo nada guardado" in procesar_comando_memoria("¿qué sabes de mi coche?")
    procesar_comando_memoria("¿qué recuerdas?")
    assert not os.path.exists(memoria.FACTS_PATH)


# --------------------------------------------------------------------------- duplicados, conflictos y ambigüedad
def test_duplicado_no_reescribe_y_lo_dice():
    procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    antes = _almacen_temporal_bytes()
    r = procesar_comando_memoria("recuerda que el gato se llama mishi")  # mismo hecho, otra forma
    assert "Ya lo tenía guardado" in r
    assert _almacen_temporal_bytes() == antes


def test_conflicto_no_sobreescribe_y_pide_actualizar():
    procesar_comando_memoria("recuerda que mi coche es rojo")
    r = procesar_comando_memoria("recuerda que mi coche es azul")
    assert "rojo" in r and "recuerda que ahora coche es azul" in r
    assert hechos_en_disco() == {"coche": "rojo"}          # intacto
    assert procesar_comando_memoria("actualiza mi coche a azul") is None   # genérico: no toca nada
    assert hechos_en_disco() == {"coche": "rojo"}
    r2 = procesar_comando_memoria("recuerda que ahora mi coche es azul")
    assert "azul" in r2 and "rojo" in r2
    assert hechos_en_disco() == {"coche": "azul"}


def test_conflicto_no_afecta_a_hechos_no_relacionados():
    procesar_comando_memoria("recuerda que mi coche es rojo")
    procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    procesar_comando_memoria("recuerda que mi coche es azul")      # conflicto
    procesar_comando_memoria("actualiza en tu memoria mi coche a verde")
    procesar_comando_memoria("olvida mi gato")
    assert hechos_en_disco() == {"coche": "verde"}                 # sólo lo pedido


def test_recordar_con_ahora_es_una_actualizacion_explicita():
    procesar_comando_memoria("recuerda que mi coche es rojo")
    r = procesar_comando_memoria("recuerda que ahora mi coche es azul")
    assert "azul" in r and hechos_en_disco() == {"coche": "azul"}


@pytest.mark.parametrize("frase,pista", [
    ("recuerda que sí", "recuerda que"),
    ("recuerda esto", "recuerda que"),
    ("remember that", "remember that"),
    ("memoriza que mañana llueve mucho", "recuerda que"),    # sin pareja clave/valor clara
    ("recuerda que 'mi coche es rojo'", "comillas"),         # hecho citado: aclarar, no adivinar
    ("olvida «mi coche»", "comillas"),
    ("actualiza en tu memoria 'coche' a 'azul'", "comillas"),
    ("actualiza", None),
    ("olvida eso", "olvida"),
    ("forget it", "forget"),
])
def test_ambiguedad_pide_aclaracion_y_no_escribe(frase, pista):
    r = procesar_comando_memoria(frase)
    if pista is None:
        assert r is None
    else:
        assert r is not None and pista in r
    assert not os.path.exists(memoria.FACTS_PATH)


# --------------------------------------------------------------------------- consultar
def test_consultas_variantes():
    procesar_comando_memoria("recuerda que mi furgoneta es una camper")
    for frase in ("¿qué sabes de mi furgoneta?", "¿qué recuerdas sobre la furgoneta?",
                  "¿recuerdas mi furgoneta?", "¿te acuerdas de mi furgoneta?", "¿no te acuerdas de mi furgoneta?",
                  "dime qué sabes de mi furgoneta", "¿cuál es mi furgoneta?",
                  "¿recuerdas cuál es mi furgoneta?"):
        r = procesar_comando_memoria(frase)
        assert r is not None and "una camper" in r, frase


def test_consultas_variantes_en():
    procesar_comando_memoria("remember that my van is a camper")
    for frase in ("what do you know about my van?", "what is my van?",
                  "do you remember my van?", "what do you remember about my van?"):
        r = procesar_comando_memoria(frase)
        assert r is not None and "a camper" in r, frase


def test_confirmar_o_desmentir_un_hecho_sin_guardarlo():
    procesar_comando_memoria("recuerda que mi coche es rojo")
    assert procesar_comando_memoria("¿recuerdas que mi coche es rojo?").startswith("Sí")
    r = procesar_comando_memoria("¿recuerdas que mi coche es azul?")
    assert "No exactamente" in r and "rojo" in r
    assert hechos_en_disco() == {"coche": "rojo"}                  # la pregunta no escribió nada
    assert "No tengo nada guardado" in procesar_comando_memoria("¿recuerdas que mi moto es negra?")


def test_listar_y_memoria_vacia():
    assert "ningún hecho" in procesar_comando_memoria("¿qué recuerdas?")
    procesar_comando_memoria("recuerda que mi coche es rojo")
    procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    r = procesar_comando_memoria("lista tus hechos")
    assert "2" in r and "- coche: rojo" in r and "- gato: Mishi" in r
    assert "coche: rojo" in procesar_comando_memoria("show your facts")


def test_consulta_desconocida_y_parecidos():
    procesar_comando_memoria("recuerda que mi color favorito es el azul")
    assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi talla?")
    r = procesar_comando_memoria("¿qué sabes de mi color?")            # coincidencia parcial: sólo sugerencia
    assert "'color favorito'" in r and "Quizá" in r and "el azul" not in r and "Sí" not in r
    assert "el azul" in procesar_comando_memoria("¿qué sabes de mi color favorito?")


# --------------------------------------------------------------------------- olvidar
def test_olvidar_variantes():
    for frase in ("olvida mi coche", "olvídate de mi coche", "olvida el hecho coche",
                  "borra de tu memoria el coche", "elimina el hecho coche", "borra mi coche de tu memoria",
                  "ya no recuerdes mi coche", "deja de recordar mi coche",
                  "forget my coche", "delete the fact coche", "remove my coche from your memory"):
        procesar_comando_memoria("recuerda que mi coche es rojo")
        r = procesar_comando_memoria(frase)
        assert r is not None and ("Olvidado" in r or "Forgotten" in r), frase
        assert hechos_en_disco() == {}, frase


def test_olvidar_con_valor_en_conflicto_pide_confirmacion():
    procesar_comando_memoria("recuerda que mi coche es rojo")
    r = procesar_comando_memoria("olvida que mi coche es azul")
    assert "rojo" in r and "olvida coche" in r
    assert hechos_en_disco() == {"coche": "rojo"}                  # no se borró
    assert "Olvidado" in procesar_comando_memoria("olvida que mi coche es rojo")
    assert hechos_en_disco() == {}


def test_olvidar_inexistente_y_sugerencias():
    assert "No tenía nada guardado" in procesar_comando_memoria("olvida mi moto")
    procesar_comando_memoria("recuerda que mi color favorito es el azul")
    r = procesar_comando_memoria("olvida mi color")
    assert "color favorito" in r                                    # sugiere, no borra a ciegas
    assert hechos_en_disco() == {"color favorito": "el azul"}


def test_olvidar_todo_requiere_confirmacion_explicita():
    procesar_comando_memoria("recuerda que mi coche es rojo")
    procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    r = procesar_comando_memoria("olvida todo")
    assert "confirmo" in r and hechos_en_disco() == {"coche": "rojo", "gato": "Mishi"}
    assert "2" in procesar_comando_memoria("olvida todo, confirmo")
    assert hechos_en_disco() == {}
    assert "No había" in procesar_comando_memoria("olvida todo")


def test_forget_everything_en():
    procesar_comando_memoria("remember that my van is a camper")
    assert "confirm" in procesar_comando_memoria("forget everything")
    assert hechos_en_disco() == {"van": "a camper"}
    procesar_comando_memoria("forget everything, confirm")
    assert hechos_en_disco() == {}


# --------------------------------------------------------------------------- robustez del almacén
def test_fichero_danado_no_se_toca_y_se_informa(_almacen_temporal):
    _almacen_temporal.hechos.write_text("[esto, no, es, un, almacen]", encoding="utf-8")
    antes = _almacen_temporal.hechos.read_bytes()
    for frase in ("recuerda que mi coche es rojo", "¿qué recuerdas?", "olvida mi coche",
                  "recuerda que ahora mi coche es azul", "olvida todo, confirmo"):
        r = procesar_comando_memoria(frase)
        assert r is not None and "dañado" in r, frase
    assert _almacen_temporal.hechos.read_bytes() == antes          # ni un byte cambiado


def test_yaml_ilegible_tambien_se_preserva(_almacen_temporal):
    _almacen_temporal.hechos.write_text("hechos: {rota: [", encoding="utf-8")
    antes = _almacen_temporal.hechos.read_bytes()
    assert "dañado" in procesar_comando_memoria("recuerda que mi coche es rojo")
    assert _almacen_temporal.hechos.read_bytes() == antes


def test_fallo_de_escritura_no_confirma_ni_destruye(_almacen_temporal):
    procesar_comando_memoria("recuerda que mi coche es rojo")
    antes = _almacen_temporal.hechos.read_bytes()

    def explota(*a, **kw):
        raise OSError("disco lleno (simulado)")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", explota)
        r = procesar_comando_memoria("recuerda que mi gato se llama Mishi")
        assert "No he podido guardar" in r and "intacta" in r      # sin éxito falso
        r2 = procesar_comando_memoria("olvida mi coche")
        assert "No he podido guardar" in r2
    assert _almacen_temporal.hechos.read_bytes() == antes          # datos previos intactos
    assert hechos_en_disco() == {"coche": "rojo"}
    restos = [f for f in os.listdir(_almacen_temporal.dir) if f.startswith(".facts-")]
    assert restos == []                                            # el temporal se limpia


def test_exito_solo_tras_escribir(monkeypatch):
    """La confirmación sale DESPUÉS de persistir: si guardar_hechos falla, no hay confirmación."""
    llamadas = []
    original = memoria.guardar_hechos

    def espia(hechos):
        llamadas.append(dict(hechos))
        return original(hechos)

    monkeypatch.setattr(memoria, "guardar_hechos", espia)
    r = procesar_comando_memoria("recuerda que mi coche es rojo")
    assert "Hecho guardado" in r and len(llamadas) == 1
    assert hechos_en_disco() == {"coche": "rojo"}


# --------------------------------------------------------------------------- contexto para los motores
def test_los_hechos_llegan_al_contexto_y_desaparecen_al_olvidar():
    procesar_comando_memoria("recuerda que mi furgoneta es una camper")
    contexto = memoria.get_memory_context()
    assert "furgoneta: una camper" in contexto
    procesar_comando_memoria("olvida mi furgoneta")
    assert "furgoneta" not in memoria.get_memory_context()         # olvidado = no inyectado


def test_contexto_sobrevive_a_ficheros_danados(_almacen_temporal, capsys):
    _almacen_temporal.hechos.write_text("- lista - rota", encoding="utf-8")
    _almacen_temporal.perfil.write_text("{rota: [", encoding="utf-8")
    contexto = memoria.get_memory_context()                        # no lanza
    assert isinstance(contexto, str)
    salida = capsys.readouterr().out
    assert "Aviso" in salida


def test_contexto_sin_ficheros():
    os.unlink(memoria.MEMORY_PATH)
    assert memoria.get_memory_context() == ""


# --------------------------------------------------------------------------- integración con ai_engine
@pytest.fixture
def motor_controlado(ai_engine_aislado, selector_fake, monkeypatch):
    """ai_engine con selector fake y la memoria real (en tmp_path) como contexto."""
    monkeypatch.setattr(ai_engine_aislado, "get_memory_context", memoria.get_memory_context)
    sel = selector_fake.crear(config_base("offline"))
    ai_engine_aislado.set_selector(sel)
    return ai_engine_aislado, sel, selector_fake


def test_comando_de_memoria_es_local_sin_motores_ni_red(motor_controlado):
    ai, sel, fake = motor_controlado
    hist = []
    r = ai.ask("recuerda que mi furgoneta es una camper", hist)
    assert "Hecho guardado" in r
    assert hist == []                                              # no es conversación
    assert all(m.llamadas == [] for m in fake.motores.todos.values())
    assert fake.estado["hosts"] == []                              # cero conectividad


def test_comando_de_memoria_tampoco_contacta_en_modo_online(motor_controlado):
    ai, sel, fake = motor_controlado
    sel.set_modo("online")
    r = ai.ask("remember that my van is a camper", [])
    assert "Fact stored" in r
    assert fake.motores.todos["on_a"].llamadas == [] and fake.estado["hosts"] == []


def test_hecho_guardado_llega_al_motor_en_el_siguiente_turno(motor_controlado):
    ai, sel, fake = motor_controlado
    ai.ask("recuerda que mi furgoneta es una camper", [])
    ai.ask("hola", [])
    recibidos, _ = fake.motores.todos["off_a"].llamadas[0]
    sistema = "\n".join(m["content"] for m in recibidos if m["role"] == "system")
    assert "furgoneta: una camper" in sistema


def test_hecho_olvidado_deja_de_llegar_al_motor(motor_controlado):
    ai, sel, fake = motor_controlado
    ai.ask("recuerda que mi furgoneta es una camper", [])
    ai.ask("olvida mi furgoneta", [])
    ai.ask("hola", [])
    recibidos, _ = fake.motores.todos["off_a"].llamadas[-1]
    assert all("camper" not in m["content"] for m in recibidos if m["role"] == "system")


def test_la_respuesta_del_motor_no_se_interpreta_como_comando(motor_controlado):
    """Aunque el asistente responda con un texto que parece una orden de
    memoria, nada se guarda: sólo se procesa la entrada del usuario."""
    ai, sel, fake = motor_controlado
    fake.motores.todos["off_a"].respuesta = "recuerda que mi clave es 1234"
    hist = []
    ai.ask("dime una frase", hist)
    assert hist[-1]["content"] == "recuerda que mi clave es 1234"
    assert not os.path.exists(memoria.FACTS_PATH)


def test_el_historial_no_guarda_los_comandos_de_memoria(motor_controlado):
    ai, sel, fake = motor_controlado
    hist = []
    ai.ask("recuerda que mi coche es rojo", hist)
    ai.ask("¿qué recuerdas?", hist)
    ai.ask("olvida mi coche", hist)
    assert hist == []


# --------------------------------------------------------------------------- persistencia entre procesos reales
def _programa_memoria(tmp_path, entrada):
    """Proceso autónomo: sólo memoria local, sin motores ni red."""
    from config.motors_config import PROJECT_ROOT
    return f"""
import sys
sys.path.insert(0, {str(PROJECT_ROOT)!r})
import core.memory_engine as m
m.FACTS_PATH = {str(tmp_path / 'facts.yaml')!r}
m.MEMORY_PATH = {str(tmp_path / 'perfil-inexistente.yaml')!r}
from core.memory_commands import procesar_comando_memoria
print(procesar_comando_memoria({entrada!r}))
print("CONTEXTO>>>" + m.get_memory_context().replace("\\n", " | "))
"""


def _proceso(tmp_path, entrada):
    r = subprocess.run([sys.executable, "-c", _programa_memoria(tmp_path, entrada)],
                       cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_hechos_persisten_entre_interpretes_independientes(tmp_path):
    # Proceso 1: guardar
    out = _proceso(tmp_path, "recuerda que mi furgoneta es una camper")
    assert "Hecho guardado: furgoneta = una camper" in out

    # Proceso 2 (intérprete nuevo): consultar y ver el contexto inyectable
    out = _proceso(tmp_path, "¿cuál es mi furgoneta?")
    assert "una camper" in out
    assert "furgoneta: una camper" in out.split("CONTEXTO>>>")[1]

    # Proceso 3: olvidar
    out = _proceso(tmp_path, "olvida mi furgoneta")
    assert "Olvidado: furgoneta" in out

    # Proceso 4: ya no existe ni se inyecta como contexto
    out = _proceso(tmp_path, "¿qué recuerdas?")
    assert "ningún hecho" in out
    assert "furgoneta" not in out.split("CONTEXTO>>>")[1]


# =========================================================================== intención explícita
@pytest.mark.parametrize("frase", [
    "guarda que mi talla es 44", "graba esto: mi talla es 44", "anota mi talla: 44",
    "registra que mi talla es 44", "save that my size is 44", "store my size: 44",
    "note down that my size is 44", "write down my size is 44", "keep my size at 44",
    "actualiza mi talla a 44", "cambia la talla por 44", "set size to 44", "update size to 44",
    "borra la talla", "elimina mi talla", "quita la talla", "delete my size", "remove size", "erase size",
])
def test_comando_generico_sin_objeto_de_memoria_no_toca_la_memoria(frase):
    procesar_comando_memoria("recuerda que mi talla es 42")
    assert procesar_comando_memoria(frase) is None
    assert hechos_en_disco() == {"talla": "42"}            # ni guarda, ni cambia, ni borra


def test_objeto_de_memoria_no_cambia_la_propiedad():
    """'guarda en TU memoria que MI talla...' afecta al hecho del usuario (talla), no a 'tu talla'."""
    procesar_comando_memoria("recuerda que mi talla es 42")
    r = procesar_comando_memoria("guarda en tu memoria que mi talla es 44")
    assert "42" in r and "recuerda que ahora talla es 44" in r   # conflicto sobre la MISMA clave
    assert hechos_en_disco() == {"talla": "42"}


# =========================================================================== negaciones
@pytest.mark.parametrize("frase", [
    "no recuerdes que mi clave es 1234",
    "nunca guardes que mi clave es 1234",
    "no memorices mi clave",
    "no quiero que recuerdes nada de esto: mi clave es 1234",
    "don't store my password",
    "do not remember that my pin is 1234",
    "never save my pin: 1234",
    "I don't want you to remember my pin",
])
def test_negacion_de_peticion_se_contesta_localmente_sin_escribir(frase):
    r = procesar_comando_memoria(frase)
    assert r is not None and ("no guardaré" in r or "won't store" in r)
    assert not os.path.exists(memoria.FACTS_PATH)


def test_negacion_sobre_hecho_existente_lo_menciona_sin_borrarlo():
    procesar_comando_memoria("recuerda que mi clave es 1234")
    r = procesar_comando_memoria("no recuerdes mi clave")
    assert "1234" in r and "olvida clave" in r
    assert hechos_en_disco() == {"clave": "1234"}


@pytest.mark.parametrize("frase", [
    "recuerda que mi coche no es rojo",
    "recuerda que mi coche ya no es rojo",
    "recuerda que mi gato no se llama Mishi",
    "recuerda que nunca es tarde",
    "remember that my car isn't red",
    "remember that my car is not red",
    "remember my car is no longer red",
    "recuerda que ahora mi coche no es rojo",
    "olvida que mi coche no es rojo",
    "actualiza en tu memoria: mi coche no es rojo",
])
def test_hecho_negado_pide_aclaracion_y_nunca_guarda_el_valor_equivocado(frase):
    procesar_comando_memoria("recuerda que mi coche es azul")
    r = procesar_comando_memoria(frase)
    assert r is not None and ("negación" in r or "negation" in r)
    assert hechos_en_disco() == {"coche": "azul"}          # sin 'coche no' ni 'no es rojo'


def test_pregunta_negativa_es_una_consulta():
    procesar_comando_memoria("recuerda que mi coche es azul")
    assert "azul" in procesar_comando_memoria("¿no te acuerdas de mi coche?")
    assert "azul" in procesar_comando_memoria("don't you remember my coche?")
    assert procesar_comando_memoria("¿recuerdas que mi coche no es rojo?") is not None
    assert hechos_en_disco() == {"coche": "azul"}


# =========================================================================== propiedad y claves compuestas
def test_propiedad_ajena_no_se_mezcla_con_los_hechos_del_usuario():
    procesar_comando_memoria("recuerda que mi coche es rojo")
    procesar_comando_memoria("recuerda que tu coche es virtual")
    procesar_comando_memoria("recuerda que el coche de Ana es blanco")
    procesar_comando_memoria("recuerda que el coche de mi hermano es gris")
    procesar_comando_memoria("remember that Ana's car is white")
    assert hechos_en_disco() == {"coche": "rojo", "tu coche": "virtual", "coche de ana": "blanco",
                                 "coche de mi hermano": "gris", "ana's car": "white"}
    assert "coche es rojo" in procesar_comando_memoria("¿cuál es mi coche?")
    assert "Olvidado: coche " in procesar_comando_memoria("olvida mi coche")
    # sin el hecho del usuario, la búsqueda parcial no salta a coches ajenos
    assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi coche?")
    assert "No tenía nada guardado" in procesar_comando_memoria("olvida mi coche")
    assert hechos_en_disco() == {"tu coche": "virtual", "coche de ana": "blanco",
                                 "coche de mi hermano": "gris", "ana's car": "white"}


def test_clave_compuesta_del_usuario_se_encuentra_por_fragmento():
    procesar_comando_memoria("recuerda que mi número de la suerte es 7")
    procesar_comando_memoria("recuerda que mi número de teléfono es 600")
    assert "7" in procesar_comando_memoria("¿cuál es mi número de la suerte?")
    r = procesar_comando_memoria("¿cuál es mi número?")           # ambiguo: dos candidatos
    assert "número de la suerte" in r and "número de teléfono" in r
    r = procesar_comando_memoria("olvida mi número")               # ambiguo: no borra a ciegas
    assert "Quizá" in r and hechos_en_disco() == {"numero de la suerte": "7", "numero de telefono": "600"}


def test_varios_hechos_en_una_peticion():
    r = procesar_comando_memoria("recuerda que mi gato se llama Mishi y mi perro se llama Rex")
    assert "gato = Mishi" in r and "perro = Rex" in r
    assert hechos_en_disco() == {"gato": "Mishi", "perro": "Rex"}
    # un conflicto en uno no impide los demás ni toca datos no relacionados
    r = procesar_comando_memoria("remember that my cat is Tom and my gato is Garfield, and my bird is Piolín")
    assert "cat = Tom" in r and "bird = Piolín" in r and "Mishi" in r
    assert hechos_en_disco() == {"gato": "Mishi", "perro": "Rex", "cat": "Tom", "bird": "Piolín"}


def test_valor_con_conjuncion_no_se_parte():
    procesar_comando_memoria("recuerda que mi color favorito es el blanco y negro")
    assert hechos_en_disco() == {"color favorito": "el blanco y negro"}


# =========================================================================== preguntas generales
@pytest.mark.parametrize("frase", ["¿qué sabes de Python?", "what do you know about Bilbao?",
                                   "¿cuál es la capital de Francia?", "what is the time?"])
def test_pregunta_general_va_al_modelo(frase):
    assert procesar_comando_memoria(frase) is None


# =========================================================================== esquema y lectura
@pytest.mark.parametrize("contenido,motivo", [
    ("version: 2\nhechos: {}\n", "versión"),
    ("hechos: {}\n", "versión"),
    ("version: '1'\nhechos: {}\n", "versión"),
    ("version: 1\nhechos: {}\nextra: 1\n", "esquema desconocido"),
    ("version: 1\nhechos: {coche: {clave: coche, valor: rojo, peso: 3}}\n", "campos desconocidos"),
    ("version: 1\nhechos: {coche: rojo}\n", "entrada inválida"),
    ("version: 1\nhechos: [a, b]\n", "diccionario"),
    ("- lista\n", "diccionario"),
])
def test_esquema_o_version_desconocidos_se_rechazan_sin_tocar_el_fichero(_almacen_temporal, contenido, motivo):
    _almacen_temporal.hechos.write_text(contenido, encoding="utf-8")
    antes = _almacen_temporal.hechos.read_bytes()
    with pytest.raises(memoria.MemoriaHechosInvalida, match=motivo):
        memoria.cargar_hechos()
    r = procesar_comando_memoria("recuerda que mi coche es rojo")
    assert "dañado" in r and "Hecho guardado" not in r
    assert _almacen_temporal.hechos.read_bytes() == antes
    assert "furgoneta" not in memoria.get_memory_context()    # tampoco se inyecta nada raro


def test_fichero_vacio_es_un_almacen_vacio(_almacen_temporal):
    _almacen_temporal.hechos.write_text("", encoding="utf-8")
    assert memoria.cargar_hechos() == {}
    assert "Hecho guardado" in procesar_comando_memoria("recuerda que mi coche es rojo")


def test_error_de_lectura_se_informa_sin_escribir(_almacen_temporal, monkeypatch):
    procesar_comando_memoria("recuerda que mi coche es rojo")
    antes = _almacen_temporal.hechos.read_bytes()
    real_open = open

    def abrir(ruta, *a, **kw):
        if str(ruta) == str(memoria.FACTS_PATH) and (not a or "r" in a[0]):
            raise PermissionError("permiso denegado (simulado)")
        return real_open(ruta, *a, **kw)

    monkeypatch.setattr("builtins.open", abrir)
    r = procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    assert "No puedo leer" in r and "permiso denegado" in r
    assert "No he modificado nada" in r
    assert isinstance(memoria.get_memory_context(), str)     # el turno normal no se rompe
    monkeypatch.setattr("builtins.open", real_open)
    assert _almacen_temporal.hechos.read_bytes() == antes


# =========================================================================== migración del perfil heredado
PERFIL_LEGADO = {
    "aprendido_durante_sesion": {"furgoneta": "una camper", "color favorito": "azul"},
    "vida_personal": {"vehiculo": "camper", "pareja": {"nombre": "Ana"}},
    "nombre": "Jon",
    "gustos": {"ilustracion_personalizada": ["pixar", "funko"]},
    "entorno": {"configuracion": {"dockerizado": True}},
}


def escribir_perfil(almacen, datos=PERFIL_LEGADO):
    almacen.perfil.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


def test_migracion_del_perfil_sin_perdida(_almacen_temporal, capsys):
    escribir_perfil(_almacen_temporal)
    original = _almacen_temporal.perfil.read_bytes()
    n = memoria.migrar_perfil_legado()
    assert n == 7
    assert hechos_en_disco() == {
        "furgoneta": "una camper", "color favorito": "azul", "vehiculo": "camper",
        "pareja nombre": "Ana", "nombre": "Jon", "ilustracion personalizada": "pixar, funko",
        "configuracion dockerizado": "sí"}
    # copia de seguridad byte a byte y perfil vaciado (ya no se inyecta dos veces)
    copias = list(_almacen_temporal.dir.glob("user_profile.yaml.legado-*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == original
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}
    assert "migrada" in capsys.readouterr().out
    # idempotente
    assert memoria.migrar_perfil_legado() == 0
    assert len(list(_almacen_temporal.dir.glob("user_profile.yaml.legado-*.bak"))) == 1


def test_memoria_heredada_es_consultable_editable_y_olvidable(_almacen_temporal):
    escribir_perfil(_almacen_temporal)
    # la migración se dispara sola en el primer uso de la memoria
    assert "una camper" in procesar_comando_memoria("¿cuál es mi furgoneta?")
    assert "'pareja nombre'" in procesar_comando_memoria("¿qué recuerdas de mi pareja?")   # sugerencia
    assert "Ana" in procesar_comando_memoria("¿qué recuerdas de mi pareja nombre?")
    assert "Actualizado" in procesar_comando_memoria("recuerda que ahora mi furgoneta es un monovolumen")
    assert "Olvidado" in procesar_comando_memoria("olvida mi color favorito")
    contexto = memoria.get_memory_context()
    assert "furgoneta: un monovolumen" in contexto and "pareja nombre: Ana" in contexto
    assert "azul" not in contexto and "una camper" not in contexto   # lo olvidado/actualizado no vuelve


def test_migracion_se_dispara_al_construir_el_contexto(_almacen_temporal):
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"gato": "Mishi"}})
    contexto = memoria.get_memory_context()
    assert contexto.count("Mishi") == 1 and "- gato: Mishi" in contexto
    assert hechos_en_disco() == {"gato": "Mishi"}


def test_migracion_no_sobreescribe_hechos_nuevos_en_conflicto(_almacen_temporal):
    procesar_comando_memoria("recuerda que mi furgoneta es una autocaravana")
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"furgoneta": "una camper", "gato": "Mishi"}})
    memoria.migrar_perfil_legado()
    assert hechos_en_disco() == {"furgoneta": "una autocaravana", "gato": "Mishi",
                                 "furgoneta (perfil anterior)": "una camper"}


def test_migracion_no_toca_el_perfil_si_la_memoria_esta_danada(_almacen_temporal, capsys):
    escribir_perfil(_almacen_temporal)
    original = _almacen_temporal.perfil.read_bytes()
    _almacen_temporal.hechos.write_text("version: 9\n", encoding="utf-8")
    assert memoria.migrar_perfil_legado() == 0
    assert _almacen_temporal.perfil.read_bytes() == original
    assert not list(_almacen_temporal.dir.glob("*.bak"))
    assert "no migro" in capsys.readouterr().out
    # y mientras tanto el perfil sigue llegando al contexto (no se oculta ningún dato)
    assert "una camper" in memoria.get_memory_context()


def test_migracion_con_fallo_de_escritura_deja_el_perfil_intacto(_almacen_temporal, capsys):
    escribir_perfil(_almacen_temporal)
    original = _almacen_temporal.perfil.read_bytes()

    def explota(*a, **kw):
        raise OSError("disco lleno (simulado)")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", explota)
        assert memoria.migrar_perfil_legado() == 0
    assert _almacen_temporal.perfil.read_bytes() == original
    assert not os.path.exists(memoria.FACTS_PATH)
    assert "no he podido migrar" in capsys.readouterr().out
    # al siguiente intento (sin fallo) se migra
    assert memoria.migrar_perfil_legado() == 7


def test_perfil_ilegible_no_se_migra_ni_rompe(_almacen_temporal, capsys):
    _almacen_temporal.perfil.write_text("{rota: [", encoding="utf-8")
    antes = _almacen_temporal.perfil.read_bytes()
    assert memoria.migrar_perfil_legado() == 0
    assert "Hecho guardado" in procesar_comando_memoria("recuerda que mi coche es rojo")
    assert _almacen_temporal.perfil.read_bytes() == antes


def test_migracion_entre_procesos_reales(tmp_path):
    """Perfil heredado escrito 'por otra versión' -> un intérprete nuevo lo migra y otro lo olvida."""
    perfil = tmp_path / "perfil-inexistente.yaml"   # ruta que usa _programa_memoria
    perfil.write_text(yaml.safe_dump({"aprendido_durante_sesion": {"furgoneta": "una camper"}}), encoding="utf-8")
    out = _proceso(tmp_path, "¿cuál es mi furgoneta?")
    assert "una camper" in out and "migrada" in out
    out = _proceso(tmp_path, "olvida mi furgoneta")
    assert "Olvidado" in out
    out = _proceso(tmp_path, "¿qué recuerdas?")
    assert "furgoneta" not in out.split("CONTEXTO>>>")[1] and "ningún hecho" in out
    assert list(tmp_path.glob("perfil-inexistente.yaml.legado-*.bak"))


# =========================================================================== prefijo online:
def test_prefijo_online_no_saca_la_memoria_del_equipo(motor_controlado):
    ai, sel, fake = motor_controlado
    hist = []
    # modo offline: se resuelve localmente (no se rechaza ni se contacta)
    r = ai.ask("online: recuerda que mi furgoneta es una camper", hist)
    assert "Hecho guardado" in r and "OFFLINE" not in r
    # modo online: tampoco se usa el motor online ni se comprueba la conexión
    sel.set_modo("online")
    r = ai.ask("online: ¿cuál es mi furgoneta?", hist)
    assert "una camper" in r
    r = ai.ask("en línea: olvida mi furgoneta", hist)
    assert "Olvidado" in r
    assert fake.motores.todos["on_a"].llamadas == [] and fake.estado["hosts"] == []
    assert hist == [] and hechos_en_disco() == {}
    # un mensaje normal con prefijo sí va al motor online (comportamiento previo intacto)
    ai.ask("online: hola", hist)
    assert len(fake.motores.todos["on_a"].llamadas) == 1


# =========================================================================== integridad: clave completa antes de mutar
@pytest.fixture
def viajes():
    procesar_comando_memoria("recuerda que mi viaje es en mayo")
    procesar_comando_memoria("recuerda que mi viaje a Roma es en junio")
    assert hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": "en junio"}


def test_actualizar_la_clave_larga_nunca_cambia_la_corta(viajes):
    assert "Actualizado: viaje a Roma = julio" in procesar_comando_memoria("recuerda que ahora mi viaje a Roma es julio")
    assert "Actualizado: viaje a Roma = agosto" in procesar_comando_memoria("actualiza en tu memoria mi viaje a Roma: agosto")
    assert "Updated: viaje a Roma = September" in procesar_comando_memoria("update the fact viaje a Roma: September")
    assert hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": "September"}
    assert "Actualizado: viaje = abril" in procesar_comando_memoria("recuerda que ahora mi viaje es abril")
    assert hechos_en_disco() == {"viaje": "abril", "viaje a roma": "September"}


def test_division_ambigua_con_varias_claves_guardadas_pregunta(viajes):
    for frase in ("actualiza en tu memoria mi viaje a Roma a julio", "cambia el hecho viaje a Roma por julio",
                  "update the fact viaje a Roma to July"):
        r = procesar_comando_memoria(frase)
        assert "'viaje'" in r and "'viaje a Roma'" in r and ("clave completa" in r or "full key" in r), frase
        assert hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": "en junio"}, frase


def test_division_a_por_to_se_resuelve_con_la_clave_guardada():
    procesar_comando_memoria("recuerda que mi viaje a Roma es en junio")      # sólo la larga
    assert "viaje a Roma = julio" in procesar_comando_memoria("actualiza en tu memoria mi viaje a Roma a julio")
    assert hechos_en_disco() == {"viaje a roma": "julio"}
    procesar_comando_memoria("olvida mi viaje a Roma")
    procesar_comando_memoria("recuerda que mi viaje es en mayo")              # sólo la corta
    assert "viaje = Roma a julio" in procesar_comando_memoria("actualiza en tu memoria mi viaje a Roma a julio")
    assert hechos_en_disco() == {"viaje": "Roma a julio"}


def test_division_ambigua_sin_nada_guardado_pregunta_y_no_crea_nada():
    r = procesar_comando_memoria("actualiza en tu memoria mi ruta a casa a la del monte")
    assert "'ruta'" in r and "'ruta a casa'" in r
    assert not os.path.exists(memoria.FACTS_PATH)
    assert "ruta a casa = la del monte" in procesar_comando_memoria("actualiza en tu memoria mi ruta a casa: la del monte")


def test_olvidar_y_comparar_usan_la_clave_exacta(viajes):
    r = procesar_comando_memoria("olvida mi viaje a")                           # parcial: no borra
    assert "Quizá" in r and hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": "en junio"}
    assert "Sí: viaje a Roma es en junio" in procesar_comando_memoria("¿recuerdas que mi viaje a Roma es en junio?")
    assert "Sí: viaje es en mayo" in procesar_comando_memoria("¿recuerdas que mi viaje es en mayo?")
    assert "Olvidado: viaje a Roma" in procesar_comando_memoria("olvida que mi viaje a Roma es en junio")
    assert hechos_en_disco() == {"viaje": "en mayo"}
    assert "Olvidado: viaje " in procesar_comando_memoria("olvida mi viaje")
    assert hechos_en_disco() == {}


def test_valor_que_contiene_es_se_resuelve_con_la_clave_guardada():
    procesar_comando_memoria("recuerda que mi frase es lo que es")
    r = procesar_comando_memoria("recuerda que ahora mi frase es lo que es es lo que hay")
    assert "frase = lo que es es lo que hay" in r
    assert hechos_en_disco() == {"frase": "lo que es es lo que hay"}


# =========================================================================== contradicciones
@pytest.mark.parametrize("frase", [
    "recuerda que mi coche es rojo y olvida mi coche",
    "recuerda que mi coche es rojo pero no lo guardes",
    "recuerda que mi moto es roja y mi moto es negra",
    "olvida mi coche y recuerda que mi coche es verde",
    "remember that my car is red and forget it",
    "remember that my bike is red and my bike is black",
    "forget my car and remember that my car is green",
    "actualiza en tu memoria: mi coche es verde y olvida mi coche",
])
def test_peticion_contradictoria_se_rechaza_sin_cambiar_nada(frase):
    procesar_comando_memoria("recuerda que mi coche es azul")
    r = procesar_comando_memoria(frase)
    assert r is not None and ("contradice" in r or "contradicts" in r)
    assert hechos_en_disco() == {"coche": "azul"}


# =========================================================================== peticiones incompletas
@pytest.mark.parametrize("frase,pista", [
    ("recuerda", "recordar"), ("recuerda que", "recordar"), ("B.A.I, memoriza:", "recordar"),
    ("guarda en tu memoria", "recordar"), ("olvida", "olvidar"), ("olvídate de", "olvidar"),
    ("borra de tu memoria", "olvidar"), ("actualiza en tu memoria", "actualizar"),
    ("remember", "remember"), ("forget", "forget"), ("forget about", "forget"),
    ("update the fact", "update"), ("save to memory", "remember"),
])
def test_peticion_incompleta_se_aclara_localmente(frase, pista):
    r = procesar_comando_memoria(frase)
    assert r is not None and pista in r
    assert not os.path.exists(memoria.FACTS_PATH)


def test_peticion_incompleta_o_citada_nunca_invoca_un_motor(motor_controlado):
    ai, sel, fake = motor_controlado
    hist = []
    for frase in ("recuerda", "online: olvida", "online: remember that", '"recuerda que mi coche es rojo"',
                  "online: «olvida mi coche»", "recuerda que mi coche es rojo y olvida mi coche"):
        r = ai.ask(frase, hist)
        assert r is not None and "Ningún motor" not in r and "OFFLINE" not in r, frase
    sel.set_modo("online")
    for frase in ("online: recuerda", "online: forget", "online: actualiza en tu memoria mi viaje a Roma a julio"):
        r = ai.ask(frase, hist)
        assert r is not None and "respuesta de" not in r, frase
    assert all(m.llamadas == [] for m in fake.motores.todos.values())
    assert fake.estado["hosts"] == [] and hist == []
    assert not os.path.exists(memoria.FACTS_PATH)


def test_autorizacion_online_sigue_siendo_explicita(motor_controlado):
    """Lo local no relaja la política: un mensaje normal con prefijo online en modo offline se rechaza."""
    ai, sel, fake = motor_controlado
    r = ai.ask("online: hola", [])
    assert r.startswith("Estás en modo OFFLINE") and fake.estado["hosts"] == []
    assert fake.motores.todos["on_a"].llamadas == [] and sel.modo == "offline"


# =========================================================================== escritura multi-hecho atómica
def test_multi_hecho_fallo_de_escritura_no_deja_nada_a_medias(_almacen_temporal):
    procesar_comando_memoria("recuerda que mi coche es azul")
    antes = _almacen_temporal.hechos.read_bytes()

    def explota(*a, **kw):
        raise OSError("disco lleno (simulado)")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", explota)
        r = procesar_comando_memoria("recuerda que mi gato se llama Mishi y mi perro se llama Rex")
    assert "No he podido guardar" in r and "Hecho guardado" not in r
    assert _almacen_temporal.hechos.read_bytes() == antes
    assert hechos_en_disco() == {"coche": "azul"}


def test_multi_hecho_con_conflicto_una_sola_escritura_e_informe_exacto(monkeypatch):
    procesar_comando_memoria("recuerda que mi coche es azul")
    escrituras = []
    original = memoria.guardar_hechos
    monkeypatch.setattr(memoria, "guardar_hechos", lambda h, meta=None: (escrituras.append(dict(h)), original(h, meta)))
    r = procesar_comando_memoria("recuerda que mi coche es rojo y mi gato se llama Mishi y mi perro se llama Rex")
    lineas = r.splitlines()
    assert len(lineas) == 3
    assert "coche es azul" in lineas[0] and "No lo he sobreescrito" in lineas[0]
    assert lineas[1].startswith("Hecho guardado: gato = Mishi") and lineas[2].startswith("Hecho guardado: perro = Rex")
    assert len(escrituras) == 1
    assert hechos_en_disco() == {"coche": "azul", "gato": "Mishi", "perro": "Rex"}


def test_multi_hecho_sin_cambios_no_escribe():
    procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    antes = _almacen_temporal_bytes()
    r = procesar_comando_memoria("recuerda que mi gato se llama Mishi y mi gato se llama mishi")
    assert r.count("Ya lo tenía guardado") == 2
    assert _almacen_temporal_bytes() == antes


# =========================================================================== coincidencias parciales = sugerencias
def test_coincidencia_parcial_nunca_se_confirma_como_hecho():
    procesar_comando_memoria("recuerda que mi viaje a Roma es en junio")
    for frase in ("¿cuál es mi viaje?", "¿qué recuerdas de mi viaje?", "¿recuerdas mi viaje?", "what is my viaje?"):
        r = procesar_comando_memoria(frase)
        assert "'viaje a Roma'" in r and "en junio" not in r and not r.startswith(("Sí", "Yes")), frase
    assert "en junio" in procesar_comando_memoria("¿cuál es mi viaje a Roma?")


# =========================================================================== migración: sin reimportar lo olvidado
def test_migracion_con_vaciado_fallido_no_reimporta_lo_olvidado(_almacen_temporal, capsys):
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"furgoneta": "una camper", "gato": "Mishi"}})
    original = _almacen_temporal.perfil.read_bytes()
    real = memoria._escribir_atomico

    def fallo_solo_perfil(ruta, contenido, prefijo):
        if ruta == memoria.MEMORY_PATH:
            raise OSError("perfil de sólo lectura (simulado)")
        return real(ruta, contenido, prefijo)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(memoria, "_escribir_atomico", fallo_solo_perfil)
        assert memoria.migrar_perfil_legado() == 2
    assert "no he podido vaciarlo" in capsys.readouterr().out
    assert _almacen_temporal.perfil.read_bytes() == original             # el perfil sigue lleno
    assert hechos_en_disco() == {"furgoneta": "una camper", "gato": "Mishi"}
    # el usuario olvida un hecho heredado...
    assert "Olvidado" in procesar_comando_memoria("olvida mi furgoneta")
    # ...y ni el siguiente intento de migración ni un proceso "nuevo" lo resucitan
    assert memoria.migrar_perfil_legado() == 0
    assert hechos_en_disco() == {"gato": "Mishi"}
    assert "una camper" not in memoria.get_memory_context()
    # esta vez el vaciado funciona y la copia de seguridad sigue siendo única
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}
    assert len(list(_almacen_temporal.dir.glob("user_profile.yaml.legado-*.bak"))) == 1


def test_marca_de_migracion_sobrevive_a_las_operaciones(_almacen_temporal):
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"gato": "Mishi"}})
    memoria.migrar_perfil_legado()
    procesar_comando_memoria("recuerda que mi coche es rojo")
    procesar_comando_memoria("olvida mi gato")
    datos = yaml.safe_load(_almacen_temporal.hechos.read_text(encoding="utf-8"))
    assert isinstance(datos.get("perfil_migrado"), str) and len(datos["perfil_migrado"]) == 64
    # y un perfil modificado a mano después SÍ se importa (huella distinta)
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"perro": "Rex"}})
    assert memoria.migrar_perfil_legado() == 1
    assert hechos_en_disco() == {"coche": "rojo", "perro": "Rex"}


def test_marca_de_migracion_invalida_se_rechaza(_almacen_temporal):
    _almacen_temporal.hechos.write_text("version: 1\nhechos: {}\nperfil_migrado: 5\n", encoding="utf-8")
    with pytest.raises(memoria.MemoriaHechosInvalida, match="perfil_migrado"):
        memoria.cargar_hechos()
