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


def hechos_en_disco():
    if not os.path.exists(memoria.FACTS_PATH):
        return {}
    with open(memoria.FACTS_PATH, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return {clave: e["valor"] for clave, e in (datos.get("hechos") or {}).items()}


def bytes_en_disco():
    with open(memoria.FACTS_PATH, "rb") as f:
        return f.read()


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
    # ejemplos entrecomillados
    '"recuerda que mi coche es rojo"',
    "'olvida mi coche'",
    "«recuerda que mi coche es rojo»",
    "<<forget my car>>",
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
    "make a note of this: my van is a camper",   # variante positiva en la fase inicial; ahora genérica
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


def test_la_consulta_no_crea_el_fichero():
    assert "No tengo nada guardado" in procesar_comando_memoria("¿qué sabes de mi coche?")
    procesar_comando_memoria("¿qué recuerdas?")
    assert not os.path.exists(memoria.FACTS_PATH)


# --------------------------------------------------------------------------- duplicados, conflictos y ambigüedad
def test_duplicado_no_reescribe_y_lo_dice():
    procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    antes = bytes_en_disco()
    r = procesar_comando_memoria("recuerda que el gato se llama mishi")  # mismo hecho, otra forma
    assert "Ya lo tenía guardado" in r
    assert bytes_en_disco() == antes


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
    r = procesar_comando_memoria("¿qué sabes de mi color?")          # coincidencia parcial única
    assert "Quizá te refieres a: 'color favorito'" in r and "el azul" not in r   # sugerencia, no hecho confirmado
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
    r = procesar_comando_memoria("¿qué recuerdas de mi pareja?")     # parcial: sólo sugiere la clave
    assert "'pareja nombre'" in r and "Ana" not in r
    assert "Ana" in procesar_comando_memoria("¿qué recuerdas de pareja nombre?")
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


@pytest.mark.parametrize("frase,esperado", [
    ("recuerda que ahora mi viaje a Roma es en julio", "en julio"),
    ("actualiza en tu memoria viaje a Roma: en julio", "en julio"),
    ("corrige tu memoria: mi viaje a Roma es en julio", "en julio"),
    ("update the fact viaje a Roma: en julio", "en julio"),
    ("remember that now my viaje a Roma is en julio", "en julio"),
])
def test_actualizar_la_clave_larga_nunca_toca_la_corta(viajes, frase, esperado):
    r = procesar_comando_memoria(frase)
    assert "viaje a Roma" in r
    assert hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": esperado}


@pytest.mark.parametrize("frase", [
    "actualiza en tu memoria mi viaje a Roma a julio",     # 'a' dentro de la clave y como separador
    "cambia el hecho viaje a Roma por julio",
    "update the fact viaje a Roma to July",
])
def test_division_ambigua_pide_aclaracion_y_no_escribe(viajes, frase):
    antes = bytes_en_disco()
    r = procesar_comando_memoria(frase)
    assert "'viaje'" in r and "'viaje a Roma'" in r
    assert ("No está claro" in r) or ("not clear" in r)
    assert bytes_en_disco() == antes


def test_division_unica_sigue_funcionando(viajes):
    assert "Actualizado: viaje = marzo" in procesar_comando_memoria("actualiza en tu memoria mi viaje a marzo")
    assert hechos_en_disco() == {"viaje": "marzo", "viaje a roma": "en junio"}


@pytest.fixture
def planes():
    procesar_comando_memoria("recuerda que mi plan es descansar")
    procesar_comando_memoria("actualiza en tu memoria plan es viajar: sí")     # clave 'plan es viajar'
    assert hechos_en_disco() == {"plan": "descansar", "plan es viajar": "sí"}


def test_lectura_natural_ambigua_con_clave_guardada_se_aclara(planes):
    """Varias divisiones con 'es' y otra que la primera nombra un hecho guardado -> aclarar."""
    antes = bytes_en_disco()
    r = procesar_comando_memoria("recuerda que ahora mi plan es viajar es lo mejor")
    assert "No está claro" in r and "'plan'" in r and "'plan es viajar'" in r
    assert bytes_en_disco() == antes


def test_olvidar_sólo_la_clave_completa(viajes):
    assert "Olvidado: viaje a Roma" in procesar_comando_memoria("olvida mi viaje a Roma")
    assert hechos_en_disco() == {"viaje": "en mayo"}
    procesar_comando_memoria("recuerda que mi viaje a Roma es en junio")
    assert "Olvidado: viaje (era: en mayo)" in procesar_comando_memoria("olvida mi viaje")
    assert hechos_en_disco() == {"viaje a roma": "en junio"}


def test_olvidar_con_valor_resuelve_la_clave_completa(viajes):
    r = procesar_comando_memoria("olvida que mi viaje a Roma es en mayo")   # valor de 'viaje', clave de 'viaje a Roma'
    assert "en junio" in r and hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": "en junio"}
    assert "Olvidado" in procesar_comando_memoria("olvida que mi viaje a Roma es en junio")
    assert hechos_en_disco() == {"viaje": "en mayo"}


def test_recordar_la_clave_larga_no_choca_con_la_corta():
    procesar_comando_memoria("recuerda que mi viaje es en mayo")
    r = procesar_comando_memoria("recuerda que mi viaje a Roma es en junio")
    assert "Hecho guardado: viaje a Roma" in r
    r = procesar_comando_memoria("recuerda que mi viaje a Roma es en julio")   # conflicto SÓLO con la larga
    assert "viaje a Roma es en junio" in r
    assert hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": "en junio"}


# =========================================================================== citas, ejemplos y contradicciones
@pytest.mark.parametrize("frase", [
    "recuerda que mi lema es «menos es más»",
    'recuerda que mi coche es "rojo"',
    "recuerda que 'mi coche' es rojo",
    "remember that my car is “red”",
    "olvida que mi coche es 'rojo'",
    "actualiza en tu memoria mi coche: «azul»",
    "recuerda que mi lema es <<menos es más>>",
])
def test_citas_en_la_peticion_se_rechazan(frase):
    procesar_comando_memoria("recuerda que mi coche es rojo")
    r = procesar_comando_memoria(frase)
    assert "comillas" in r or "quotes" in r
    assert hechos_en_disco() == {"coche": "rojo"}


@pytest.mark.parametrize("frase", [
    "recuerda que por ejemplo mi coche es azul",
    "recuerda, por ejemplo, que mi coche es azul",
    "recuerda que p. ej. mi coche es azul",
    "remember that for example my car is blue",
    "remember that e.g. my car is blue",
    "olvida por ejemplo mi coche",
    "recuerda que ahora, supongamos, mi coche es azul",
])
def test_ejemplos_se_rechazan(frase):
    procesar_comando_memoria("recuerda que mi coche es rojo")
    r = procesar_comando_memoria(frase)
    assert r is not None and ("ejemplo" in r or "example" in r)
    assert hechos_en_disco() == {"coche": "rojo"}


def test_apostrofo_dentro_de_palabra_no_es_una_cita():
    assert "Fact stored: Ana's car = white" in procesar_comando_memoria("remember that Ana's car is white")


@pytest.mark.parametrize("frase", [
    "recuerda que mi moto es roja y olvídalo",
    "recuerda que mi moto es roja, no lo guardes",
    "recuerda que mi moto es roja pero no la recuerdes",
    "recuerda y olvida mi moto",
    "remember that my moto is red and forget it",
    "remember that my moto is red, don't save it",
    "olvida mi coche y recuerda que mi moto es roja",
    "olvida mi coche, guárdalo",
    "no recuerdes que mi moto es roja, recuérdalo",
    "recuerda que mi moto es roja y mi moto es azul",          # misma clave, dos valores
    "recuerda que mi gato se llama Tom y mi gato se llama Garfield",
])
def test_instrucciones_contradictorias_no_cambian_nada(frase):
    procesar_comando_memoria("recuerda que mi coche es rojo")
    antes = bytes_en_disco()
    r = procesar_comando_memoria(frase)
    assert r is not None and ("contradictorias" in r or "contradictory" in r)
    assert bytes_en_disco() == antes


def test_palabra_de_memoria_dentro_de_un_valor_no_es_contradiccion():
    assert "Hecho guardado" in procesar_comando_memoria("recuerda que mi canción es Remember the Name")
    assert hechos_en_disco() == {"cancion": "Remember the Name"}


def test_mismo_hecho_repetido_no_es_contradiccion():
    r = procesar_comando_memoria("recuerda que mi moto es roja y mi moto es roja")
    assert r.count("Hecho guardado") == 1 and hechos_en_disco() == {"moto": "roja"}


# =========================================================================== peticiones incompletas: siempre locales
@pytest.mark.parametrize("frase,pista", [
    ("recuerda", "recuerda que"), ("recuerda que", "recuerda que"), ("recuérdalo", "recuerda que"),
    ("memoriza esto", "recuerda que"), ("remember", "remember that"), ("remember this", "remember that"),
    ("guarda en tu memoria", "recuerda que"), ("save to memory", "remember that"),
    ("olvida", "olvida <clave>"), ("olvídalo", "olvida <clave>"), ("olvídate de eso", "olvida <clave>"),
    ("forget", "forget <key>"), ("borra de tu memoria", "olvida <clave>"), ("delete from memory", "forget <key>"),
    ("actualiza tu memoria", "recuerda que ahora"), ("update your memory", "remember that now"),
    ("¿recuerdas?", "¿cuál es mi"), ("¿te acuerdas?", "¿cuál es mi"), ("do you remember?", "what is my"),
    ("¿cuál es mi?", "¿cuál es mi"), ("¿qué sabes de?", "¿cuál es mi"),
])
def test_peticion_incompleta_se_aclara_localmente(frase, pista):
    r = procesar_comando_memoria(frase)
    assert r is not None and pista in r
    assert not os.path.exists(memoria.FACTS_PATH)


@pytest.mark.parametrize("frase", ["recuerda", "olvídalo", "¿recuerdas?", "borra de tu memoria",
                                   "recuerda que mi coche no es rojo", "recuerda que por ejemplo mi coche es rojo"])
@pytest.mark.parametrize("modo", ["offline", "online"])
def test_aclaraciones_nunca_invocan_un_motor_ni_con_prefijo_online(motor_controlado, frase, modo):
    ai, sel, fake = motor_controlado
    sel.set_modo(modo)
    hist = []
    for entrada in (frase, "online: " + frase, "en línea: " + frase):
        r = ai.ask(entrada, hist)
        assert r and "OFFLINE" not in r and "Ningún motor" not in r     # local: ni rechazo ni error de motor
    assert all(m.llamadas == [] for m in fake.motores.todos.values())
    assert fake.estado["hosts"] == [] and hist == []
    assert sel.modo == modo                                               # la autorización no cambia


def test_autorizacion_explicita_intacta_para_mensajes_normales(motor_controlado):
    ai, sel, fake = motor_controlado
    r = ai.ask("online: ¿qué tiempo hace?", [])
    assert r.startswith("Estás en modo OFFLINE")                          # sigue exigiendo autorización
    assert fake.motores.todos["on_a"].llamadas == [] and fake.estado["hosts"] == []
    assert sel.modo == "offline"


# =========================================================================== escrituras múltiples atómicas
def test_varios_hechos_se_escriben_en_una_sola_operacion(monkeypatch):
    escrituras = []
    original = memoria.guardar_hechos
    monkeypatch.setattr(memoria, "guardar_hechos", lambda *a, **kw: (escrituras.append(1), original(*a, **kw))[1])
    procesar_comando_memoria("recuerda que mi gato se llama Mishi y mi perro se llama Rex y mi pez se llama Nemo")
    assert len(escrituras) == 1
    assert hechos_en_disco() == {"gato": "Mishi", "perro": "Rex", "pez": "Nemo"}


def test_fallo_de_escritura_multiple_no_deja_nada_a_medias(_almacen_temporal):
    procesar_comando_memoria("recuerda que mi coche es rojo")
    antes = _almacen_temporal.hechos.read_bytes()
    llamadas = []
    real_replace = os.replace

    def falla_en_la_segunda(*a, **kw):
        llamadas.append(a)
        raise OSError("disco lleno (simulado)")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", falla_en_la_segunda)
        r = procesar_comando_memoria("recuerda que mi gato se llama Mishi y mi perro se llama Rex")
    assert "NINGÚN cambio" in r and "Hecho guardado" not in r          # informe exacto: nada guardado
    assert _almacen_temporal.hechos.read_bytes() == antes
    assert len(llamadas) == 1                                           # un único intento de escritura
    assert real_replace is os.replace


def test_conflicto_parcial_se_informa_con_exactitud():
    procesar_comando_memoria("recuerda que mi gato se llama Mishi")
    r = procesar_comando_memoria("recuerda que mi gato se llama Tom y mi perro se llama Rex")
    lineas = r.splitlines()
    assert len(lineas) == 2
    assert "Ya tengo guardado que gato es Mishi" in lineas[0] and "Hecho guardado: perro = Rex" in lineas[1]
    assert hechos_en_disco() == {"gato": "Mishi", "perro": "Rex"}


def test_ambiguedad_en_un_hecho_bloquea_toda_la_peticion(planes):
    antes = bytes_en_disco()
    r = procesar_comando_memoria("recuerda que ahora mi perro es Rex y mi plan es viajar es lo mejor")
    assert "No está claro" in r
    assert bytes_en_disco() == antes              # ni siquiera 'perro'


# =========================================================================== consultas parciales: sólo sugerencias
@pytest.mark.parametrize("frase", ["¿cuál es mi número?", "¿qué recuerdas de mi número?", "¿qué sabes de mi número?",
                                   "¿recuerdas mi número?", "¿recuerdas que mi número es 7?", "what is my número?"])
def test_coincidencia_parcial_es_sugerencia_sin_valor(frase):
    procesar_comando_memoria("recuerda que mi número de la suerte es 7")
    r = procesar_comando_memoria(frase)
    assert "número de la suerte" in r and "7" not in r.replace(frase, "")
    assert not r.startswith(("Sí", "Yes"))


# =========================================================================== migración: nada olvidado vuelve
def _falla_vaciar_perfil(mp):
    real = memoria._escribir_atomico

    def escribir(ruta, contenido, prefijo):
        if ruta == memoria.MEMORY_PATH:
            raise OSError("perfil de solo lectura (simulado)")
        return real(ruta, contenido, prefijo)

    mp.setattr(memoria, "_escribir_atomico", escribir)


def test_migracion_con_perfil_no_vaciable_no_reimporta_lo_olvidado(_almacen_temporal, capsys):
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"furgoneta": "una camper", "gato": "Mishi"}})
    with pytest.MonkeyPatch.context() as mp:
        _falla_vaciar_perfil(mp)
        assert "Olvidado" in procesar_comando_memoria("olvida mi furgoneta")
        # el perfil sigue lleno (no se pudo vaciar) pero la furgoneta no vuelve por ningún camino
        assert "furgoneta" in _almacen_temporal.perfil.read_text()
        for _ in range(3):
            assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi furgoneta?")
        contexto = memoria.get_memory_context()
        assert "camper" not in contexto and contexto.count("Mishi") == 1
        procesar_comando_memoria("olvida todo, confirmo")
        assert hechos_en_disco() == {} and "Mishi" not in memoria.get_memory_context()
    salida = capsys.readouterr().out
    assert salida.count("no he podido vaciar el perfil") == 1               # sin avisos repetidos
    # cuando el perfil vuelve a ser escribible se vacía, sin reimportar nada
    memoria.migrar_perfil_legado()
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}
    assert hechos_en_disco() == {}


