"""
Memoria persistente (fase 7 "aprendizaje local natural") — MIGRADO a la API actual.

Origen: tests/test_memoria.py suministrado por la revisión externa (SHA-256
722c6d27b49d3be337931a5d54fc28c835a33f5957595220c21086e0cc077ac9), escrito para
una API anterior (memory_engine.interpretar / procesar_peticion / hay_pendiente,
listar_hechos() -> (hechos, notas), MemoriaCorrupta, CABECERA_MEMORIA,
_guardar_perfil, formato {hechos, notas} en user_profile.yaml). Con esa API
daba 172 fallos y 41 errores (APIs eliminadas y fixture perfil_temporal ausente).

Migración (todas las entradas originales se conservan):
- API actual: core.memory_commands.procesar_comando_memoria(texto) -> str | None
  y el almacén de hechos de core.memory_engine (config/data/facts.yaml, esquema
  versionado; claves normalizadas sin artículo ni posesivo de 1.ª persona:
  "mi coche" -> "coche", "my car" -> "car").
- [RETENIDO]  mismo escenario y mismo resultado; sólo cambia la forma de
  observarlo (API, clave normalizada, texto del mensaje, fichero).
- [REESCRITO] misma entrada, pero el resultado esperado original contradice un
  requisito explícito posterior de la fase 7 (intención explícita de memoria,
  rechazo de citas/ejemplos, negaciones, aclaraciones sin estado, un valor por
  dato, sin notas libres, claves completas con propiedad). El test comprueba
  el comportamiento requerido actual para esa misma entrada.
Cada test indica su origen y clasificación.
"""
import os

import pytest
import yaml

from core import memory_engine as m
from core.memory_commands import procesar_comando_memoria


@pytest.fixture
def mem(perfil_temporal):
    """API mínima sobre el almacenamiento temporal: pedir(texto) -> respuesta,
    hechos() {clave_normalizada: valor}, ruta (facts.yaml), perfil (user_profile.yaml)."""
    class Mem:
        perfil = perfil_temporal
        ruta = perfil_temporal.parent / "facts.yaml"

        @staticmethod
        def pedir(texto):
            return procesar_comando_memoria(texto)

        @staticmethod
        def hechos():
            return {norma: e["valor"] for norma, e in m.cargar_hechos().items()}

        @staticmethod
        def yaml():
            return yaml.safe_load(Mem.ruta.read_text(encoding="utf-8"))

    return Mem


def _ok(r):
    return r is not None and (r.startswith("Hecho guardado") or r.startswith("Fact stored"))


# =========================================================================== interpretación: variaciones aceptadas
# [original: test_variantes_de_guardar, 40 casos] 33 RETENIDOS (clave normalizada), 7 REESCRITOS (abajo).
GUARDAR = [
    ("recuerda que mi coche es rojo", "coche", "rojo"),
    ("Recuerda que mi coche es ROJO.", "coche", "ROJO"),
    ("recuerda: mi coche es rojo", "coche", "rojo"),
    ("recuerda mi coche es rojo", "coche", "rojo"),
    ("recuerda esto: mi coche es rojo", "coche", "rojo"),
    ("aprende: mi coche es rojo", "coche", "rojo"),
    ("aprende que mi coche es rojo", "coche", "rojo"),
    ("memoriza que mi coche es rojo", "coche", "rojo"),
    ("acuérdate de que mi coche es rojo", "coche", "rojo"),
    ("no olvides que mi coche es rojo", "coche", "rojo"),
    ("no te olvides de que mi coche es rojo", "coche", "rojo"),
    ("quiero que recuerdes que mi coche es rojo", "coche", "rojo"),
    ("me gustaría que recordaras que mi coche es rojo", "coche", "rojo"),
    ("puedes recordar que mi coche es rojo", "coche", "rojo"),
    ("B.A.I, recuerda que mi coche es rojo", "coche", "rojo"),
    ("bai por favor recuerda que mi coche es rojo, por favor!", "coche", "rojo"),
    ("Recuerda, por favor, que mi coche es rojo", "coche", "rojo"),
    ("  recuerda   que  mi coche   es rojo  ", "coche", "rojo"),
    ("recuerda que mi coche = rojo", "coche", "rojo"),
    ("recuerda que mi coche: rojo", "coche", "rojo"),
    ("recuerda que mis hijos son Ana y Luis", "hijos", "Ana y Luis"),
    ("recuerda que mi perro se llama Rex", "perro", "Rex"),
    ("recuerda que mi coche está en el garaje", "coche", "en el garaje"),
    ("recuerda que mi cumpleaños es el 3 de mayo", "cumpleanos", "el 3 de mayo"),
    ("remember that my car is red", "car", "red"),
    ("Remember: my car is red.", "car", "red"),
    ("remember my car is red", "car", "red"),
    ("please remember that my car is red", "car", "red"),
    ("don't forget that my car is red", "car", "red"),
    ("do not forget my car is red", "car", "red"),
    ("I want you to remember that my car is red", "car", "red"),
    ("could you please remember that my car is red", "car", "red"),
    ("remember that my kids are Ana and Luis", "kids", "Ana and Luis"),
]


@pytest.mark.parametrize("texto,clave,valor", GUARDAR)
def test_variantes_de_guardar(mem, texto, clave, valor):
    r = mem.pedir(texto)
    assert _ok(r), (texto, r)
    assert mem.hechos() == {clave: valor}


