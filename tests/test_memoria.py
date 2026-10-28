"""
Memoria persistente (core/memory_engine.py, fase 7 "aprendizaje local natural").

Pruebas de regresión con almacenamiento temporal y sin ningún motor: la memoria
es puramente local y determinista. Cubren:
  - interpretación de peticiones en lenguaje natural (variaciones, ES/EN) y, sobre
    todo, lo que NO debe interpretarse (conversación, preguntas, negaciones,
    ejemplos entrecomillados, peticiones incrustadas);
  - guardar / consultar / actualizar / añadir / olvidar, duplicados, conflictos
    y preguntas de aclaración;
  - formato del fichero, migración del formato antiguo, contexto para el motor;
  - robustez: ficheros ausentes, vacíos o corruptos y fallos de escritura.
"""
import os

import pytest
import yaml

from core import memory_engine as m


@pytest.fixture
def mem(perfil_temporal):
    """API mínima sobre el fichero temporal: pedir(texto) -> respuesta, hechos(), notas(), ruta."""
    class Mem:
        ruta = perfil_temporal

        @staticmethod
        def pedir(texto):
            return m.procesar_peticion(texto)

        @staticmethod
        def hechos():
            return m.listar_hechos()[0]

        @staticmethod
        def notas():
            return m.listar_hechos()[1]

        @staticmethod
        def yaml():
            return yaml.safe_load(perfil_temporal.read_text(encoding="utf-8"))

    return Mem


# =========================================================================== interpretación: variaciones aceptadas
GUARDAR = [
    ("recuerda que mi coche es rojo", "mi coche", "rojo"),
    ("Recuerda que mi coche es ROJO.", "mi coche", "ROJO"),
    ("recuerda: mi coche es rojo", "mi coche", "rojo"),
    ("recuerda mi coche es rojo", "mi coche", "rojo"),
    ("recuerda esto: mi coche es rojo", "mi coche", "rojo"),
    ("aprende: mi coche es rojo", "mi coche", "rojo"),
    ("aprende que mi coche es rojo", "mi coche", "rojo"),
    ("anota que mi coche es rojo", "mi coche", "rojo"),
    ("apunta que mi coche es rojo", "mi coche", "rojo"),
    ("guarda que mi coche es rojo", "mi coche", "rojo"),
    ("graba esto: mi coche es rojo", "mi coche", "rojo"),
    ("memoriza que mi coche es rojo", "mi coche", "rojo"),
    ("acuérdate de que mi coche es rojo", "mi coche", "rojo"),
    ("no olvides que mi coche es rojo", "mi coche", "rojo"),
    ("no te olvides de que mi coche es rojo", "mi coche", "rojo"),
    ("quiero que recuerdes que mi coche es rojo", "mi coche", "rojo"),
    ("me gustaría que recordaras que mi coche es rojo", "mi coche", "rojo"),
    ("puedes recordar que mi coche es rojo", "mi coche", "rojo"),
    ("B.A.I, recuerda que mi coche es rojo", "mi coche", "rojo"),
    ("bai por favor recuerda que mi coche es rojo, por favor!", "mi coche", "rojo"),
    ("Recuerda, por favor, que mi coche es rojo", "mi coche", "rojo"),
    ("  recuerda   que  mi coche   es rojo  ", "mi coche", "rojo"),
    ("recuerda que «mi coche» es 'rojo'", "mi coche", "rojo"),
    ("recuerda que mi coche = rojo", "mi coche", "rojo"),
    ("recuerda que mi coche: rojo", "mi coche", "rojo"),
    ("recuerda que mis hijos son Ana y Luis", "mis hijos", "Ana y Luis"),
    ("recuerda que mi perro se llama Rex", "mi perro", "Rex"),
    ("recuerda que mi coche está en el garaje", "mi coche", "en el garaje"),
    ("recuerda que mi cumpleaños es el 3 de mayo", "mi cumpleaños", "el 3 de mayo"),
    ("remember that my car is red", "my car", "red"),
    ("Remember: my car is red.", "my car", "red"),
    ("remember my car is red", "my car", "red"),
    ("please remember that my car is red", "my car", "red"),
    ("don't forget that my car is red", "my car", "red"),
    ("do not forget my car is red", "my car", "red"),
    ("note that my car is red", "my car", "red"),
    ("write down that my car is red", "my car", "red"),
    ("I want you to remember that my car is red", "my car", "red"),
    ("could you please remember that my car is red", "my car", "red"),
    ("remember that my kids are Ana and Luis", "my kids", "Ana and Luis"),
]