def test_perfil_editado_tras_migrar_sólo_importa_lo_nuevo(_almacen_temporal):
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"furgoneta": "una camper"}})
    procesar_comando_memoria("olvida mi furgoneta")
    # alguien restaura el perfil antiguo y añade un dato nuevo
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"furgoneta": "una camper", "perro": "Rex"}})
    assert memoria.migrar_perfil_legado() == 1
    assert hechos_en_disco() == {"perro": "Rex"}


def test_huellas_de_migracion_validadas_por_el_esquema(_almacen_temporal):
    _almacen_temporal.hechos.write_text("version: 1\nhechos: {}\nlegado_migrado: 3\n", encoding="utf-8")
    with pytest.raises(memoria.MemoriaHechosInvalida, match="legado_migrado"):
        memoria.cargar_hechos()


# =========================================================================== CLI de punta a punta
def test_cli_clave_completa_y_aclaraciones_sin_motor(memoria_temporal, selector_fake, monkeypatch, capsys, tmp_path):
    import builtins
    import core.ai_engine as ai
    import core.assistant as assistant
    monkeypatch.setattr(memoria, "HISTORY_DIR", str(tmp_path / "h"))
    monkeypatch.setattr(memoria, "SESSION_FILE", str(tmp_path / "h" / "historial.json"))
    sel = selector_fake.crear(config_base("offline"))
    monkeypatch.setattr(ai, "_selector", sel)
    monkeypatch.setattr(assistant, "chat_history", [])
    entradas = ["recuerda que mi viaje es en mayo", "recuerda que mi viaje a Roma es en junio",
                "actualiza en tu memoria mi viaje a Roma a julio",          # ambiguo -> aclaración
                "recuerda que ahora mi viaje a Roma es en julio",           # inequívoco
                "online: recuerda", "online: olvídalo", "¿cuál es mi viaje a?", "salir"]
    monkeypatch.setattr(builtins, "input", lambda *_: entradas.pop(0))
    assistant.run_assistant()
    out = capsys.readouterr().out
    assert "No está claro" in out and "Actualizado: viaje a Roma = en julio" in out
    assert "Quizá te refieres a" in out and "Estás en modo OFFLINE" not in out
    assert hechos_en_disco() == {"viaje": "en mayo", "viaje a roma": "en julio"}
    assert all(m.llamadas == [] for m in selector_fake.motores.todos.values())
    assert selector_fake.estado["hosts"] == []