# [REESCRITO x7, original: test_variantes_de_guardar] Requisito: los verbos genéricos (anota, apunta,
# guarda, graba, note, write down) sólo guardan con un objeto de memoria explícito, y los hechos entre
# comillas son ejemplos. La misma entrada no escribe nada; la forma explícita equivalente sí guarda.
GUARDAR_GENERICO = [
    ("anota que mi coche es rojo", "anota en tu memoria que mi coche es rojo"),
    ("apunta que mi coche es rojo", "apunta en tu memoria que mi coche es rojo"),
    ("guarda que mi coche es rojo", "guarda en tu memoria que mi coche es rojo"),
    ("graba esto: mi coche es rojo", "graba en memoria: mi coche es rojo"),
    ("note that my car is red", "note in your memory that my car is red"),
    ("write down that my car is red", "write down as a fact that my car is red"),
]


@pytest.mark.parametrize("texto,explicito", GUARDAR_GENERICO)
def test_guardar_con_verbo_generico_exige_objeto_de_memoria(mem, texto, explicito):
    assert mem.pedir(texto) is None
    assert not mem.ruta.exists()
    assert _ok(mem.pedir(explicito))
    assert list(mem.hechos().values()) in (["rojo"], ["red"])


def test_guardar_con_hecho_entrecomillado_se_rechaza(mem):
    """[REESCRITO, original: test_variantes_de_guardar «mi coche» es 'rojo'] Requisito: citas = ejemplos."""
    r = mem.pedir("recuerda que «mi coche» es 'rojo'")
    assert "comillas" in r and not mem.ruta.exists()
    assert _ok(mem.pedir("recuerda que mi coche es rojo"))


# [REESCRITO x5, original: test_frases_sin_clave_valor_se_guardan_como_nota] Requisito: sin notas libres;
# una petición sin clave/valor clara se aclara localmente sin escribir (y nunca crea una clave falsa).
NOTAS = [
    ("recuerda que tengo que llamar a Juan", "recuerda que"),
    ("no olvides que me gusta el café solo", "recuerda que"),
    ("recuerda que no como carne", "negación"),
    ("remember that I don't eat meat", "remember that"),
    ("recuerda que tengo que llamar a Juan porque es su cumpleaños", "recuerda que"),
]


@pytest.mark.parametrize("texto,pista", NOTAS)
def test_frases_sin_clave_valor_piden_aclaracion_sin_escribir(mem, texto, pista):
    r = mem.pedir(texto)
    assert r is not None and pista in r
    assert not mem.ruta.exists()


# [original: test_variantes_de_consultar, 11 casos] RETENIDOS: todas consultan el dato completo.
CONSULTAR = [
    ("¿qué sabes de mi coche?", "rojo"),
    ("que sabes sobre mi coche", "rojo"),
    ("¿Qué recuerdas acerca de mi coche?", "rojo"),
    ("dime qué sabes de mi coche", "rojo"),
    ("¿qué tienes guardado sobre mi coche?", "rojo"),
    ("¿qué has guardado de mi coche?", "rojo"),
    ("B.A.I, ¿qué recuerdas de mi coche?", "rojo"),
    ("what do you know about my car?", "red"),
    ("What do you remember about my car", "red"),
    ("what have you saved about my car?", "red"),
    ("tell me what you remember about my car", "red"),
]


@pytest.mark.parametrize("texto,valor", CONSULTAR)
def test_variantes_de_consultar(mem, texto, valor):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    antes = mem.ruta.read_bytes()
    r = mem.pedir(texto)
    assert r is not None and valor in r and r.startswith(("Sí, lo recuerdo", "Yes, I remember"))
    assert mem.ruta.read_bytes() == antes                     # consultar nunca escribe