@pytest.mark.parametrize("texto,clave,valor", GUARDAR)
def test_variantes_de_guardar(texto, clave, valor):
    p = m.interpretar(texto)
    assert p is not None and p.op == "guardar", texto
    assert (p.clave, p.valor) == (clave, valor)


NOTAS = [
    ("recuerda que tengo que llamar a Juan", "tengo que llamar a Juan"),
    ("no olvides que me gusta el café solo", "me gusta el café solo"),
    ("recuerda que no como carne", "no como carne"),
    ("remember that I don't eat meat", "I don't eat meat"),
    ("recuerda que tengo que llamar a Juan porque es su cumpleaños", "tengo que llamar a Juan porque es su cumpleaños"),
]


@pytest.mark.parametrize("texto,nota", NOTAS)
def test_frases_sin_clave_valor_se_guardan_como_nota(texto, nota):
    p = m.interpretar(texto)
    assert p is not None and p.op == "guardar" and p.clave is None and p.valor == nota


CONSULTAR = [
    ("¿qué sabes de mi coche?", "mi coche"),
    ("que sabes sobre mi coche", "mi coche"),
    ("¿Qué recuerdas acerca de mi coche?", "mi coche"),
    ("dime qué sabes de mi coche", "mi coche"),
    ("¿qué tienes guardado sobre mi coche?", "mi coche"),
    ("¿qué has guardado de mi coche?", "mi coche"),
    ("B.A.I, ¿qué recuerdas de mi coche?", "mi coche"),
    ("what do you know about my car?", "my car"),
    ("What do you remember about my car", "my car"),
    ("what have you saved about my car?", "my car"),
    ("tell me what you remember about my car", "my car"),
]


@pytest.mark.parametrize("texto,termino", CONSULTAR)
def test_variantes_de_consultar(texto, termino):
    p = m.interpretar(texto)
    assert p is not None and p.op == "consultar" and p.termino == termino


@pytest.mark.parametrize("texto", [
    "¿qué recuerdas?", "qué sabes de mí", "¿qué has aprendido?", "what do you remember?", "what do you know about me?",
    "ver memoria", "muestra tu memoria", "muéstrame lo que sabes de mí", "lista los hechos", "show me your memory",
    "list facts", "enséñame la memoria persistente",
])
def test_variantes_de_listar(texto):
    p = m.interpretar(texto)
    assert p is not None and p.op == "listar"


OLVIDAR = [
    ("olvida mi coche", "mi coche"),
    ("Olvida lo de mi coche.", "mi coche"),
    ("olvídate de mi coche", "mi coche"),
    ("olvida lo que sabes de mi coche", "mi coche"),
    ("olvida todo lo que sabes sobre mi coche", "mi coche"),
    ("borra mi coche de tu memoria", "mi coche"),
    ("elimina lo que sabes de mi coche", "mi coche"),
    ("quita el dato de mi coche de la memoria", "mi coche"),
    ("deja de recordar mi coche", "mi coche"),
    ("no recuerdes más mi coche", "mi coche"),
    ("B.A.I, por favor, olvida mi coche", "mi coche"),
    ("olvida, por favor, mi coche", "mi coche"),
    ("forget my car", "my car"),
    ("forget about my car", "my car"),
    ("forget everything about my car", "my car"),
    ("delete my car from your memory", "my car"),
    ("remove what you know about my car", "my car"),
    ("stop remembering my car", "my car"),
]


@pytest.mark.parametrize("texto,termino", OLVIDAR)
def test_variantes_de_olvidar(texto, termino):
    p = m.interpretar(texto)
    assert p is not None and p.op == "olvidar" and p.termino == termino