# =========================================================================== compatibilidad con almacenes 'perfil_migrado'
import hashlib


_SIN_MARCADOR = object()


def _almacen_marcado(almacen, marcador=_SIN_MARCADOR, hechos=None, clave="perfil_migrado"):
    """Escribe un almacén como el de una versión anterior: hechos + marcador de migración
    (None escribe la clave con valor nulo; _SIN_MARCADOR la omite)."""
    datos = {"version": 1, "hechos": hechos if hechos is not None else
             {"gato": {"clave": "gato", "valor": "Mishi", "origen": "user_profile.yaml"}}}
    if marcador is not _SIN_MARCADOR:
        datos[clave] = marcador
    almacen.hechos.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


PERFIL_VIEJO = {"aprendido_durante_sesion": {"furgoneta": "una camper", "gato": "Mishi"}}   # furgoneta ya olvidada


def _texto_perfil(datos=PERFIL_VIEJO):
    return yaml.safe_dump(datos, allow_unicode=True)


def _marcadores_compatibles():
    texto = _texto_perfil()
    sha = hashlib.sha256(texto.encode()).hexdigest()
    return [
        ("lista de huellas del perfil completo", [sha]),
        ("una sola huella", sha),
        ("diccionario con huella", {"sha256": sha}),
        ("huella del volcado canónico", [hashlib.sha256(yaml.safe_dump(PERFIL_VIEJO, sort_keys=True).encode()).hexdigest()]),
        ("md5 del perfil", [hashlib.md5(texto.encode()).hexdigest()]),
        ("huellas por hoja (formato actual)", [memoria._huella(["aprendido_durante_sesion", "furgoneta"], "una camper"),
                                               memoria._huella(["aprendido_durante_sesion", "gato"], "Mishi")]),
        # el marcador NO reconocido tiene su propia semántica: ver test_marcador_no_reconocido_*
    ]