# [original: test_variantes_de_listar, 12 casos] 11 RETENIDOS; "ver memoria" REESCRITO (abajo).
@pytest.mark.parametrize("texto", [
    "¿qué recuerdas?", "qué sabes de mí", "¿qué has aprendido?", "what do you remember?", "what do you know about me?",
    "muestra tu memoria", "muéstrame lo que sabes de mí", "lista los hechos", "show me your memory",
    "list facts", "enséñame la memoria persistente",
])
def test_variantes_de_listar(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi perro se llama Rex")
    r = mem.pedir(texto)
    assert r is not None and "- coche: rojo" in r and "- perro: Rex" in r


def test_ver_memoria_sigue_siendo_el_comando_de_historial_de_la_cli(mem):
    """[REESCRITO, original: test_variantes_de_listar "ver memoria"] "ver memoria" es un comando
    existente de la CLI (muestra el historial, README); no se reasigna. Los hechos se listan con "ver hechos"."""
    mem.pedir("recuerda que mi coche es rojo")
    assert mem.pedir("ver memoria") is None
    assert "- coche: rojo" in mem.pedir("ver hechos")


# [original: test_variantes_de_olvidar, 18 casos] RETENIDOS: olvidan el dato completo y nada más.
OLVIDAR = [
    "olvida mi coche", "Olvida lo de mi coche.", "olvídate de mi coche", "olvida lo que sabes de mi coche",
    "olvida todo lo que sabes sobre mi coche", "borra mi coche de tu memoria", "elimina lo que sabes de mi coche",
    "quita el dato de mi coche de la memoria", "deja de recordar mi coche", "no recuerdes más mi coche",
    "B.A.I, por favor, olvida mi coche", "olvida, por favor, mi coche",
    "forget my car", "forget about my car", "forget everything about my car", "delete my car from your memory",
    "remove what you know about my car", "stop remembering my car",
]


@pytest.mark.parametrize("texto", OLVIDAR)
def test_variantes_de_olvidar(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    mem.pedir("recuerda que mi perro se llama Rex")
    r = mem.pedir(texto)
    assert r.startswith(("Olvidado: coche", "Forgotten: car")), (texto, r)
    restantes = mem.hechos()
    assert restantes["perro"] == "Rex" and len(restantes) == 2      # sólo se borra el dato pedido


# [original: test_olvidar_un_valor_concreto, 3 casos] RETENIDOS.
@pytest.mark.parametrize("texto,clave", [
    ("olvida que mi coche es rojo", "coche"), ("olvídate de que mi coche es rojo", "coche"), ("forget that my car is red", "car"),
])
def test_olvidar_un_valor_concreto(mem, texto, clave):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    assert mem.pedir(texto).startswith(("Olvidado", "Forgotten"))
    assert clave not in mem.hechos() and len(mem.hechos()) == 1


# [original: test_variantes_de_olvidar_todo, 8 casos] RETENIDOS: todas son "olvidar todo", que pide
# confirmación y no borra nada por sí sola.
@pytest.mark.parametrize("texto", [
    "olvida todo", "olvida todo lo que sabes de mí", "olvida lo que sabes de mí", "borra toda tu memoria", "olvídate de todo",
    "forget everything", "forget everything about me", "erase your memory",
])
def test_variantes_de_olvidar_todo(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    antes = mem.ruta.read_bytes()
    r = mem.pedir(texto)
    assert "confirmo" in r or "confirm" in r
    assert mem.ruta.read_bytes() == antes


# [original: test_variantes_de_actualizar, 12 casos] REESCRITOS: el requisito de intención explícita
# exige objeto de memoria para verbos genéricos ("actualiza/cambia/corrige/update/change") y un verbo de
# memoria para las formas sin verbo ("ahora mi coche es azul"). La entrada original no toca nada; la
# forma explícita equivalente actualiza al mismo valor.
ACTUALIZAR = [
    ("actualiza mi coche a azul", "actualiza en tu memoria mi coche a azul", "coche", "azul"),
    ("actualiza mi coche: azul", "actualiza en tu memoria mi coche: azul", "coche", "azul"),
    ("actualiza mi coche: ahora es azul", "actualiza en tu memoria mi coche: ahora es azul", "coche", "azul"),
    ("cambia mi coche a azul", "cambia en tu memoria mi coche a azul", "coche", "azul"),
    ("cambia mi coche por azul", "cambia en tu memoria mi coche por azul", "coche", "azul"),
    ("corrige mi coche, ahora es azul", "corrige tu memoria: mi coche, ahora es azul", "coche", "azul"),
    ("ahora mi coche es azul", "recuerda que ahora mi coche es azul", "coche", "azul"),
    ("mi coche ahora es azul", "recuerda que mi coche ahora es azul", "coche", "azul"),
    ("mi coche ya no es rojo, ahora es azul", "recuerda que ahora mi coche es azul", "coche", "azul"),
    ("update my car to blue", "update in your memory my car to blue", "car", "blue"),
    ("change my car to blue", "change the fact my car to blue", "car", "blue"),
    ("my car is now blue", "remember that my car is now blue", "car", "blue"),
]


@pytest.mark.parametrize("texto,explicito,clave,valor", ACTUALIZAR)
def test_variantes_de_actualizar(mem, texto, explicito, clave, valor):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    antes = mem.hechos()
    assert mem.pedir(texto) is None and mem.hechos() == antes
    r = mem.pedir(explicito)
    assert r.startswith(("Actualizado", "Updated")), (explicito, r)
    assert mem.hechos()[clave] == valor and len(mem.hechos()) == 2


def test_recuerda_que_ahora_actualiza_y_tambien_anade(mem):
    """[original: test_recuerda_que_ahora_actualiza_y_tambien_anade] "ahora": RETENIDO (actualiza).
    "también"/"also": REESCRITO (un valor por dato: se aclara sin cambiar nada ni crear claves falsas)."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    assert mem.pedir("recuerda que ahora mi coche es azul").startswith("Actualizado")
    assert mem.hechos() == {"coche": "azul", "car": "red"}
    assert "un valor por dato" in mem.pedir("recuerda que mi coche también es azul")
    assert "single value" in mem.pedir("remember that my car is also blue")
    assert mem.hechos() == {"coche": "azul", "car": "red"}


@pytest.mark.parametrize("texto", ["añade azul a mi coche", "agrega Pedro a mis hijos", "add blue to my car"])
def test_variantes_de_anadir(mem, texto):
    """[REESCRITO x3, original: test_variantes_de_anadir] Requisitos: un valor por dato e intención
    explícita; "añadir" sin verbo de memoria es conversación normal y no modifica nada."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mis hijos son Ana")
    antes = mem.ruta.read_bytes()
    assert mem.pedir(texto) is None
    assert mem.ruta.read_bytes() == antes


# =========================================================================== interpretación: lo que NO es una petición
# [original: test_frases_normales_no_son_peticiones_de_memoria, 57 casos] En TODOS se retiene el
# escenario esencial: la memoria no se modifica. 45 RETENIDOS además devuelven None (conversación
# normal). 12 REESCRITOS: requisitos posteriores piden responder localmente sin escribir a negaciones
# de peticiones de memoria, a peticiones reconocibles pero incompletas y a consultas de solo lectura.
NO_PETICIONES = [
    "hola qué tal", "mi furgoneta es una camper", "me gusta el café", "tengo dos hijos", "mi coche es rojo",
    "dame la hora: ahora mismo",
    "no borres mi coche de tu memoria",
    "¿puedes recordar que mi coche es rojo?", "recuerda que mi coche es rojo?", "¿olvidas mi coche?", "olvida mi coche?",
    "¿qué hace 'recuerda que X es Y'?", "can you forget my car?",
    '"recuerda que mi coche es rojo"', "«olvida mi coche»", "'remember that my car is red'",
    "explica qué significa «recuerda que X es Y»", "dime la hora y recuerda que mi coche es rojo",
    "antes de que olvides mi coche dime la hora", "cuando te diga recuerda que X es Y, ¿qué harás?",
    "me gustaría que recordaras mejor las cosas", "it would be nice if you could remember things",
    "guarda el fichero", "aprende python", "borra los comentarios del código", "elimina la última línea", "quita el sombrero",
    "cambia a modo online", "pasa a modo offline", "save the file", "learn how to cook", "remove the last line",
    "estado", "reset", "salir",
    "¿qué sabes?", "what do you know?", "qué sabes hacer",
    "recuérdame mañana la cita", "me recuerdas a mi primo", "cambia de tema", "ahora es tarde",
    "1", "sí", "no",
]
# Respuesta local sin escribir (requisitos de negaciones, peticiones incompletas y consultas).
NO_PETICIONES_CON_RESPUESTA_LOCAL = [
    ("no recuerdes que mi coche es rojo", "no guardaré"),
    ("no quiero que recuerdes mi coche", "no guardaré"),
    ("nunca recuerdes mi coche", "no guardaré"),
    ("don't remember that my car is red", "won't store"),
    ("no olvides nada", "recuerda que"),
    ("please do not forget everything", "remember that"),
    ("¿recuerdas que mi coche es rojo?", "coche es rojo"),
    ("do you remember my car?", "nothing stored"),
    ("recuerdas mi coche", "coche es rojo"),
    ("olvida eso", "olvide exactamente"),
    ("olvídalo", "olvide exactamente"),
    ("forget it", "exactly should I forget"),
]


@pytest.mark.parametrize("texto", NO_PETICIONES)
def test_frases_normales_no_son_peticiones_de_memoria(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    antes = mem.ruta.read_bytes()
    assert mem.pedir(texto) is None, texto
    assert mem.ruta.read_bytes() == antes


@pytest.mark.parametrize("texto,pista", NO_PETICIONES_CON_RESPUESTA_LOCAL)
def test_negaciones_incompletas_y_consultas_responden_sin_escribir(mem, texto, pista):
    mem.pedir("recuerda que mi coche es rojo")
    antes = mem.ruta.read_bytes()
    r = mem.pedir(texto)
    assert r is not None and pista in r, (texto, r)
    assert mem.ruta.read_bytes() == antes


@pytest.mark.parametrize("texto", [
    "mi coche ahora es azul", "ahora mi coche es azul", "cambia mi coche a azul", "corrige mi coche, ahora es azul",
    "añade azul a mi coche", "my car is now blue", "change my car to blue", "add blue to my car",
    "¿qué sabes de python?", "what do you know about Rust?", "¿qué sabes?",
])
def test_formas_sin_verbo_explicito_solo_cuentan_si_el_dato_existe(mem, texto):
    """[RETENIDO x11] Sin el dato guardado: conversación normal (None) y nunca crea datos.
    [Ampliado por el requisito de intención explícita] con el dato guardado tampoco lo cambian."""
    assert mem.pedir(texto) is None
    assert not mem.ruta.exists()
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    antes = mem.ruta.read_bytes()
    assert mem.pedir(texto) is None
    assert mem.ruta.read_bytes() == antes


def test_interpretar_no_tiene_efectos_secundarios(mem):
    """[REESCRITO, original usaba interpretar()/hay_pendiente()] Sin interpretar() separado: las
    peticiones que sólo piden confirmación o aclaración no crean ficheros ni dejan estado pendiente."""
    assert mem.pedir("recuerda esto").startswith("No he entendido")
    assert mem.pedir("olvida todo").startswith("No había")
    assert not mem.ruta.exists()
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("olvida todo")                                  # pide confirmación...
    assert mem.pedir("sí") is None and mem.pedir("1") is None  # ...y no queda nada pendiente
    assert mem.hechos() == {"coche": "rojo"}


def test_interpretar_tolera_entradas_raras(mem):
    """[RETENIDO] Entradas raras: nunca fallan ni escriben; como mucho piden aclaración."""
    for raro in (None, 42, "", "   ", "?", "¿", '"', "recuerda", "olvida", "recuerda que", "recuerda que es"):
        r = mem.pedir(raro)
        assert r is None or isinstance(r, str)
    assert not mem.ruta.exists()


# =========================================================================== operaciones
def test_guardar_crea_el_fichero_con_el_formato_esperado(mem):
    """[REESCRITO] Formato actual: facts.yaml versionado (no {hechos, notas} en el perfil); las notas
    libres no existen: la segunda petición pide aclaración y no cambia el fichero."""
    r = mem.pedir("recuerda que mi coche es rojo")
    assert r == "Hecho guardado: coche = rojo. Lo recordaré entre sesiones."
    datos = mem.yaml()
    assert datos["version"] == 1 and set(datos) == {"version", "hechos"}
    assert {k: (e["clave"], e["valor"]) for k, e in datos["hechos"].items()} == {"coche": ("coche", "rojo")}
    antes = mem.ruta.read_bytes()
    assert mem.pedir("no olvides que tengo que llamar a Juan").startswith("No he entendido")
    assert mem.ruta.read_bytes() == antes


def test_guardar_conserva_mayusculas_del_valor_y_acentos_de_la_clave(mem):
    """[RETENIDO]"""
    mem.pedir("Recuerda que Mi Cumpleaños es el 3 de Mayo")
    assert mem.hechos() == {"cumpleanos": "el 3 de Mayo"}
    assert m.listar_hechos() == [("Cumpleaños", "el 3 de Mayo")]          # acentos y mayúsculas visibles
    # la misma clave sin acento / con mayúsculas es el mismo dato
    assert mem.pedir("recuerda que MI CUMPLEANOS es el 3 de mayo").startswith("Ya lo tenía guardado")
    assert mem.hechos() == {"cumpleanos": "el 3 de Mayo"}


def test_duplicado_exacto_no_reescribe_el_fichero(mem):
    """[RETENIDO]"""
    mem.pedir("recuerda que mi coche es rojo")
    mtime = os.stat(mem.ruta).st_mtime_ns
    assert mem.pedir("recuerda que mi coche es Rojo") == "Ya lo tenía guardado: coche = rojo. No he cambiado nada."
    assert os.stat(mem.ruta).st_mtime_ns == mtime


def test_conflicto_pregunta_y_sustituye(mem):
    """[REESCRITO] Aclaración sin estado: el conflicto no sobrescribe e indica la forma explícita;
    '1' ya no es una respuesta pendiente. La sustitución explícita mantiene intacto el dato no relacionado."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi ciudad es Bilbao")
    r = mem.pedir("recuerda que mi coche es azul")
    assert r.startswith("Ya tengo guardado que coche es rojo.") and "recuerda que ahora coche es azul" in r
    assert mem.hechos() == {"coche": "rojo", "ciudad": "Bilbao"}
    assert mem.pedir("1") is None and mem.hechos() == {"coche": "rojo", "ciudad": "Bilbao"}
    assert mem.pedir("recuerda que ahora mi coche es azul") == "Actualizado: coche = azul (antes era: rojo)."
    assert mem.hechos() == {"coche": "azul", "ciudad": "Bilbao"}      # el dato no relacionado sigue intacto


def test_conflicto_pregunta_y_anade(mem):
    """[REESCRITO] Un valor por dato: no hay "añadir"; ni "añádelo" ni "también" cambian nada."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi coche es azul")
    assert mem.pedir("añádelo") is None
    assert "un valor por dato" in mem.pedir("recuerda que mi coche también es azul")
    assert mem.hechos() == {"coche": "rojo"}
    assert mem.pedir("recuerda que mi coche es rojo").startswith("Ya lo tenía guardado")


def test_conflicto_cancelado_no_cambia_nada(mem):
    """[RETENIDO] Tras un conflicto nada cambia, y las respuestas sueltas no hacen nada."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi coche es azul")
    assert mem.pedir("no") is None
    assert mem.hechos() == {"coche": "rojo"}
    mem.pedir("recuerda que mi coche es verde")
    assert mem.pedir("¿qué hora es?") is None
    assert mem.pedir("1") is None
    assert mem.hechos() == {"coche": "rojo"}


def test_actualizar_y_anadir_explicitos(mem):
    """[REESCRITO] Formas explícitas actualizan; las genéricas/sin verbo no tocan nada; actualizar un
    dato inexistente con intención explícita lo guarda (y lo dice); "añadir"/"también" no existen."""
    mem.pedir("recuerda que mi coche es rojo")
    assert mem.pedir("actualiza en tu memoria mi coche a azul") == "Actualizado: coche = azul (antes era: rojo)."
    assert mem.pedir("mi coche ahora es verde") is None
    assert mem.pedir("recuerda que mi coche ahora es verde") == "Actualizado: coche = verde (antes era: azul)."
    assert mem.pedir("recuerda que ahora mi coche es negro") == "Actualizado: coche = negro (antes era: verde)."
    assert mem.pedir("update my car to white") is None
    assert mem.pedir("change my car to white") is None
    assert mem.pedir("actualiza mi moto a roja") is None                 # entrada original: genérica, no toca nada
    assert mem.pedir("actualiza en tu memoria mi moto a roja") == "No tenía ese dato; lo guardo ahora: moto = roja."
    assert mem.pedir("añade blanco a mi coche") is None
    assert "un valor por dato" in mem.pedir("recuerda que mi coche también es gris")
    assert mem.hechos() == {"coche": "negro", "moto": "roja"}


def test_actualizar_elige_el_corte_que_coincide_con_un_dato(mem):
    """[REESCRITO: entrada con objeto de memoria por el requisito de intención explícita; mismo
    resultado] Se elige la división cuya clave completa está guardada."""
    mem.pedir("recuerda que mi viaje a Roma es en junio")
    assert mem.pedir("cambia mi viaje a Roma a julio") is None
    assert mem.pedir("cambia en tu memoria mi viaje a Roma a julio") == "Actualizado: viaje a Roma = julio (antes era: en junio)."
    assert mem.hechos() == {"viaje a roma": "julio"}


def test_olvidar_por_clave_por_contencion_y_por_valor(mem):
    """[RETENIDO por clave; REESCRITO por valor/contención y nota] Sólo se borran claves completas:
    "lo de Rex" (valor) no borra a ciegas; las notas libres no existen."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi perro se llama Rex")
    assert mem.pedir("olvida el coche") == "Olvidado: coche (era: rojo). Ya no lo usaré."
    assert mem.pedir("olvida lo de Rex") == "No tenía nada guardado sobre 'Rex'."
    assert mem.hechos() == {"perro": "Rex"}
    assert mem.pedir("olvida lo de mi perro") == "Olvidado: perro (era: Rex). Ya no lo usaré."
    assert mem.pedir("olvida que tengo que llamar a Juan") == "No tenía nada guardado sobre 'tengo que llamar a Juan'."
    assert mem.hechos() == {}


def test_olvidar_un_valor_de_una_lista(mem):
    """[REESCRITO] Un valor por dato: se olvida el dato si el valor coincide; si no, no se toca."""
    mem.pedir("recuerda que mis hijos son Ana y Luis")
    assert mem.pedir("añade Luis a mis hijos") is None                   # entrada original: no hay "añadir"
    for parcial in ("olvida que mis hijos son Ana", "olvida que mis hijos son Luis"):   # entradas originales
        assert mem.pedir(parcial).startswith("Tengo guardado que hijos es Ana y Luis")
    r = mem.pedir("olvida que mis hijos son Pedro")
    assert r.startswith("Tengo guardado que hijos es Ana y Luis, no 'Pedro'.") and "olvida hijos" in r
    assert mem.hechos() == {"hijos": "Ana y Luis"}
    assert mem.pedir("olvida que mis hijos son Ana y Luis") == "Olvidado: hijos (era: Ana y Luis). Ya no lo usaré."
    assert mem.hechos() == {}


def test_olvidar_inexistente_informa_sin_tocar_nada(mem):
    """[RETENIDO; "olvida la conversación" REESCRITO: no hay sugerencia de «reset», sólo se informa
    de que no es un dato guardado y no se toca nada]"""
    mem.pedir("recuerda que mi coche es rojo")
    assert mem.pedir("olvida mi moto") == "No tenía nada guardado sobre 'moto'."
    assert mem.hechos() == {"coche": "rojo"}
    assert mem.pedir("olvida la conversación") == "No tenía nada guardado sobre 'conversación'."
    assert mem.hechos() == {"coche": "rojo"}


def test_olvidar_ambiguo_pregunta_cual(mem):
    """[REESCRITO] Con propiedad: "coche" es el del usuario (no el de Ana); la ambigüedad real
    (varias claves parciales) se aclara con sugerencias sin borrar nada; no hay respuestas numeradas."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    mem.pedir("recuerda que mi moto es negra")
    assert mem.pedir("olvida coche") == "Olvidado: coche (era: rojo). Ya no lo usaré."
    assert mem.hechos() == {"coche de ana": "azul", "moto": "negra"}
    assert mem.pedir("2") is None and mem.pedir("todos") is None
    mem.pedir("recuerda que mi número de la suerte es 7")
    mem.pedir("recuerda que mi número de teléfono es 600")
    r = mem.pedir("olvida mi número")
    assert "Quizá te refieres a" in r and "número de la suerte" in r and "número de teléfono" in r
    assert len(mem.hechos()) == 4
    assert mem.pedir("olvida el coche de Ana") == "Olvidado: coche de Ana (era: azul). Ya no lo usaré."


def test_actualizar_ambiguo_pregunta_cual(mem):
    """[REESCRITO] Ambigüedad real de clave: se aclara y no se cambia nada; con la clave completa sí."""
    mem.pedir("recuerda que mi viaje es en mayo")
    mem.pedir("recuerda que mi viaje a Roma es en junio")
    mem.pedir("recuerda que mi coche es rojo")
    assert mem.pedir("actualiza coche a verde") is None                  # entrada original: genérica, no toca nada
    assert mem.hechos()["coche"] == "rojo"
    assert mem.pedir("olvida mi coche").startswith("Olvidado")
    r = mem.pedir("actualiza en tu memoria mi viaje a Roma a verde")
    assert r.startswith("No está claro a qué dato te refieres") and "'viaje'" in r and "'viaje a Roma'" in r
    assert mem.pedir("1") is None
    assert mem.hechos() == {"viaje": "en mayo", "viaje a roma": "en junio"}
    assert mem.pedir("actualiza en tu memoria viaje a Roma: verde").startswith("Actualizado: viaje a Roma = verde")
    assert mem.hechos() == {"viaje": "en mayo", "viaje a roma": "verde"}


def test_olvidar_todo_requiere_confirmacion(mem):
    """[RETENIDO el requisito de confirmación; REESCRITO el mecanismo: frase explícita en el mismo
    mensaje ('olvida todo, confirmo') en vez de una respuesta pendiente 'sí']"""
    assert mem.pedir("olvida todo") == "No había ningún hecho guardado que olvidar."
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi perro se llama Rex")
    assert "confirm" in mem.pedir("forget everything")
    assert mem.pedir("mejor no") is None and len(mem.hechos()) == 2
    assert "confirmo" in mem.pedir("borra toda tu memoria")
    assert mem.pedir("sí") is None and len(mem.hechos()) == 2
    assert mem.pedir("olvida todo, confirmo") == "Hecho: he olvidado los 2 hechos guardados."
    assert mem.yaml()["hechos"] == {}


def test_peticion_de_guardar_sin_contenido_pide_aclaracion(mem):
    """[RETENIDO]"""
    r = mem.pedir("recuerda esto")
    assert r.startswith("No he entendido qué dato debo recordar") and "recuerda que <clave> es <valor>" in r
    assert mem.pedir("acuérdate de mi cumpleaños").startswith("No he entendido qué dato debo recordar")
    assert mem.pedir("remember the milk").startswith("I couldn't tell which fact to store")
    assert not mem.ruta.exists()


def test_consultar_y_listar(mem):
    """[REESCRITO: mensajes actuales, propiedad y contrato de consultas]"""
    assert mem.pedir("¿qué recuerdas?").startswith("Aún no tengo ningún hecho guardado.")
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    assert mem.pedir("¿qué sabes de mi coche?") == "Sí, lo recuerdo: coche es rojo."
    assert mem.pedir("what do you remember about juan?") == "I have nothing stored about 'juan'."
    assert mem.pedir("¿qué recuerdas del coche?") is None             # 'del' no es un conector reconocido
    assert mem.pedir("¿qué recuerdas sobre coche?") == "Sí, lo recuerdo: coche es rojo."   # el de Ana es otro dato
    assert mem.pedir("¿qué recuerdas de mi moto?") == "No tengo nada guardado sobre 'moto'."
    assert mem.pedir("¿qué sabes de mi moto?") == "No tengo nada guardado sobre 'moto'."   # 'mi X': consulta de memoria
    assert mem.pedir("¿qué sabes de python?") is None                 # pregunta general: para el modelo
    assert mem.pedir("ver hechos") == "Tengo 2 hecho(s) guardado(s):\n- coche: rojo\n- coche de Ana: azul"


# =========================================================================== contexto para el motor y fichero
def test_contexto_para_el_motor(mem):
    """[RETENIDO; sin notas ni listas]"""
    assert m.get_memory_context() == ""                 # sin fichero: sin mensaje de memoria
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mis hijos son Ana y Luis")
    assert mem.pedir("añade Luis a mis hijos") is None                   # entrada original: no hay "añadir"
    ctx = m.get_memory_context()
    assert ctx.startswith("Hechos que el usuario pidió recordar (memoria persistente):")
    assert ctx.endswith("- coche: rojo\n- hijos: Ana y Luis")
    mem.pedir("olvida mis hijos")
    assert "hijos" not in m.get_memory_context() and "- coche: rojo" in m.get_memory_context()


def test_formato_antiguo_se_migra_y_las_otras_secciones_se_conservan(mem):
    """[REESCRITO] Migración actual: TODAS las secciones del perfil antiguo pasan a ser hechos
    (consultables y olvidables) y el perfil original se conserva byte a byte en una copia."""
    mem.perfil.write_text(
        "aprendido_durante_sesion:\n  mi coche: rojo\n"
        "vida_personal:\n  pareja:\n    nombre: Ana\n  vehiculo: una camper\n"
        "entorno:\n  sistemas_operativos: [ubuntu, windows]\n", encoding="utf-8")
    original = mem.perfil.read_bytes()
    assert mem.hechos() == {"coche": "rojo", "pareja nombre": "Ana", "vehiculo": "una camper",
                            "sistemas operativos": "ubuntu, windows"}
    ctx = m.get_memory_context()
    assert "- coche: rojo" in ctx and ctx.count("rojo") == 1           # sin duplicados
    assert "- pareja nombre: Ana" in ctx and "- vehiculo: una camper" in ctx
    assert "- sistemas operativos: ubuntu, windows" in ctx
    assert _ok(mem.pedir("recuerda que mi ciudad es Bilbao"))
    assert mem.hechos()["ciudad"] == "Bilbao" and len(mem.hechos()) == 5
    copias = list(mem.perfil.parent.glob("user_profile.yaml.legado-*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == original
    assert yaml.safe_load(mem.perfil.read_text(encoding="utf-8")) == {"aprendido_durante_sesion": {}}


def test_fichero_vacio_o_ausente_se_trata_como_memoria_vacia(mem):
    """[RETENIDO]"""
    assert mem.hechos() == {} and m.get_memory_context() == ""
    mem.ruta.write_text("", encoding="utf-8")
    assert mem.hechos() == {} and m.get_memory_context() == ""
    assert _ok(mem.pedir("recuerda que mi coche es rojo"))
    assert mem.yaml()["version"] == 1 and mem.hechos() == {"coche": "rojo"}


@pytest.mark.parametrize("contenido", [
    "hechos: [esto, no, es, un, mapa\n",           # YAML inválido
    "- una\n- lista\n",                               # válido pero no es un mapa
    "hechos: [lista]\n",                              # sección con el tipo equivocado
    "notas: {a: b}\n",
    "\xff\xfe binario",
])
def test_fichero_corrupto_no_se_sobrescribe_y_no_rompe_el_contexto(mem, contenido, capsys):
    """[RETENIDO x5: mismo contenido dañado en el fichero de memoria persistente actual]"""
    mem.ruta.write_bytes(contenido.encode("utf-8", "surrogateescape") if isinstance(contenido, str) else contenido)
    original = mem.ruta.read_bytes()
    assert m.get_memory_context() == ""
    assert "Aviso: memoria de hechos dañada" in capsys.readouterr().out
    r = mem.pedir("recuerda que mi coche es rojo")
    assert r.startswith("No puedo usar la memoria persistente") and "No lo modificaré" in r
    assert mem.pedir("olvida todo").startswith("No puedo usar la memoria persistente")
    assert mem.pedir("¿qué recuerdas?").startswith("No puedo usar la memoria persistente")
    assert mem.ruta.read_bytes() == original
    assert not any(f.startswith(".facts-") for f in os.listdir(mem.ruta.parent))   # sin temporales huérfanos
    with pytest.raises(m.MemoriaHechosInvalida):
        m.listar_hechos()


def test_fallo_de_escritura_no_destruye_los_datos_ni_informa_exito(mem):
    """[RETENIDO]"""
    mem.pedir("recuerda que mi coche es rojo")
    original = mem.ruta.read_bytes()

    def fallo(*a, **k):
        raise OSError("disco lleno")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(m.os, "replace", fallo)
        r = mem.pedir("recuerda que mi ciudad es Bilbao")
    assert r.startswith("No he podido guardar el cambio") and "disco lleno" in r
    assert "Hecho guardado" not in r
    assert mem.ruta.read_bytes() == original
    assert not any(f.startswith(".facts-") for f in os.listdir(mem.ruta.parent))
    assert mem.hechos() == {"coche": "rojo"}
    assert _ok(mem.pedir("recuerda que mi ciudad es Bilbao"))              # recuperado: vuelve a funcionar


def test_directorio_de_solo_lectura(mem, monkeypatch):
    """[RETENIDO, incluida su condición de entorno original]"""
    if os.geteuid() == 0:
        pytest.skip("root ignora los permisos de directorio")
    mem.pedir("recuerda que mi coche es rojo")
    original = mem.ruta.read_bytes()
    os.chmod(mem.ruta.parent, 0o500)
    try:
        r = mem.pedir("recuerda que mi ciudad es Bilbao")
        assert r.startswith("No he podido guardar el cambio") and "Hecho guardado" not in r
        assert mem.ruta.read_bytes() == original
    finally:
        os.chmod(mem.ruta.parent, 0o700)


def test_la_verificacion_tras_escribir_detecta_escrituras_incompletas(mem, monkeypatch):
    """[RETENIDO: el escritor actual es guardar_hechos]"""
    mem.pedir("recuerda que mi coche es rojo")
    monkeypatch.setattr(m, "guardar_hechos", lambda *a, **k: None)       # "escribe" sin escribir
    r = mem.pedir("recuerda que mi ciudad es Bilbao")
    assert r.startswith("No he podido guardar el cambio") and "verificación" in r
    assert "Hecho guardado" not in r
    assert mem.hechos() == {"coche": "rojo"}


def test_el_fichero_se_crea_con_directorios_intermedios(perfil_temporal, monkeypatch):
    """[RETENIDO: el fichero de memoria persistente actual es facts.yaml]"""
    ruta = perfil_temporal.parent / "config" / "data" / "facts.yaml"
    monkeypatch.setattr(m, "FACTS_PATH", str(ruta))
    assert _ok(procesar_comando_memoria("recuerda que mi coche es rojo"))
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert datos["version"] == 1 and datos["hechos"]["coche"]["valor"] == "rojo"


def test_historial_ilegible_se_aparta_en_vez_de_sobrescribirse(tmp_path, monkeypatch, capsys):
    """[RETENIDO]"""
    monkeypatch.setattr(m, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(m, "SESSION_FILE", str(tmp_path / "historial.json"))
    (tmp_path / "historial.json").write_text("{corrupto", encoding="utf-8")
    assert m.load_full_history() == []
    assert "conservado en" in capsys.readouterr().out
    respaldos = [f for f in os.listdir(tmp_path) if f.startswith("historial.json.corrupto-")]
    assert len(respaldos) == 1 and (tmp_path / respaldos[0]).read_text(encoding="utf-8") == "{corrupto"
    assert (tmp_path / "historial.json").read_text(encoding="utf-8") == "[]"


def test_la_memoria_no_usa_la_red(mem, monkeypatch):
    """[RETENIDO] Todo el procesamiento es local: cualquier intento de abrir un socket sería un fallo."""
    import socket

    def prohibido(*a, **k):
        raise AssertionError("la memoria persistente no debe abrir sockets")

    monkeypatch.setattr(socket, "socket", prohibido)
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)
    assert _ok(mem.pedir("recuerda que mi coche es rojo"))
    assert "rojo" in mem.pedir("¿qué sabes de mi coche?")
    assert mem.pedir("actualiza en tu memoria mi coche a azul").startswith("Actualizado")
    assert mem.pedir("olvida mi coche").startswith("Olvidado")
    assert m.get_memory_context() == ""