@pytest.mark.parametrize("texto", [
    "olvida que mi coche es rojo", "olvídate de que mi coche es rojo", "forget that my car is red",
])
def test_olvidar_un_valor_concreto(texto):
    p = m.interpretar(texto)
    assert p.op == "olvidar_valor" and p.valor in ("rojo", "red")


@pytest.mark.parametrize("texto", [
    "olvida todo", "olvida todo lo que sabes de mí", "olvida lo que sabes de mí", "borra toda tu memoria", "olvídate de todo",
    "forget everything", "forget everything about me", "erase your memory",
])
def test_variantes_de_olvidar_todo(texto):
    p = m.interpretar(texto)
    assert p is not None and p.op == "olvidar_todo"


ACTUALIZAR = [
    ("actualiza mi coche a azul", "mi coche", "azul"),
    ("actualiza mi coche: azul", "mi coche", "azul"),
    ("actualiza mi coche: ahora es azul", "mi coche", "azul"),
    ("cambia mi coche a azul", "mi coche", "azul"),
    ("cambia mi coche por azul", "mi coche", "azul"),
    ("corrige mi coche, ahora es azul", "mi coche", "azul"),
    ("ahora mi coche es azul", "mi coche", "azul"),
    ("mi coche ahora es azul", "mi coche", "azul"),
    ("mi coche ya no es rojo, ahora es azul", "mi coche", "azul"),
    ("update my car to blue", "my car", "blue"),
    ("change my car to blue", "my car", "blue"),
    ("my car is now blue", "my car", "blue"),
]


@pytest.mark.parametrize("texto,clave,valor", ACTUALIZAR)
def test_variantes_de_actualizar(texto, clave, valor):
    p = m.interpretar(texto)
    assert p is not None and p.op == "actualizar", texto
    assert (clave, valor) in p.candidatos


def test_recuerda_que_ahora_actualiza_y_tambien_anade():
    p = m.interpretar("recuerda que ahora mi coche es azul")
    assert (p.op, p.clave, p.valor, p.si_existe) == ("guardar", "mi coche", "azul", "actualizar")
    p = m.interpretar("recuerda que mi coche también es azul")
    assert (p.op, p.clave, p.valor, p.si_existe) == ("guardar", "mi coche", "azul", "anadir")
    p = m.interpretar("remember that my car is also blue")
    assert (p.op, p.clave, p.valor, p.si_existe) == ("guardar", "my car", "blue", "anadir")


@pytest.mark.parametrize("texto,clave,valor", [
    ("añade azul a mi coche", "mi coche", "azul"),
    ("agrega Pedro a mis hijos", "mis hijos", "Pedro"),
    ("add blue to my car", "my car", "blue"),
])
def test_variantes_de_anadir(texto, clave, valor):
    p = m.interpretar(texto)
    assert p.op == "anadir" and (clave, valor) in p.candidatos


# =========================================================================== interpretación: lo que NO es una petición
NO_PETICIONES = [
    # conversación normal (antes se "aprendía" de todo esto)
    "hola qué tal",
    "mi furgoneta es una camper",
    "me gusta el café",
    "tengo dos hijos",
    "mi coche es rojo",
    "dame la hora: ahora mismo",
    # negaciones
    "no recuerdes que mi coche es rojo",
    "no quiero que recuerdes mi coche",
    "nunca recuerdes mi coche",
    "no olvides nada",
    "don't remember that my car is red",
    "please do not forget everything",
    "no borres mi coche de tu memoria",
    # preguntas (sobre el comando o sobre el hecho): nunca modifican la memoria
    "¿recuerdas que mi coche es rojo?",
    "¿puedes recordar que mi coche es rojo?",
    "recuerda que mi coche es rojo?",
    "¿olvidas mi coche?",
    "olvida mi coche?",
    "¿qué hace 'recuerda que X es Y'?",
    "do you remember my car?",
    "can you forget my car?",
    # ejemplos entrecomillados
    '"recuerda que mi coche es rojo"',
    "«olvida mi coche»",
    "'remember that my car is red'",
    # peticiones incrustadas en otra frase
    "explica qué significa «recuerda que X es Y»",
    "dime la hora y recuerda que mi coche es rojo",
    "antes de que olvides mi coche dime la hora",
    "cuando te diga recuerda que X es Y, ¿qué harás?",
    "me gustaría que recordaras mejor las cosas",
    "it would be nice if you could remember things",
    # verbos genéricos sin marca de memoria
    "guarda el fichero",
    "aprende python",
    "borra los comentarios del código",
    "elimina la última línea",
    "quita el sombrero",
    "cambia a modo online",
    "pasa a modo offline",
    "save the file",
    "learn how to cook",
    "remove the last line",
    # comandos de otros subsistemas
    "estado", "reset", "salir",
    # pronombres sin referente / preguntas generales
    "olvida eso", "olvídalo", "forget it", "¿qué sabes?", "what do you know?", "qué sabes hacer",
    # otras frases con los mismos verbos
    "recuérdame mañana la cita", "me recuerdas a mi primo", "recuerdas mi coche", "cambia de tema", "ahora es tarde",
    # respuestas a preguntas que no están pendientes
    "1", "sí", "no",
]