def _casos_marcadores():
    casos = [("perfil_migrado", d, m) for d, m in _marcadores_compatibles()]
    # el alias 'legado_migrado' sólo existió con huellas por hoja
    casos.append(("legado_migrado",) + _marcadores_compatibles()[5])
    return casos


@pytest.mark.parametrize("clave,descripcion,marcador", _casos_marcadores(), ids=lambda x: x if isinstance(x, str) and len(x) < 60 else "")
def test_almacen_marcado_por_otra_version_conserva_hechos_y_no_resucita(_almacen_temporal, clave, descripcion, marcador):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, marcador, clave=clave)
    # los hechos del almacén se usan con normalidad
    assert "gato es Mishi" in procesar_comando_memoria("¿cuál es mi gato?")
    # el dato olvidado del perfil no vuelve: ni como hecho ni como contexto
    assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi furgoneta?")
    contexto = memoria.get_memory_context()
    assert "camper" not in contexto and contexto.count("Mishi") == 1
    assert hechos_en_disco() == {"gato": "Mishi"}
    # el perfil queda en copia y vacío
    assert list(_almacen_temporal.dir.glob("user_profile.yaml.legado-*.bak"))
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}
    # después de olvidar el último hecho heredado tampoco vuelve nada, y el marcador
    # queda consolidado bajo 'perfil_migrado' con huellas propias
    procesar_comando_memoria("olvida mi gato")
    assert hechos_en_disco() == {} and memoria.get_memory_context() == ""
    datos = yaml.safe_load(_almacen_temporal.hechos.read_text(encoding="utf-8"))
    assert "perfil_migrado" in datos and "legado_migrado" not in datos
    assert all(":" in h for h in datos["perfil_migrado"])
    # y si alguien restaura el perfil viejo, sigue sin volver nada
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    assert memoria.migrar_perfil_legado() == 0 and hechos_en_disco() == {}
    # pero un dato NUEVO añadido al perfil sí se importa (el marcador ajeno ya fue absorbido)
    _almacen_temporal.perfil.write_text(_texto_perfil({"aprendido_durante_sesion": {"perro": "Rex"}}), encoding="utf-8")
    assert memoria.migrar_perfil_legado() == 1 and hechos_en_disco() == {"perro": "Rex"}


# --------------------------------------------------------------------------- marcador no reconocido: pendiente de conciliar
def test_marcador_no_reconocido_deja_lo_incierto_pendiente_sin_borrar_ni_inyectar(_almacen_temporal, capsys):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    perfil_original = _almacen_temporal.perfil.read_bytes()
    _almacen_marcado(_almacen_temporal, ["0123456789abcdef0123456789abcdef"])   # huella de otra versión, irreconocible
    hechos_original = _almacen_temporal.hechos.read_bytes()
    for _ in range(3):
        assert "gato es Mishi" in procesar_comando_memoria("¿cuál es mi gato?")        # los hechos funcionan
        assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi furgoneta?")
        contexto = memoria.get_memory_context()
        assert "camper" not in contexto and contexto.count("Mishi") == 1            # ni reintroducido ni inyectado
    # perfil intacto (ni vaciado ni copiado), almacén sin tocar (nada que escribir)
    assert _almacen_temporal.perfil.read_bytes() == perfil_original
    assert not list(_almacen_temporal.dir.glob("user_profile.yaml.legado-*.bak"))
    assert _almacen_temporal.hechos.read_bytes() == hechos_original
    salida = capsys.readouterr().out
    assert salida.count("pendientes de conciliar") == 1                              # se explica, una vez
    assert "'furgoneta'" in salida and "'gato'" not in salida.split("pendientes de conciliar")[1].split(")")[0]
    assert "no sé interpretar" in salida and "recuerda que <clave> es <valor>" in salida


def test_marcador_no_reconocido_nada_incierto_entra_ni_siquiera_nuevo(_almacen_temporal):
    """Con un marcador irreconocible no se puede distinguir 'nuevo' de 'olvidado': todo lo
    que no esté ya en los hechos queda pendiente (nada se importa)."""
    _almacen_temporal.perfil.write_text(_texto_perfil({"aprendido_durante_sesion": {
        "gato": "Mishi", "furgoneta": "una camper", "perro": "Rex"}}), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, ["no-es-una-huella-conocida"])
    assert memoria.migrar_perfil_legado() == 0
    assert hechos_en_disco() == {"gato": "Mishi"}
    assert "Rex" not in memoria.get_memory_context() and "camper" not in memoria.get_memory_context()