@pytest.mark.parametrize("texto", NO_PETICIONES)
def test_frases_normales_no_son_peticiones_de_memoria(texto):
    assert m.interpretar(texto) is None, texto


@pytest.mark.parametrize("texto", [
    "mi coche ahora es azul", "ahora mi coche es azul", "cambia mi coche a azul", "corrige mi coche, ahora es azul",
    "añade azul a mi coche", "my car is now blue", "change my car to blue", "add blue to my car",
    "¿qué sabes de python?", "what do you know about Rust?", "¿qué sabes?",
])
def test_formas_sin_verbo_explicito_solo_cuentan_si_el_dato_existe(mem, texto):
    """'mi coche ahora es azul' es memoria si 'mi coche' está guardado; si no, es
    conversación normal (None) y nunca crea datos ni responde 'no tengo'."""
    assert mem.pedir(texto) is None
    assert not mem.ruta.exists()


def test_interpretar_no_tiene_efectos_secundarios(mem):
    m.interpretar("recuerda que mi coche es rojo")
    m.interpretar("olvida todo")
    assert not mem.ruta.exists() and not m.hay_pendiente()


def test_interpretar_tolera_entradas_raras():
    for raro in (None, 42, "", "   ", "?", "¿", '"', "recuerda", "olvida", "recuerda que", "recuerda que es"):
        p = m.interpretar(raro)
        assert p is None or p.op == "guardar"


# =========================================================================== operaciones
def test_guardar_crea_el_fichero_con_el_formato_esperado(mem):
    r = mem.pedir("recuerda que mi coche es rojo")
    assert r == "Guardado en memoria persistente: «mi coche: rojo»."
    assert mem.yaml() == {"hechos": {"mi coche": "rojo"}, "notas": []}
    assert mem.pedir("no olvides que tengo que llamar a Juan") == "Guardado en memoria persistente (nota): «tengo que llamar a Juan»."
    assert mem.yaml() == {"hechos": {"mi coche": "rojo"}, "notas": ["tengo que llamar a Juan"]}


def test_guardar_conserva_mayusculas_del_valor_y_acentos_de_la_clave(mem):
    mem.pedir("Recuerda que Mi Cumpleaños es el 3 de Mayo")
    assert mem.hechos() == {"mi cumpleaños": "el 3 de Mayo"}
    # la misma clave sin acento / con mayúsculas es el mismo dato
    assert mem.pedir("recuerda que MI CUMPLEANOS es el 3 de mayo").startswith("Ya lo tenía guardado")
    assert mem.hechos() == {"mi cumpleaños": "el 3 de Mayo"}


def test_duplicado_exacto_no_reescribe_el_fichero(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mtime = os.stat(mem.ruta).st_mtime_ns
    assert mem.pedir("recuerda que mi coche es Rojo") == "Ya lo tenía guardado: «mi coche: rojo». No he cambiado nada."
    assert os.stat(mem.ruta).st_mtime_ns == mtime


def test_conflicto_pregunta_y_sustituye(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi ciudad es Bilbao")
    r = mem.pedir("recuerda que mi coche es azul")
    assert r.startswith("Ya tengo guardado «mi coche: rojo». ¿Sustituyo el valor por «azul» (1) o lo añado como otro valor (2)?")
    assert mem.hechos() == {"mi coche": "rojo", "mi ciudad": "Bilbao"} and m.hay_pendiente()
    assert mem.pedir("1") == "Actualizado: «mi coche» pasa de «rojo» a «azul»."
    assert mem.hechos() == {"mi coche": "azul", "mi ciudad": "Bilbao"}   # el dato no relacionado sigue intacto
    assert not m.hay_pendiente()


def test_conflicto_pregunta_y_anade(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi coche es azul")
    assert mem.pedir("añádelo") == "Añadido: ahora «mi coche: rojo, azul»."
    assert mem.yaml()["hechos"] == {"mi coche": ["rojo", "azul"]}
    assert mem.pedir("recuerda que mi coche es azul").startswith("Ya lo tenía guardado: «mi coche: rojo, azul»")


def test_conflicto_cancelado_no_cambia_nada(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi coche es azul")
    assert mem.pedir("no") == "De acuerdo, no cambio nada."
    assert mem.hechos() == {"mi coche": "rojo"}
    mem.pedir("recuerda que mi coche es verde")
    assert mem.pedir("¿qué hora es?") is None          # otro mensaje cualquiera cancela la pregunta...
    assert not m.hay_pendiente()
    assert mem.pedir("1") is None                        # ...y la respuesta tardía ya no hace nada
    assert mem.hechos() == {"mi coche": "rojo"}


def test_actualizar_y_anadir_explicitos(mem):
    mem.pedir("recuerda que mi coche es rojo")
    assert mem.pedir("actualiza mi coche a azul") == "Actualizado: «mi coche» pasa de «rojo» a «azul»."
    assert mem.pedir("mi coche ahora es verde") == "Actualizado: «mi coche» pasa de «azul» a «verde»."
    assert mem.pedir("recuerda que ahora mi coche es negro") == "Actualizado: «mi coche» pasa de «verde» a «negro»."
    assert mem.pedir("update my car to white") == "No tengo ningún dato guardado sobre «my car». Para guardarlo: «recuerda que my car es white»."
    assert mem.pedir("change my car to white") is None                   # verbo genérico y 'my car' no existe -> conversación
    assert mem.pedir("actualiza mi moto a roja") == "No tengo ningún dato guardado sobre «mi moto». Para guardarlo: «recuerda que mi moto es roja»."
    assert mem.pedir("añade blanco a mi coche") == "Añadido: ahora «mi coche: negro, blanco»."
    assert mem.pedir("recuerda que mi coche también es gris") == "Añadido: ahora «mi coche: negro, blanco, gris»."
    assert mem.hechos() == {"mi coche": ["negro", "blanco", "gris"]}


def test_actualizar_elige_el_corte_que_coincide_con_un_dato(mem):
    mem.pedir("recuerda que mi viaje a Roma es en junio")
    assert mem.pedir("cambia mi viaje a Roma a julio") == "Actualizado: «mi viaje a roma» pasa de «en junio» a «julio»."


def test_olvidar_por_clave_por_contencion_y_por_valor(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi perro se llama Rex")
    mem.pedir("recuerda que tengo que llamar a Juan")
    assert mem.pedir("olvida el coche") == "Olvidado: «mi coche: rojo». Ya no lo tendré en cuenta."
    assert mem.pedir("olvida lo de Rex") == "Olvidado: «mi perro: Rex». Ya no lo tendré en cuenta."
    assert mem.pedir("olvida que tengo que llamar a Juan") == "Olvidado: «nota: tengo que llamar a Juan». Ya no lo tendré en cuenta."
    assert mem.yaml() == {"hechos": {}, "notas": []}


def test_olvidar_un_valor_de_una_lista(mem):
    mem.pedir("recuerda que mis hijos son Ana")
    mem.pedir("añade Luis a mis hijos")
    assert mem.pedir("olvida que mis hijos son Ana") == "Olvidado «Ana» de «mis hijos»; queda «mis hijos: Luis»."
    assert mem.pedir("olvida que mis hijos son Pedro") == ("Tengo «mis hijos: Luis», no «Pedro». No he cambiado nada. "
                                                           "Para borrar el dato completo: «olvida mis hijos».")
    assert mem.pedir("olvida que mis hijos son Luis") == "Olvidado: «mis hijos: Luis». Ya no lo tendré en cuenta."
    assert mem.hechos() == {}


def test_olvidar_inexistente_informa_sin_tocar_nada(mem):
    mem.pedir("recuerda que mi coche es rojo")
    r = mem.pedir("olvida mi moto")
    assert r == "No tengo ningún dato guardado sobre «mi moto». Puedes ver todo lo que recuerdo con «¿qué recuerdas?»."
    assert mem.hechos() == {"mi coche": "rojo"}
    assert "«reset»" in mem.pedir("olvida la conversación")


def test_olvidar_ambiguo_pregunta_cual(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    mem.pedir("recuerda que mi moto es negra")
    r = mem.pedir("olvida coche")
    assert r.startswith("Hay varios datos que coinciden:\n  1) mi coche: rojo\n  2) el coche de ana: azul\n¿Cuál olvido?")
    assert mem.hechos() == {"mi coche": "rojo", "el coche de ana": "azul", "mi moto": "negra"}
    assert mem.pedir("2") == "Olvidado: «el coche de ana: azul». Ya no lo tendré en cuenta."
    assert mem.hechos() == {"mi coche": "rojo", "mi moto": "negra"}
    mem.pedir("recuerda que el coche de Ana es azul")
    mem.pedir("olvida coche")
    assert mem.pedir("todos") == "Olvidado: «mi coche: rojo»; «el coche de ana: azul». Ya no lo tendré en cuenta."
    assert mem.hechos() == {"mi moto": "negra"}


def test_actualizar_ambiguo_pregunta_cual(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    assert "¿Cuál actualizo?" in mem.pedir("actualiza coche a verde")
    assert mem.pedir("1") == "Actualizado: «mi coche» pasa de «rojo» a «verde»."
    assert mem.hechos() == {"mi coche": "verde", "el coche de ana": "azul"}


def test_olvidar_todo_requiere_confirmacion(mem):
    assert mem.pedir("olvida todo") == "La memoria persistente ya está vacía."
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que tengo que llamar a Juan")
    assert "¿Confirmas?" in mem.pedir("forget everything")
    assert mem.pedir("mejor no") is None and mem.hechos() == {"mi coche": "rojo"}
    assert "¿Confirmas?" in mem.pedir("borra toda tu memoria")
    assert mem.pedir("sí") == "Memoria persistente vaciada (2 datos olvidados)."
    assert mem.yaml() == {"hechos": {}, "notas": []}


def test_peticion_de_guardar_sin_contenido_pide_aclaracion(mem):
    r = mem.pedir("recuerda esto")
    assert r.startswith("¿Qué quieres que recuerde?") and "recuerda que X es Y" in r
    assert mem.pedir("acuérdate de mi cumpleaños").startswith("¿Qué quieres que recuerde sobre «mi cumpleaños»?")
    assert mem.pedir("remember the milk").startswith("¿Qué quieres que recuerde sobre «the milk»?")
    assert not mem.ruta.exists()


def test_consultar_y_listar(mem):
    assert mem.pedir("¿qué recuerdas?") == ("No tengo ningún dato en la memoria persistente. "
                                           "Dímelo como «recuerda que X es Y» (por ejemplo, «recuerda que mi coche es rojo»).")
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    mem.pedir("recuerda que tengo que llamar a Juan")
    assert mem.pedir("¿qué sabes de mi coche?") == "Sobre «mi coche» tengo guardado: «mi coche: rojo»."
    assert mem.pedir("what do you remember about juan?") == "Sobre «juan» tengo guardado: «nota: tengo que llamar a Juan»."
    assert mem.pedir("¿qué recuerdas del coche?") is None             # 'del' no es un conector reconocido
    assert mem.pedir("¿qué recuerdas sobre coche?") == ("Sobre «coche» tengo guardado:\n- mi coche: rojo\n- el coche de ana: azul")
    assert mem.pedir("¿qué recuerdas de mi moto?") == "No tengo ningún dato guardado sobre «mi moto». Puedes ver todo lo que recuerdo con «¿qué recuerdas?»."
    assert mem.pedir("¿qué sabes de mi moto?") is None                # 'sabes' sin dato: pregunta general para el modelo
    assert mem.pedir("ver memoria") == "Memoria persistente (3 datos):\n- mi coche: rojo\n- el coche de ana: azul\n- nota: tengo que llamar a Juan"


# =========================================================================== contexto para el motor y fichero
def test_contexto_para_el_motor(mem):
    assert m.get_memory_context() == ""                 # sin fichero: sin mensaje de memoria
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mis hijos son Ana")
    mem.pedir("añade Luis a mis hijos")
    mem.pedir("recuerda que tengo que llamar a Juan")
    ctx = m.get_memory_context()
    assert ctx.startswith(m.CABECERA_MEMORIA)
    assert ctx.endswith("- mi coche: rojo\n- mis hijos: Ana, Luis\n- nota: tengo que llamar a Juan")
    mem.pedir("olvida mis hijos")
    assert "hijos" not in m.get_memory_context() and "- mi coche: rojo" in m.get_memory_context()


def test_formato_antiguo_se_migra_y_las_otras_secciones_se_conservan(mem):
    mem.ruta.write_text(
        "aprendido_durante_sesion:\n  mi coche: rojo\n"
        "vida_personal:\n  pareja:\n    nombre: Ana\n  vehiculo: una camper\n"
        "entorno:\n  sistemas_operativos: [ubuntu, windows]\n", encoding="utf-8")
    assert mem.hechos() == {"mi coche": "rojo"}
    ctx = m.get_memory_context()
    assert "- mi coche: rojo" in ctx and ctx.count("mi coche") == 1      # antes aparecía duplicado
    assert "Nombre es Ana." in ctx and "Vehiculo es una camper." in ctx
    assert "Sistemas_operativos incluye: ubuntu, windows." in ctx
    assert mem.pedir("recuerda que mi ciudad es Bilbao").startswith("Guardado")
    datos = mem.yaml()
    assert datos["hechos"] == {"mi coche": "rojo", "mi ciudad": "Bilbao"}
    assert "aprendido_durante_sesion" not in datos
    assert datos["vida_personal"] == {"pareja": {"nombre": "Ana"}, "vehiculo": "una camper"}
    assert datos["entorno"] == {"sistemas_operativos": ["ubuntu", "windows"]}


def test_fichero_vacio_o_ausente_se_trata_como_memoria_vacia(mem):
    assert mem.hechos() == {} and m.get_memory_context() == ""
    mem.ruta.write_text("", encoding="utf-8")
    assert mem.hechos() == {} and m.get_memory_context() == ""
    assert mem.pedir("recuerda que mi coche es rojo").startswith("Guardado")
    assert mem.yaml() == {"hechos": {"mi coche": "rojo"}, "notas": []}


@pytest.mark.parametrize("contenido", [
    "hechos: [esto, no, es, un, mapa\n",           # YAML inválido
    "- una\n- lista\n",                               # válido pero no es un mapa
    "hechos: [lista]\n",                              # sección con el tipo equivocado
    "notas: {a: b}\n",
    "\xff\xfe binario",
])
def test_fichero_corrupto_no_se_sobrescribe_y_no_rompe_el_contexto(mem, contenido, capsys):
    mem.ruta.write_bytes(contenido.encode("utf-8", "surrogateescape") if isinstance(contenido, str) else contenido)
    original = mem.ruta.read_bytes()
    assert m.get_memory_context() == ""
    assert "Aviso: memoria persistente ilegible" in capsys.readouterr().out
    r = mem.pedir("recuerda que mi coche es rojo")
    assert r.startswith("No he podido usar la memoria persistente") and "No se ha modificado nada" in r
    assert mem.pedir("olvida todo").startswith("No he podido usar la memoria persistente")
    assert mem.pedir("¿qué recuerdas?").startswith("No he podido usar la memoria persistente")
    assert mem.ruta.read_bytes() == original
    assert not any(f.startswith(".user_profile-") for f in os.listdir(mem.ruta.parent))   # sin temporales huérfanos
    with pytest.raises(m.MemoriaCorrupta):
        m.listar_hechos()


def test_fallo_de_escritura_no_destruye_los_datos_ni_informa_exito(mem):
    mem.pedir("recuerda que mi coche es rojo")
    original = mem.ruta.read_bytes()

    def fallo(*a, **k):
        raise OSError("disco lleno")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(m.os, "replace", fallo)
        r = mem.pedir("recuerda que mi ciudad es Bilbao")
    assert r.startswith("No he podido usar la memoria persistente (no se ha podido escribir") and "disco lleno" in r
    assert "Guardado" not in r
    assert mem.ruta.read_bytes() == original
    assert not any(f.startswith(".user_profile-") for f in os.listdir(mem.ruta.parent))
    assert mem.hechos() == {"mi coche": "rojo"}
    assert mem.pedir("recuerda que mi ciudad es Bilbao").startswith("Guardado")   # recuperado: vuelve a funcionar


def test_directorio_de_solo_lectura(mem, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("root ignora los permisos de directorio")
    mem.pedir("recuerda que mi coche es rojo")
    original = mem.ruta.read_bytes()
    os.chmod(mem.ruta.parent, 0o500)
    try:
        r = mem.pedir("recuerda que mi ciudad es Bilbao")
        assert r.startswith("No he podido usar la memoria persistente") and "Guardado" not in r
        assert mem.ruta.read_bytes() == original
    finally:
        os.chmod(mem.ruta.parent, 0o700)


def test_la_verificacion_tras_escribir_detecta_escrituras_incompletas(mem, monkeypatch):
    mem.pedir("recuerda que mi coche es rojo")
    monkeypatch.setattr(m, "_guardar_perfil", lambda data: None)       # "escribe" sin escribir
    r = mem.pedir("recuerda que mi ciudad es Bilbao")
    assert r.startswith("No he podido usar la memoria persistente") and "verificación" in r
    assert mem.hechos() == {"mi coche": "rojo"}


def test_el_fichero_se_crea_con_directorios_intermedios(perfil_temporal, monkeypatch):
    ruta = perfil_temporal.parent / "config" / "data" / "user_profile.yaml"
    monkeypatch.setattr(m, "MEMORY_PATH", str(ruta))
    assert m.procesar_peticion("recuerda que mi coche es rojo").startswith("Guardado")
    assert yaml.safe_load(ruta.read_text(encoding="utf-8")) == {"hechos": {"mi coche": "rojo"}, "notas": []}


def test_historial_ilegible_se_aparta_en_vez_de_sobrescribirse(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(m, "SESSION_FILE", str(tmp_path / "historial.json"))
    (tmp_path / "historial.json").write_text("{corrupto", encoding="utf-8")
    assert m.load_full_history() == []
    assert "apartado" in capsys.readouterr().out
    respaldos = [f for f in os.listdir(tmp_path) if f.startswith("historial.json.corrupto-")]
    assert len(respaldos) == 1 and (tmp_path / respaldos[0]).read_text(encoding="utf-8") == "{corrupto"
    assert (tmp_path / "historial.json").read_text(encoding="utf-8") == "[]"


def test_la_memoria_no_usa_la_red(mem, monkeypatch):
    """Todo el procesamiento es local: cualquier intento de abrir un socket sería un fallo."""
    import socket

    def prohibido(*a, **k):
        raise AssertionError("la memoria persistente no debe abrir sockets")

    monkeypatch.setattr(socket, "socket", prohibido)
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("¿qué sabes de mi coche?")
    mem.pedir("actualiza mi coche a azul")
    mem.pedir("olvida mi coche")
    assert m.get_memory_context() == ""