def test_marcador_no_reconocido_se_concilia_con_peticion_explicita(_almacen_temporal, capsys):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    perfil_original = _almacen_temporal.perfil.read_bytes()
    _almacen_marcado(_almacen_temporal, ["0123456789abcdef0123456789abcdef"])
    procesar_comando_memoria("¿qué recuerdas?")
    # el usuario decide conservar el dato incierto: se guarda como hecho explícito
    assert "Hecho guardado: furgoneta = una camper" in procesar_comando_memoria("recuerda que mi furgoneta es una camper")
    # ya no queda nada pendiente: el perfil se vacía (con copia) y no se duplica nada
    memoria.migrar_perfil_legado()
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}
    copias = list(_almacen_temporal.dir.glob("user_profile.yaml.legado-*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == perfil_original
    contexto = memoria.get_memory_context()
    assert contexto.count("camper") == 1 and contexto.count("Mishi") == 1
    # el marcador ajeno se conserva (no se ha podido interpretar, no se descarta)
    datos = yaml.safe_load(_almacen_temporal.hechos.read_text(encoding="utf-8"))
    assert "0123456789abcdef0123456789abcdef" in datos["perfil_migrado"]


def test_marcador_no_reconocido_y_olvido_posterior_no_resucita(_almacen_temporal):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, ["0123456789abcdef0123456789abcdef"])
    procesar_comando_memoria("olvida mi gato")          # el único hecho seguro se olvida
    for _ in range(2):
        assert hechos_en_disco() == {}
        contexto = memoria.get_memory_context()
        assert "Mishi" not in contexto and "camper" not in contexto
    assert "gato" in _almacen_temporal.perfil.read_text()   # el perfil sigue intacto, pendiente


def test_marcador_diccionario_conserva_valores_desconocidos_como_incertidumbre(_almacen_temporal):
    sha = hashlib.sha256(_texto_perfil().encode()).hexdigest()
    _almacen_marcado(_almacen_temporal, {"sha256": sha, "fecha": "2025-01-01", "version": "0.9"})
    assert memoria.huellas_migradas() == {sha, "2025-01-01", "0.9"}          # nada se descarta


def test_marcador_diccionario_mixto_certeza_para_este_perfil_y_prudencia_despues(_almacen_temporal):
    """Una huella reconocida da certeza sobre ESTE perfil; los valores desconocidos del
    diccionario se conservan y, en adelante, mantienen la prudencia (pendiente) para lo nuevo."""
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    sha = hashlib.sha256(_texto_perfil().encode()).hexdigest()
    _almacen_marcado(_almacen_temporal, {"sha256": sha, "fecha": "2025-01-01"})
    assert "gato es Mishi" in procesar_comando_memoria("¿cuál es mi gato?")
    assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi furgoneta?")
    assert "camper" not in memoria.get_memory_context()
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}   # migrado con certeza
    datos = yaml.safe_load(_almacen_temporal.hechos.read_text(encoding="utf-8"))
    assert "2025-01-01" in datos["perfil_migrado"] and sha not in datos["perfil_migrado"]
    # lo que se añada después al perfil queda pendiente: no se puede distinguir de algo olvidado
    _almacen_temporal.perfil.write_text(_texto_perfil({"aprendido_durante_sesion": {"perro": "Rex"}}), encoding="utf-8")
    assert memoria.migrar_perfil_legado() == 0 and hechos_en_disco() == {"gato": "Mishi"}
    assert "Rex" not in memoria.get_memory_context()


def test_almacen_marcado_y_perfil_con_datos_nuevos_por_hoja(_almacen_temporal):
    """Marcador por hojas (formato actual): las hojas no marcadas SÍ son nuevas y se importan."""
    _almacen_temporal.perfil.write_text(_texto_perfil({"aprendido_durante_sesion": {
        "furgoneta": "una camper", "perro": "Rex"}}), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, [memoria._huella(["aprendido_durante_sesion", "furgoneta"], "una camper")])
    assert memoria.migrar_perfil_legado() == 1
    assert hechos_en_disco() == {"gato": "Mishi", "perro": "Rex"}


def test_almacen_marcado_sin_perfil_funciona_sin_ruido(_almacen_temporal, capsys):
    _almacen_marcado(_almacen_temporal, ["deadbeef"])
    os.unlink(_almacen_temporal.perfil)
    assert "gato es Mishi" in procesar_comando_memoria("¿cuál es mi gato?")
    assert "marcado como migrado" not in capsys.readouterr().out


@pytest.mark.parametrize("contenido", [
    "version: 1\nhechos: {}\nperfil_migrado: 3\n",
    "version: 1\nhechos: {}\nperfil_migrado: [1, 2]\n",
    "version: 1\nhechos: {}\nperfil_migrado: {a: {b: c}}\n",
    "version: 1\nhechos: {}\nlegado_migrado: true\n",
])
def test_marcadores_con_forma_invalida_se_rechazan(_almacen_temporal, contenido):
    _almacen_temporal.hechos.write_text(contenido, encoding="utf-8")
    with pytest.raises(memoria.MemoriaHechosInvalida, match="migrado"):
        memoria.cargar_hechos()


def test_almacen_marcado_con_escritura_persistentemente_fallida(_almacen_temporal, capsys):
    """Ni siquiera pudiendo escribir: lo olvidado no vuelve, el perfil no se reimporta y se avisa una vez."""
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, [hashlib.sha256(_texto_perfil().encode()).hexdigest()])
    antes = (_almacen_temporal.hechos.read_bytes(), _almacen_temporal.perfil.read_bytes())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disco de solo lectura (simulado)")))
        for _ in range(3):
            assert "gato es Mishi" in procesar_comando_memoria("¿cuál es mi gato?")
            assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi furgoneta?")
            assert "camper" not in memoria.get_memory_context()
    assert (_almacen_temporal.hechos.read_bytes(), _almacen_temporal.perfil.read_bytes()) == antes
    salida = capsys.readouterr().out
    assert salida.count("no he podido anotar las huellas") == 1


# =========================================================================== colisiones: ningún valor heredado se pierde
def test_colision_con_hecho_y_con_perfil_anterior_conserva_todos_los_valores(_almacen_temporal):
    procesar_comando_memoria("recuerda que mi coche es rojo")
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"coche": "azul"}})
    assert memoria.migrar_perfil_legado() == 1
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"coche": "verde"}})   # otra versión antigua
    assert memoria.migrar_perfil_legado() == 1
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"coche": "verde"}})   # el mismo valor: no se duplica
    assert memoria.migrar_perfil_legado() == 0
    assert hechos_en_disco() == {"coche": "rojo", "coche (perfil anterior)": "azul", "coche (perfil anterior 2)": "verde"}
    # todos consultables y olvidables por separado
    assert "azul" in procesar_comando_memoria("¿cuál es mi coche (perfil anterior)?")
    assert "Olvidado" in procesar_comando_memoria("olvida mi coche (perfil anterior 2)")
    assert hechos_en_disco() == {"coche": "rojo", "coche (perfil anterior)": "azul"}


def test_colision_entre_hojas_del_propio_perfil(_almacen_temporal):
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"coche": "rojo"},
                                        "vida_personal": {"coche": "azul", "pareja": {"nombre": "Ana"}},
                                        "nombre": "Jon", "Coche": "verde"})
    assert memoria.migrar_perfil_legado() == 5
    assert sorted(hechos_en_disco().values()) == ["Ana", "Jon", "azul", "rojo", "verde"]
    assert hechos_en_disco()["coche"] in ("rojo", "verde")   # el resto con sus padres o sufijo, nunca descartados


# =========================================================================== procesos nuevos con fallos persistentes
def _programa_migracion(tmp_path, entrada, perfil_no_vaciable):
    """Proceso autónomo de memoria; con perfil_no_vaciable simula en CADA proceso
    que el perfil no se puede reescribir (fallo persistente)."""
    from config.motors_config import PROJECT_ROOT
    return f"""
import sys, os
sys.path.insert(0, {str(PROJECT_ROOT)!r})
import core.memory_engine as m
m.FACTS_PATH = {str(tmp_path / 'facts.yaml')!r}
m.MEMORY_PATH = {str(tmp_path / 'perfil.yaml')!r}
if {perfil_no_vaciable!r}:
    _real = m._escribir_atomico
    def _escribir(ruta, contenido, prefijo):
        if ruta == m.MEMORY_PATH:
            raise OSError("perfil de solo lectura (simulado)")
        return _real(ruta, contenido, prefijo)
    m._escribir_atomico = _escribir
from core.memory_commands import procesar_comando_memoria
print(procesar_comando_memoria({entrada!r}))
print("CONTEXTO>>>" + m.get_memory_context().replace("\\n", " | "))
"""


def _proceso_migracion(tmp_path, entrada, perfil_no_vaciable=True):
    r = subprocess.run([sys.executable, "-c", _programa_migracion(tmp_path, entrada, perfil_no_vaciable)],
                       cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_fallo_persistente_al_vaciar_el_perfil_entre_procesos(tmp_path):
    perfil = tmp_path / "perfil.yaml"
    perfil.write_text(yaml.safe_dump({"aprendido_durante_sesion": {"furgoneta": "una camper", "gato": "Mishi"}}))
    texto_perfil = perfil.read_bytes()
    out = _proceso_migracion(tmp_path, "¿cuál es mi furgoneta?")           # migra; no puede vaciar
    assert "una camper" in out and "no he podido vaciar" in out
    out = _proceso_migracion(tmp_path, "olvida mi furgoneta")
    assert "Olvidado: furgoneta" in out
    for _ in range(2):                                                    # procesos nuevos, perfil aún lleno
        out = _proceso_migracion(tmp_path, "¿qué recuerdas?")
        assert "furgoneta" not in out and "- gato: Mishi" in out
        assert "camper" not in out.split("CONTEXTO>>>")[1] and out.split("CONTEXTO>>>")[1].count("Mishi") == 1
    assert perfil.read_bytes() == texto_perfil                            # intacto mientras falla
    copias = list(tmp_path.glob("perfil.yaml.legado-*.bak"))
    assert len(copias) == 1                                               # una sola copia, no una por proceso
    # el fallo desaparece: el perfil se vacía sin reimportar nada
    out = _proceso_migracion(tmp_path, "¿qué recuerdas?", perfil_no_vaciable=False)
    assert "furgoneta" not in out and "- gato: Mishi" in out
    assert yaml.safe_load(perfil.read_text()) == {"aprendido_durante_sesion": {}}
    assert "furgoneta" not in _proceso_migracion(tmp_path, "¿qué recuerdas?", perfil_no_vaciable=False)


def test_almacen_perfil_migrado_entre_procesos(tmp_path):
    perfil = tmp_path / "perfil.yaml"
    texto = yaml.safe_dump({"aprendido_durante_sesion": {"furgoneta": "una camper", "gato": "Mishi"}})
    perfil.write_text(texto)
    (tmp_path / "facts.yaml").write_text(yaml.safe_dump({"version": 1,
        "hechos": {"gato": {"clave": "gato", "valor": "Mishi"}},
        "perfil_migrado": [hashlib.sha256(texto.encode()).hexdigest()]}))
    out = _proceso_migracion(tmp_path, "¿qué recuerdas?", perfil_no_vaciable=False)
    assert "- gato: Mishi" in out and "furgoneta" not in out and "marcado como migrado" in out
    out = _proceso_migracion(tmp_path, "¿cuál es mi furgoneta?", perfil_no_vaciable=False)
    assert "No tengo nada guardado" in out and "camper" not in out.split("CONTEXTO>>>")[1]


def test_marcador_no_reconocido_en_procesos_nuevos_con_fallo_persistente(tmp_path):
    perfil = tmp_path / "perfil.yaml"
    perfil.write_text(_texto_perfil(), encoding="utf-8")
    original = perfil.read_bytes()
    (tmp_path / "facts.yaml").write_text(yaml.safe_dump({"version": 1,
        "hechos": {"gato": {"clave": "gato", "valor": "Mishi"}},
        "perfil_migrado": ["0123456789abcdef0123456789abcdef"]}), encoding="utf-8")

    out = _proceso_migracion(tmp_path, "¿qué recuerdas?")              # perfil no escribible en cada proceso
    assert "- gato: Mishi" in out and "furgoneta" not in out.split("pendientes de conciliar")[0]
    assert "pendientes de conciliar ('furgoneta')" in out and "no sé interpretar" in out
    assert "camper" not in out.split("CONTEXTO>>>")[1]
    assert "Olvidado: gato" in _proceso_migracion(tmp_path, "olvida mi gato")
    for _ in range(3):                                                  # procesos nuevos repetidos
        out = _proceso_migracion(tmp_path, "¿qué recuerdas?")
        assert "ningún hecho" in out
        contexto = out.split("CONTEXTO>>>")[1]
        assert "Mishi" not in contexto and "camper" not in contexto     # ni lo olvidado ni lo incierto
        assert out.count("pendientes de conciliar") == 1                # se explica en cada sesión, una vez
    assert perfil.read_bytes() == original                              # ni vaciado ni reescrito
    assert not list(tmp_path.glob("perfil.yaml.legado-*.bak"))
    datos = yaml.safe_load((tmp_path / "facts.yaml").read_text(encoding="utf-8"))
    assert datos["hechos"] == {} and datos["perfil_migrado"] == ["0123456789abcdef0123456789abcdef"]


# =========================================================================== marcadores con ':' no reconocidos
@pytest.mark.parametrize("marcador", [
    "hoja:no-es-una-huella", "perfil:0123", "otra-version:abc", "hoja:" + "g" * 64, "PERFIL:" + "0" * 64,
    "hoja:" + "0" * 63, "v2:" + hashlib.sha256(b"x").hexdigest(), "deadbeef", "",
])
def test_marcador_no_reconocido_con_o_sin_dos_puntos_deja_pendiente(_almacen_temporal, marcador, capsys):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    original = _almacen_temporal.perfil.read_bytes()
    _almacen_marcado(_almacen_temporal, [marcador] if marcador else [""])
    hechos_original = _almacen_temporal.hechos.read_bytes()
    for _ in range(2):
        assert "gato es Mishi" in procesar_comando_memoria("¿cuál es mi gato?")
        assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi furgoneta?")
        assert "camper" not in memoria.get_memory_context()
    assert hechos_en_disco() == {"gato": "Mishi"}                             # nada importado
    assert _almacen_temporal.perfil.read_bytes() == original                  # ni vaciado ni reescrito
    assert _almacen_temporal.hechos.read_bytes() == hechos_original           # marcador conservado tal cual
    assert not list(_almacen_temporal.dir.glob("user_profile.yaml.legado-*.bak"))
    assert capsys.readouterr().out.count("pendientes de conciliar ('furgoneta')") == 1


def test_marcador_no_reconocido_no_impide_reconocer_este_perfil(_almacen_temporal):
    """Un marcador ajeno que SÍ identifica el perfil actual da certeza aunque haya otros irreconocibles."""
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    sha = hashlib.sha256(_texto_perfil().encode()).hexdigest()
    _almacen_marcado(_almacen_temporal, ["otra-version:abc", sha])
    assert memoria.migrar_perfil_legado() == 0
    assert hechos_en_disco() == {"gato": "Mishi"}
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}   # migrado con certeza
    datos = yaml.safe_load(_almacen_temporal.hechos.read_text(encoding="utf-8"))
    assert "otra-version:abc" in datos["perfil_migrado"] and sha not in datos["perfil_migrado"]      # el ajeno se conserva


def test_huellas_propias_bien_formadas_de_migraciones_anteriores_no_bloquean_lo_nuevo(_almacen_temporal):
    """'hoja:'/'perfil:' + sha256 son registros propios de migraciones pasadas: lo nuevo se importa."""
    _almacen_temporal.perfil.write_text(_texto_perfil({"aprendido_durante_sesion": {"perro": "Rex"}}), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, ["hoja:" + "a" * 64, "perfil:" + "0" * 64])
    assert memoria.migrar_perfil_legado() == 1
    assert hechos_en_disco() == {"gato": "Mishi", "perro": "Rex"}


def test_alias_legado_con_huella_mal_formada_queda_pendiente(_almacen_temporal):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, ["no-hex"], clave="legado_migrado")
    assert memoria.migrar_perfil_legado() == 0
    assert hechos_en_disco() == {"gato": "Mishi"} and "camper" not in memoria.get_memory_context()


# =========================================================================== diccionarios de marcadores: contenido desconocido
def _sha_perfil():
    return hashlib.sha256(_texto_perfil().encode()).hexdigest()


CASOS_DICCIONARIO_INCIERTO = [
    ("cadenas desconocidas", {"version": "0.9", "nota": "migrado"}),
    ("lista desconocida", {"huellas": ["x", "y"]}),
    ("mezcla de propio mal formado y desconocido", {"a": "hoja:no-hex", "b": ["perfil:0123"]}),
    ("vacío", {}),
    ("nulo", None),
    ("lista vacía", []),
    ("cadena vacía", ""),
    ("lista con cadena desconocida", ["lo-que-sea"]),
]


@pytest.mark.parametrize("clave", ["perfil_migrado", "legado_migrado"])
@pytest.mark.parametrize("descripcion,marcador", CASOS_DICCIONARIO_INCIERTO, ids=lambda x: x if isinstance(x, str) else "")
def test_contenido_desconocido_del_marcador_mantiene_la_incertidumbre(_almacen_temporal, clave, descripcion, marcador, capsys):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    _almacen_marcado(_almacen_temporal, marcador, clave=clave)
    antes = (_almacen_temporal.perfil.read_bytes(), _almacen_temporal.hechos.read_bytes())
    assert memoria.huellas_migradas()                                          # nunca un conjunto vacío
    for _ in range(2):
        assert "gato es Mishi" in procesar_comando_memoria("¿cuál es mi gato?")
        assert "No tengo nada guardado" in procesar_comando_memoria("¿cuál es mi furgoneta?")
        assert "camper" not in memoria.get_memory_context()
    assert hechos_en_disco() == {"gato": "Mishi"}                             # nada importado
    assert (_almacen_temporal.perfil.read_bytes(), _almacen_temporal.hechos.read_bytes()) == antes   # sin modificar
    assert capsys.readouterr().out.count("pendientes de conciliar") == 1


@pytest.mark.parametrize("clave", ["perfil_migrado", "legado_migrado"])
def test_diccionario_con_huella_reconocida_y_valores_desconocidos(_almacen_temporal, clave):
    """Mezcla: la huella que identifica ESTE perfil da certeza; lo desconocido se conserva."""
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    marcador = {"sha": _sha_perfil(), "otros": ["x", "y"], "nota": "v0.9"}
    if clave == "legado_migrado":   # el alias etiqueta los valores sin ':' como 'hoja:' -> la huella del perfil
        marcador["sha"] = "perfil:" + _sha_perfil()   # completo sólo se reconoce con su etiqueta propia
    _almacen_marcado(_almacen_temporal, marcador, clave=clave)
    assert memoria.migrar_perfil_legado() == 0
    assert hechos_en_disco() == {"gato": "Mishi"}
    assert yaml.safe_load(_almacen_temporal.perfil.read_text()) == {"aprendido_durante_sesion": {}}
    datos = yaml.safe_load(_almacen_temporal.hechos.read_text(encoding="utf-8"))
    conservados = {"x", "y"} if clave == "perfil_migrado" else {"hoja:x", "hoja:y"}   # el alias etiqueta lo que no lleva ':'
    assert conservados <= set(datos["perfil_migrado"]) and "legado_migrado" not in datos
    assert "camper" not in memoria.get_memory_context()


@pytest.mark.parametrize("clave", ["perfil_migrado", "legado_migrado"])
@pytest.mark.parametrize("contenido", [
    "{a: 1}", "{a: [1, 2]}", "{a: {b: c}}", "{a: null}", "{a: true}", "[a, 1]", "7", "true",
])
def test_formas_invalidas_del_marcador_rechazan_el_esquema_sin_tocar_nada(_almacen_temporal, clave, contenido):
    _almacen_temporal.perfil.write_text(_texto_perfil(), encoding="utf-8")
    _almacen_temporal.hechos.write_text(
        f"version: 1\nhechos: {{gato: {{clave: gato, valor: Mishi}}}}\n{clave}: {contenido}\n", encoding="utf-8")
    antes = (_almacen_temporal.perfil.read_bytes(), _almacen_temporal.hechos.read_bytes())
    with pytest.raises(memoria.MemoriaHechosInvalida, match="migrado"):
        memoria.cargar_hechos()
    r = procesar_comando_memoria("¿cuál es mi furgoneta?")
    assert "dañado" in r
    assert "Hecho guardado" not in procesar_comando_memoria("recuerda que mi coche es rojo")
    assert (_almacen_temporal.perfil.read_bytes(), _almacen_temporal.hechos.read_bytes()) == antes


@pytest.mark.parametrize("clave", ["perfil_migrado", "legado_migrado"])
@pytest.mark.parametrize("marcador", [{"version": "0.9", "nota": "migrado"}, {"huellas": ["x", "y"]}, {}, None])
def test_marcador_desconocido_entre_procesos_lo_olvidado_no_vuelve(tmp_path, clave, marcador):
    perfil = tmp_path / "perfil.yaml"
    perfil.write_text(_texto_perfil(), encoding="utf-8")
    original = perfil.read_bytes()
    (tmp_path / "facts.yaml").write_text(yaml.safe_dump({"version": 1,
        "hechos": {"gato": {"clave": "gato", "valor": "Mishi"}}, clave: marcador}), encoding="utf-8")
    out = _proceso_migracion(tmp_path, "¿qué recuerdas?", perfil_no_vaciable=False)
    assert "- gato: Mishi" in out and "furgoneta" not in out.split("pendientes de conciliar")[0]
    assert "camper" not in out.split("CONTEXTO>>>")[1]
    assert "Olvidado: gato" in _proceso_migracion(tmp_path, "olvida mi gato", perfil_no_vaciable=False)
    for _ in range(2):
        out = _proceso_migracion(tmp_path, "¿qué recuerdas?", perfil_no_vaciable=False)
        assert "ningún hecho" in out
        contexto = out.split("CONTEXTO>>>")[1]
        assert "Mishi" not in contexto and "camper" not in contexto
    assert perfil.read_bytes() == original
    datos = yaml.safe_load((tmp_path / "facts.yaml").read_text(encoding="utf-8"))
    assert datos["hechos"] == {} and datos.get("perfil_migrado")                # el marcador se conserva (consolidado)
    esperados = {"ajeno:vacio"} if not marcador else {v for v in marcador.values() if isinstance(v, str)} | {
        h for v in marcador.values() if isinstance(v, list) for h in v}
    assert all(any(m.endswith(e) for m in datos["perfil_migrado"]) for e in esperados)


# =========================================================================== la escritura atómica conserva permisos
def test_escritura_atomica_conserva_los_permisos_del_fichero(_almacen_temporal):
    import stat
    _almacen_temporal.perfil.chmod(0o640)
    escribir_perfil(_almacen_temporal, {"aprendido_durante_sesion": {"gato": "Mishi"}})
    _almacen_temporal.perfil.chmod(0o640)
    memoria.migrar_perfil_legado()                     # reescribe el perfil (vaciado) y crea facts.yaml
    assert stat.S_IMODE(_almacen_temporal.perfil.stat().st_mode) == 0o640          # se conserva
    umask = os.umask(0); os.umask(umask)
    assert stat.S_IMODE(_almacen_temporal.hechos.stat().st_mode) == (0o666 & ~umask)   # nuevo: según umask
    procesar_comando_memoria("recuerda que mi coche es rojo")
    assert stat.S_IMODE(_almacen_temporal.hechos.stat().st_mode) == (0o666 & ~umask)
