"""
Memoria persistente (core/memory_engine.py + core/memory_commands.py, fase 7
"aprendizaje local natural").

Pruebas de regresión con almacenamiento temporal y sin ningún motor: la memoria
es puramente local y determinista. Cubren:
  - interpretación de peticiones en lenguaje natural (variaciones, ES/EN) y, sobre
    todo, lo que NO debe interpretarse (conversación, preguntas, negaciones,
    ejemplos entrecomillados, peticiones incrustadas);
  - guardar / consultar / actualizar / olvidar, duplicados, conflictos y
    preguntas de aclaración;
  - formato del fichero, migración del formato antiguo, contexto para el motor;
  - robustez: ficheros ausentes, vacíos o corruptos y fallos de escritura.

MIGRACIÓN A LA API ACTUAL (fichero recibido en la revisión externa, escrito
contra una API que no existe en este proyecto: interpretar(), procesar_peticion(),
hay_pendiente(), listar_hechos() -> (hechos, notas), MemoriaCorrupta,
_guardar_perfil, fixture perfil_temporal, notas, listas de valores y
respuestas numeradas a preguntas pendientes). Cada caso original se conserva
con una de estas marcas:
  R  retenido: misma frase y misma expectativa, sólo cambia la API/el fixture.
  W  reescrito: misma frase/escenario; la expectativa se adapta al contrato
     actual, en todos los casos por una directriz posterior del proyecto:
       - los verbos genéricos (guarda/anota/apunta/graba/note/write down) NO
         guardan sin objeto de memoria explícito;
       - las citas y los ejemplos se rechazan con aclaración;
       - las negaciones y las peticiones incompletas se contestan localmente,
         nunca van al motor y nunca escriben;
       - la clave se guarda sin el posesivo de primera persona ("coche", no
         "mi coche") y la propiedad ajena se conserva ("coche de ana");
       - el olvido es por clave exacta; las coincidencias parciales son
         sugerencias, nunca borrados ni hechos confirmados;
       - un valor por clave (sin listas ni notas): un conflicto pide la forma
         explícita "recuerda que ahora X es Y" en lugar de respuestas "1/2";
       - "olvida todo" se confirma con la frase "olvida todo, confirmo".
  P  reemplazo: el escenario no se puede expresar con la API actual (p. ej.
     interpretar() sin efectos secundarios); se prueba el comportamiento
     requerido subyacente con la API actual.
"""
import os
import stat

import pytest
import yaml

from core import memory_engine as m
from core.memory_commands import procesar_comando_memoria


@pytest.fixture
def mem(memoria_temporal):
    """API mínima sobre el almacén temporal: pedir(texto) -> respuesta, hechos(), ruta."""
    class Mem:
        ruta = memoria_temporal.hechos          # facts.yaml (la memoria persistente actual)
        perfil = memoria_temporal.perfil        # user_profile.yaml (formato antiguo)

        @staticmethod
        def pedir(texto):
            return procesar_comando_memoria(texto)

        @staticmethod
        def hechos():
            return {clave: e["valor"] for clave, e in m.cargar_hechos().items()}

        @staticmethod
        def yaml():
            return yaml.safe_load(memoria_temporal.hechos.read_text(encoding="utf-8"))

    return Mem


def _valores(mem):
    return dict(mem.hechos())


# =========================================================================== interpretación: variaciones aceptadas
# (marca, texto, clave normalizada, valor)   — None en clave/valor = no debe guardar nada
GUARDAR = [
    ("R", "recuerda que mi coche es rojo", "coche", "rojo"),
    ("R", "Recuerda que mi coche es ROJO.", "coche", "ROJO"),
    ("R", "recuerda: mi coche es rojo", "coche", "rojo"),
    ("R", "recuerda mi coche es rojo", "coche", "rojo"),
    ("R", "recuerda esto: mi coche es rojo", "coche", "rojo"),
    ("R", "aprende: mi coche es rojo", "coche", "rojo"),
    ("R", "aprende que mi coche es rojo", "coche", "rojo"),
    ("W", "anota que mi coche es rojo", None, None),          # genérico sin objeto de memoria: conversación
    ("W", "apunta que mi coche es rojo", None, None),
    ("W", "guarda que mi coche es rojo", None, None),
    ("W", "graba esto: mi coche es rojo", None, None),
    ("R", "memoriza que mi coche es rojo", "coche", "rojo"),
    ("R", "acuérdate de que mi coche es rojo", "coche", "rojo"),
    ("R", "no olvides que mi coche es rojo", "coche", "rojo"),
    ("R", "no te olvides de que mi coche es rojo", "coche", "rojo"),
    ("R", "quiero que recuerdes que mi coche es rojo", "coche", "rojo"),
    ("R", "me gustaría que recordaras que mi coche es rojo", "coche", "rojo"),
    ("R", "puedes recordar que mi coche es rojo", "coche", "rojo"),
    ("R", "B.A.I, recuerda que mi coche es rojo", "coche", "rojo"),
    ("R", "bai por favor recuerda que mi coche es rojo, por favor!", "coche", "rojo"),
    ("R", "Recuerda, por favor, que mi coche es rojo", "coche", "rojo"),
    ("R", "  recuerda   que  mi coche   es rojo  ", "coche", "rojo"),
    ("W", "recuerda que «mi coche» es 'rojo'", None, None),   # citas: se rechaza con aclaración
    ("R", "recuerda que mi coche = rojo", "coche", "rojo"),
    ("R", "recuerda que mi coche: rojo", "coche", "rojo"),
    ("R", "recuerda que mis hijos son Ana y Luis", "hijos", "Ana y Luis"),
    ("R", "recuerda que mi perro se llama Rex", "perro", "Rex"),
    ("R", "recuerda que mi coche está en el garaje", "coche", "en el garaje"),
    ("R", "recuerda que mi cumpleaños es el 3 de mayo", "cumpleanos", "el 3 de mayo"),
    ("R", "remember that my car is red", "car", "red"),
    ("R", "Remember: my car is red.", "car", "red"),
    ("R", "remember my car is red", "car", "red"),
    ("R", "please remember that my car is red", "car", "red"),
    ("R", "don't forget that my car is red", "car", "red"),
    ("R", "do not forget my car is red", "car", "red"),
    ("W", "note that my car is red", None, None),             # genérico sin objeto de memoria
    ("W", "write down that my car is red", None, None),
    ("R", "I want you to remember that my car is red", "car", "red"),
    ("R", "could you please remember that my car is red", "car", "red"),
    ("R", "remember that my kids are Ana and Luis", "kids", "Ana and Luis"),
]


@pytest.mark.parametrize("marca,texto,clave,valor", GUARDAR, ids=[g[1] for g in GUARDAR])
def test_variantes_de_guardar(mem, marca, texto, clave, valor):
    r = mem.pedir(texto)
    if clave is None:
        assert mem.hechos() == {} and "Hecho guardado" not in str(r) and "Fact stored" not in str(r), texto
        if marca == "W" and "«" in texto:
            assert "comillas" in r                           # cita: aclaración local, nada guardado
        else:
            assert r is None                                 # genérico: conversación normal
    else:
        assert r is not None and ("Hecho guardado" in r or "Fact stored" in r), texto
        assert mem.hechos() == {clave: valor}


@pytest.mark.parametrize("texto", ["guarda en tu memoria que mi coche es rojo", "anota como hecho que mi coche es rojo",
                                   "note in your memory that my car is red", "write down as a fact that my car is red"])
def test_verbos_genericos_con_objeto_de_memoria_si_guardan(mem, texto):
    """Complemento de los casos W de GUARDAR: la forma explícita de esos verbos sí guarda."""
    assert "guardado" in mem.pedir(texto).lower() or "stored" in mem.pedir(texto).lower() or mem.hechos()
    assert list(mem.hechos().values()) in (["rojo"], ["red"])


# W: sin notas (un dato sin clave/valor no se puede consultar, actualizar ni olvidar por clave):
#    la petición se aclara localmente y no se guarda nada. "recuerda que no como carne" es además
#    una negación y se aclara como tal.
NOTAS = [
    ("recuerda que tengo que llamar a Juan", "recuerda que"),
    ("no olvides que me gusta el café solo", "recuerda que"),
    ("recuerda que no como carne", "negación"),
    ("remember that I don't eat meat", "remember that"),
    ("recuerda que tengo que llamar a Juan porque es su cumpleaños", "recuerda que"),
]


@pytest.mark.parametrize("texto,pista", NOTAS)
def test_frases_sin_clave_valor_piden_aclaracion_y_no_guardan(mem, texto, pista):
    r = mem.pedir(texto)
    assert r is not None and pista in r, texto
    assert not mem.ruta.exists()


CONSULTAR = [  # R: la consulta devuelve el dato guardado
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
    r = mem.pedir(texto)
    assert r is not None and valor in r and ("recuerdo" in r or "remember" in r), texto
    assert mem.hechos() == {"coche": "rojo", "car": "red"}        # consultar no modifica nada


@pytest.mark.parametrize("texto", [  # R (ver memoria -> ver hechos: "ver memoria" es el comando del historial en la CLI)
    "¿qué recuerdas?", "qué sabes de mí", "¿qué has aprendido?", "what do you remember?", "what do you know about me?",
    "ver hechos", "muestra tu memoria", "muéstrame lo que sabes de mí", "lista los hechos", "show me your memory",
    "list facts", "enséñame la memoria persistente",
])
def test_variantes_de_listar(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi perro se llama Rex")
    r = mem.pedir(texto)
    assert r is not None and "- coche: rojo" in r and "- perro: Rex" in r, texto


OLVIDAR = [  # R: olvidan exactamente ese dato
    ("olvida mi coche", "coche"),
    ("Olvida lo de mi coche.", "coche"),
    ("olvídate de mi coche", "coche"),
    ("olvida lo que sabes de mi coche", "coche"),
    ("olvida todo lo que sabes sobre mi coche", "coche"),
    ("borra mi coche de tu memoria", "coche"),
    ("elimina lo que sabes de mi coche", "coche"),
    ("quita el dato de mi coche de la memoria", "coche"),
    ("deja de recordar mi coche", "coche"),
    ("no recuerdes más mi coche", "coche"),
    ("B.A.I, por favor, olvida mi coche", "coche"),
    ("olvida, por favor, mi coche", "coche"),
    ("forget my car", "car"),
    ("forget about my car", "car"),
    ("forget everything about my car", "car"),
    ("delete my car from your memory", "car"),
    ("remove what you know about my car", "car"),
    ("stop remembering my car", "car"),
]


@pytest.mark.parametrize("texto,clave", OLVIDAR)
def test_variantes_de_olvidar(mem, texto, clave):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    mem.pedir("recuerda que mi moto es negra")
    r = mem.pedir(texto)
    assert r is not None and ("Olvidado" in r or "Forgotten" in r), texto
    esperado = {"coche": "rojo", "car": "red", "moto": "negra"}
    esperado.pop(clave)
    assert mem.hechos() == esperado                                  # sólo ese dato; el resto intacto


@pytest.mark.parametrize("texto", [  # R
    "olvida que mi coche es rojo", "olvídate de que mi coche es rojo", "forget that my car is red",
])
def test_olvidar_un_valor_concreto(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    r = mem.pedir(texto)
    assert "Olvidado" in r or "Forgotten" in r
    assert len(mem.hechos()) == 1


@pytest.mark.parametrize("texto", [  # W: requiere la frase de confirmación en vez de responder "sí"
    "olvida todo", "olvida todo lo que sabes de mí", "olvida lo que sabes de mí", "borra toda tu memoria", "olvídate de todo",
    "forget everything", "forget everything about me", "erase your memory",
])
def test_variantes_de_olvidar_todo(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    r = mem.pedir(texto)
    assert r is not None and ("confirmo" in r or "confirm" in r), texto
    assert mem.hechos() == {"coche": "rojo"}                         # pedir confirmación no borra nada


ACTUALIZAR = [  # R: actualizan un dato que ya existe (nunca crean)
    ("actualiza mi coche a azul", "coche", "azul"),
    ("actualiza mi coche: azul", "coche", "azul"),
    ("actualiza mi coche: ahora es azul", "coche", "azul"),
    ("cambia mi coche a azul", "coche", "azul"),
    ("cambia mi coche por azul", "coche", "azul"),
    ("corrige mi coche, ahora es azul", "coche", "azul"),
    ("ahora mi coche es azul", "coche", "azul"),
    ("mi coche ahora es azul", "coche", "azul"),
    ("mi coche ya no es rojo, ahora es azul", "coche", "azul"),
    ("update my car to blue", "car", "blue"),
    ("change my car to blue", "car", "blue"),
    ("my car is now blue", "car", "blue"),
]


@pytest.mark.parametrize("texto,clave,valor", ACTUALIZAR)
def test_variantes_de_actualizar(mem, texto, clave, valor):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("remember that my car is red")
    r = mem.pedir(texto)
    assert r is not None and ("Actualizado" in r or "Updated" in r), texto
    esperado = {"coche": "rojo", "car": "red"}
    esperado[clave] = valor
    assert mem.hechos() == esperado


def test_recuerda_que_ahora_actualiza_y_tambien_no_anade(mem):
    """R: 'recuerda que ahora' actualiza. W: sin listas de valores, 'también' es un
    conflicto: no sobreescribe y pide la forma explícita."""
    mem.pedir("recuerda que mi coche es rojo")
    assert "Actualizado: coche = azul" in mem.pedir("recuerda que ahora mi coche es azul")
    r = mem.pedir("recuerda que mi coche también es verde")
    assert "azul" in r and "recuerda que ahora" in r and mem.hechos() == {"coche": "azul"}
    mem.pedir("remember that my car is red")
    r = mem.pedir("remember that my car is also blue")
    assert "red" in r and mem.hechos() == {"coche": "azul", "car": "red"}


@pytest.mark.parametrize("texto", [  # W: sin listas, 'añade X a Y' es un verbo genérico sin objeto: conversación
    "añade azul a mi coche", "agrega Pedro a mis hijos", "add blue to my car",
])
def test_anadir_no_existe_como_operacion(mem, texto):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mis hijos son Ana")
    assert mem.pedir(texto) is None
    assert mem.hechos() == {"coche": "rojo", "hijos": "Ana"}


# =========================================================================== interpretación: lo que NO es una petición
# (marca, texto, resultado): None = conversación normal (va al motor); "local" = respuesta local sin escribir
NO_PETICIONES = [
    # conversación normal (antes se "aprendía" de todo esto)
    ("R", "hola qué tal", None),
    ("R", "mi furgoneta es una camper", None),
    ("R", "me gusta el café", None),
    ("R", "tengo dos hijos", None),
    ("R", "mi coche es rojo", None),
    ("R", "dame la hora: ahora mismo", None),
    # negaciones: se contestan localmente y NUNCA escriben (W: antes iban al motor)
    ("W", "no recuerdes que mi coche es rojo", "local"),
    ("W", "no quiero que recuerdes mi coche", "local"),
    ("W", "nunca recuerdes mi coche", "local"),
    ("W", "no olvides nada", "local"),
    ("W", "don't remember that my car is red", "local"),
    ("W", "please do not forget everything", "local"),
    ("R", "no borres mi coche de tu memoria", None),
    # preguntas (sobre el comando o sobre el hecho): nunca modifican la memoria
    ("W", "¿recuerdas que mi coche es rojo?", "local"),        # consulta de sólo lectura
    ("R", "¿puedes recordar que mi coche es rojo?", None),
    ("R", "recuerda que mi coche es rojo?", None),
    ("R", "¿olvidas mi coche?", None),
    ("R", "olvida mi coche?", None),
    ("R", "¿qué hace 'recuerda que X es Y'?", None),
    ("W", "do you remember my car?", "local"),                  # consulta de sólo lectura
    ("R", "can you forget my car?", None),
    # ejemplos entrecomillados
    ("R", '"recuerda que mi coche es rojo"', None),
    ("R", "«olvida mi coche»", None),
    ("R", "'remember that my car is red'", None),
    # peticiones incrustadas en otra frase
    ("R", "explica qué significa «recuerda que X es Y»", None),
    ("R", "dime la hora y recuerda que mi coche es rojo", None),
    ("R", "antes de que olvides mi coche dime la hora", None),
    ("R", "cuando te diga recuerda que X es Y, ¿qué harás?", None),
    ("R", "me gustaría que recordaras mejor las cosas", None),
    ("R", "it would be nice if you could remember things", None),
    # verbos genéricos sin marca de memoria
    ("R", "guarda el fichero", None),
    ("R", "aprende python", None),
    ("R", "borra los comentarios del código", None),
    ("R", "elimina la última línea", None),
    ("R", "quita el sombrero", None),
    ("R", "cambia a modo online", None),
    ("R", "pasa a modo offline", None),
    ("R", "save the file", None),
    ("R", "learn how to cook", None),
    ("R", "remove the last line", None),
    # comandos de otros subsistemas
    ("R", "estado", None), ("R", "reset", None), ("R", "salir", None),
    # pronombres sin referente: aclaración local (W); preguntas generales: al motor
    ("W", "olvida eso", "local"), ("W", "olvídalo", "local"), ("W", "forget it", "local"),
    ("R", "¿qué sabes?", None), ("R", "what do you know?", None), ("R", "qué sabes hacer", None),
    # otras frases con los mismos verbos
    ("R", "recuérdame mañana la cita", None), ("R", "me recuerdas a mi primo", None), ("R", "recuerdas mi coche", None),
    ("R", "cambia de tema", None), ("R", "ahora es tarde", None),
    # respuestas a preguntas que no están pendientes
    ("R", "1", None), ("R", "sí", None), ("R", "no", None),
]


@pytest.mark.parametrize("marca,texto,resultado", NO_PETICIONES, ids=[n[1] for n in NO_PETICIONES])
def test_frases_normales_no_son_peticiones_de_memoria(mem, marca, texto, resultado):
    mem.pedir("recuerda que mi moto es negra")                    # un dato no relacionado que debe quedar intacto
    r = mem.pedir(texto)
    if resultado is None:
        assert r is None, texto
    else:
        assert isinstance(r, str) and r, texto                  # respuesta local, nunca el motor
    assert mem.hechos() == {"moto": "negra"}                    # nada guardado, nada cambiado, nada borrado


@pytest.mark.parametrize("texto", [  # R
    "mi coche ahora es azul", "ahora mi coche es azul", "cambia mi coche a azul", "corrige mi coche, ahora es azul",
    "añade azul a mi coche", "my car is now blue", "change my car to blue", "add blue to my car",
    "¿qué sabes de python?", "what do you know about Rust?", "¿qué sabes?",
])
def test_formas_sin_verbo_explicito_solo_cuentan_si_el_dato_existe(mem, texto):
    """'mi coche ahora es azul' es memoria si 'mi coche' está guardado; si no, es
    conversación normal (None) y nunca crea datos ni responde 'no tengo'."""
    assert mem.pedir(texto) is None
    assert not mem.ruta.exists()


def test_las_lecturas_y_aclaraciones_no_tienen_efectos_secundarios(mem):
    """P (interpretar() no existe): las operaciones que no escriben nunca crean el almacén."""
    for texto in ("¿qué recuerdas?", "¿cuál es mi coche?", "recuerda esto", "olvida todo", "olvídalo",
                  "recuerda que «mi coche es rojo»", "no recuerdes que mi coche es rojo"):
        mem.pedir(texto)
    assert not mem.ruta.exists()


def test_procesar_tolera_entradas_raras(mem):
    """R (adaptado): entradas vacías o incompletas no rompen ni escriben."""
    for raro in (None, 42, "", "   ", "?", "¿", '"', "recuerda", "olvida", "recuerda que", "recuerda que es"):
        r = mem.pedir(raro)
        assert r is None or isinstance(r, str)
    assert not mem.ruta.exists()


# =========================================================================== operaciones
def test_guardar_crea_el_fichero_con_el_formato_esperado(mem):
    """W: formato actual (facts.yaml versionado); las notas no existen (aclaración)."""
    r = mem.pedir("recuerda que mi coche es rojo")
    assert r == "Hecho guardado: coche = rojo. Lo recordaré entre sesiones."
    datos = mem.yaml()
    assert datos["version"] == 1 and set(datos["hechos"]) == {"coche"}
    assert datos["hechos"]["coche"]["clave"] == "coche" and datos["hechos"]["coche"]["valor"] == "rojo"
    assert mem.pedir("no olvides que tengo que llamar a Juan").startswith("No he entendido qué dato")
    assert set(mem.yaml()["hechos"]) == {"coche"}


def test_guardar_conserva_mayusculas_del_valor_y_acentos_de_la_clave(mem):
    mem.pedir("Recuerda que Mi Cumpleaños es el 3 de Mayo")
    assert mem.hechos() == {"cumpleanos": "el 3 de Mayo"}
    assert mem.yaml()["hechos"]["cumpleanos"]["clave"] == "Cumpleaños"     # la clave visible conserva el acento
    # la misma clave sin acento / con mayúsculas es el mismo dato
    assert mem.pedir("recuerda que MI CUMPLEANOS es el 3 de mayo").startswith("Ya lo tenía guardado")
    assert mem.hechos() == {"cumpleanos": "el 3 de Mayo"}


def test_duplicado_exacto_no_reescribe_el_fichero(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mtime = os.stat(mem.ruta).st_mtime_ns
    assert mem.pedir("recuerda que mi coche es Rojo") == "Ya lo tenía guardado: coche = rojo. No he cambiado nada."
    assert os.stat(mem.ruta).st_mtime_ns == mtime


def test_conflicto_pregunta_y_sustituye(mem):
    """W: el conflicto no sobreescribe y pide la forma explícita (sin respuestas '1/2')."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi ciudad es Bilbao")
    r = mem.pedir("recuerda que mi coche es azul")
    assert r.startswith("Ya tengo guardado que coche es rojo") and "recuerda que ahora coche es azul" in r
    assert mem.hechos() == {"coche": "rojo", "ciudad": "Bilbao"}
    assert mem.pedir("recuerda que ahora mi coche es azul") == "Actualizado: coche = azul (antes era: rojo)."
    assert mem.hechos() == {"coche": "azul", "ciudad": "Bilbao"}   # el dato no relacionado sigue intacto


def test_conflicto_no_anade_listas_de_valores(mem):
    """W: un valor por clave; 'añádelo' no es una operación."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi coche es azul")
    assert mem.pedir("añádelo") is None
    assert mem.hechos() == {"coche": "rojo"}
    assert mem.pedir("recuerda que mi coche es rojo").startswith("Ya lo tenía guardado: coche = rojo")


def test_conflicto_cancelado_no_cambia_nada(mem):
    """W: sin estado pendiente; 'no' y cualquier otro mensaje son conversación."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi coche es azul")
    assert mem.pedir("no") is None
    assert mem.hechos() == {"coche": "rojo"}
    mem.pedir("recuerda que mi coche es verde")
    assert mem.pedir("¿qué hora es?") is None
    assert mem.pedir("1") is None
    assert mem.hechos() == {"coche": "rojo"}


def test_actualizar_explicito_e_implicito(mem):
    """R salvo 'añadir' (W: sin listas) y 'también' (W: conflicto)."""
    mem.pedir("recuerda que mi coche es rojo")
    assert mem.pedir("actualiza mi coche a azul") == "Actualizado: coche = azul (antes era: rojo)."
    assert mem.pedir("mi coche ahora es verde") == "Actualizado: coche = verde (antes era: azul)."
    assert mem.pedir("recuerda que ahora mi coche es negro") == "Actualizado: coche = negro (antes era: verde)."
    assert mem.pedir("update my car to white") == ("I have nothing stored about 'car', so there is nothing to update. "
                                                   "To store it say 'remember that car is white'.")
    assert mem.pedir("change my car to white") is None                   # verbo genérico y 'car' no existe -> conversación
    assert mem.pedir("actualiza mi moto a roja").startswith("No tengo ningún dato guardado sobre 'moto'")
    assert mem.pedir("añade blanco a mi coche") is None
    assert "recuerda que ahora" in mem.pedir("recuerda que mi coche también es gris")
    assert mem.hechos() == {"coche": "negro"}


def test_actualizar_elige_el_corte_que_coincide_con_un_dato(mem):
    mem.pedir("recuerda que mi viaje a Roma es en junio")
    assert mem.pedir("cambia mi viaje a Roma a julio") == "Actualizado: viaje a Roma = julio (antes era: en junio)."


def test_actualizar_con_dos_cortes_guardados_pide_aclaracion(mem):
    """Complemento: con 'viaje' y 'viaje a Roma' guardados el corte es ambiguo y no se toca nada."""
    mem.pedir("recuerda que mi viaje es en mayo")
    mem.pedir("recuerda que mi viaje a Roma es en junio")
    r = mem.pedir("cambia mi viaje a Roma a julio")
    assert "No está claro" in r and mem.hechos() == {"viaje": "en mayo", "viaje a roma": "en junio"}


def test_olvidar_por_clave_exacta_nunca_por_valor(mem):
    """W: el olvido es por clave exacta ('olvida lo de Rex' no borra 'perro'); las notas no existen."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi perro se llama Rex")
    assert mem.pedir("olvida el coche") == "Olvidado: coche (era: rojo). Ya no lo usaré."
    assert mem.pedir("olvida lo de Rex") == "No tenía nada guardado sobre 'Rex'."
    assert mem.hechos() == {"perro": "Rex"}
    assert mem.pedir("olvida mi perro") == "Olvidado: perro (era: Rex). Ya no lo usaré."
    assert mem.pedir("olvida que tengo que llamar a Juan").startswith("No tenía nada guardado")
    assert mem.hechos() == {}


def test_olvidar_con_valor_que_no_coincide(mem):
    """W (sin listas): el valor se comprueba antes de olvidar; si no coincide no se toca nada."""
    mem.pedir("recuerda que mis hijos son Ana")
    assert mem.pedir("olvida que mis hijos son Pedro") == ("Tengo guardado que hijos es Ana, no 'Pedro'. "
                                                           "Si quieres que lo olvide de todos modos dime 'olvida hijos'.")
    assert mem.hechos() == {"hijos": "Ana"}
    assert mem.pedir("olvida que mis hijos son Ana") == "Olvidado: hijos (era: Ana). Ya no lo usaré."
    assert mem.hechos() == {}


def test_olvidar_inexistente_informa_sin_tocar_nada(mem):
    mem.pedir("recuerda que mi coche es rojo")
    assert mem.pedir("olvida mi moto") == "No tenía nada guardado sobre 'moto'."
    assert mem.hechos() == {"coche": "rojo"}
    assert "'reset'" in mem.pedir("olvida la conversación")
    assert mem.hechos() == {"coche": "rojo"}


def test_olvidar_respeta_la_propiedad_y_no_borra_a_ciegas(mem):
    """W: 'coche' es el del usuario; 'el coche de Ana' es otro dato y no se mezcla (sin respuestas numeradas)."""
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    mem.pedir("recuerda que mi moto es negra")
    assert mem.pedir("olvida coche") == "Olvidado: coche (era: rojo). Ya no lo usaré."
    assert mem.hechos() == {"coche de ana": "azul", "moto": "negra"}
    assert mem.pedir("2") is None
    assert "No tenía nada guardado" in mem.pedir("olvida coche")          # ya no hay 'coche' del usuario
    assert mem.hechos() == {"coche de ana": "azul", "moto": "negra"}
    assert mem.pedir("olvida el coche de Ana") == "Olvidado: coche de Ana (era: azul). Ya no lo usaré."
    assert mem.hechos() == {"moto": "negra"}


def test_actualizar_respeta_la_propiedad(mem):
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    assert mem.pedir("actualiza coche a verde") == "Actualizado: coche = verde (antes era: rojo)."
    assert mem.hechos() == {"coche": "verde", "coche de ana": "azul"}


def test_olvidar_todo_requiere_confirmacion(mem):
    """W: confirmación con frase ('olvida todo, confirmo'); 'sí' suelto es conversación."""
    assert mem.pedir("olvida todo") == "No había ningún hecho guardado que olvidar."
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mi moto es negra")
    assert "confirm" in mem.pedir("forget everything")
    assert mem.pedir("mejor no") is None and mem.hechos() == {"coche": "rojo", "moto": "negra"}
    assert "confirmo" in mem.pedir("borra toda tu memoria")
    assert mem.pedir("sí") is None and mem.hechos() == {"coche": "rojo", "moto": "negra"}
    assert mem.pedir("olvida todo, confirmo") == "Hecho: he olvidado los 2 hechos guardados."
    assert mem.hechos() == {}


def test_peticion_de_guardar_sin_contenido_pide_aclaracion(mem):
    r = mem.pedir("recuerda esto")
    assert r.startswith("No he entendido qué dato debo recordar") and "recuerda que <clave> es <valor>" in r
    assert mem.pedir("acuérdate de mi cumpleaños").startswith("No he entendido qué dato debo recordar")
    assert mem.pedir("remember the milk").startswith("I couldn't tell which fact to store")
    assert not mem.ruta.exists()


def test_consultar_y_listar(mem):
    assert mem.pedir("¿qué recuerdas?") == ("Aún no tengo ningún hecho guardado. "
                                           "Dime 'recuerda que <clave> es <valor>' para guardar uno.")
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que el coche de Ana es azul")
    mem.pedir("recuerda que mi llamada pendiente es a Juan")
    assert mem.pedir("¿qué sabes de mi coche?") == "Sí, lo recuerdo: coche es rojo."
    assert mem.pedir("what do you remember about llamada pendiente?") == "Yes, I remember: llamada pendiente is a Juan."
    assert mem.pedir("¿qué recuerdas del coche?") is None             # 'del' no es un conector reconocido
    assert mem.pedir("¿qué recuerdas sobre coche?") == "Sí, lo recuerdo: coche es rojo."   # W: propiedad: sólo el del usuario
    assert mem.pedir("¿qué recuerdas de mi moto?") == "No tengo nada guardado sobre 'moto'."
    assert mem.pedir("¿qué sabes de mi moto?") is None                # 'sabes' sin dato: pregunta general para el modelo
    assert mem.pedir("ver hechos") == ("Tengo 3 hecho(s) guardado(s):\n- coche: rojo\n- coche de Ana: azul\n"
                                       "- llamada pendiente: a Juan")


# =========================================================================== contexto para el motor y fichero
def test_contexto_para_el_motor(mem):
    """W: cabecera y formato actuales; un valor por clave; sin notas."""
    assert m.get_memory_context() == ""                 # sin fichero: sin mensaje de memoria
    mem.pedir("recuerda que mi coche es rojo")
    mem.pedir("recuerda que mis hijos son Ana y Luis")
    ctx = m.get_memory_context()
    assert ctx.startswith("Hechos que el usuario pidió recordar (memoria persistente):")
    assert ctx.endswith("- coche: rojo\n- hijos: Ana y Luis")
    mem.pedir("olvida mis hijos")
    assert "hijos" not in m.get_memory_context() and "- coche: rojo" in m.get_memory_context()


def test_formato_antiguo_se_migra_y_las_otras_secciones_se_conservan(mem):
    """W: TODO el perfil antiguo se migra a hechos (consultables, editables y olvidables)
    con copia de seguridad; nada se inyecta dos veces."""
    mem.perfil.write_text(
        "aprendido_durante_sesion:\n  mi coche: rojo\n"
        "vida_personal:\n  pareja:\n    nombre: Ana\n  vehiculo: una camper\n"
        "entorno:\n  sistemas_operativos: [ubuntu, windows]\n", encoding="utf-8")
    assert mem.hechos() == {"coche": "rojo", "pareja nombre": "Ana", "vehiculo": "una camper",
                            "sistemas operativos": "ubuntu, windows"}
    ctx = m.get_memory_context()
    assert "- coche: rojo" in ctx and ctx.count("coche") == 1            # antes aparecía duplicado
    assert "- pareja nombre: Ana" in ctx and "- vehiculo: una camper" in ctx
    assert "- sistemas operativos: ubuntu, windows" in ctx
    assert mem.pedir("recuerda que mi ciudad es Bilbao").startswith("Hecho guardado")
    assert mem.hechos()["ciudad"] == "Bilbao"
    assert yaml.safe_load(mem.perfil.read_text(encoding="utf-8")) == {"aprendido_durante_sesion": {}}
    copias = list(mem.perfil.parent.glob("user_profile.yaml.legado-*.bak"))
    assert len(copias) == 1 and "vehiculo: una camper" in copias[0].read_text(encoding="utf-8")
    assert "Olvidado" in mem.pedir("olvida mi vehiculo") and "camper" not in m.get_memory_context()


def test_fichero_vacio_o_ausente_se_trata_como_memoria_vacia(mem):
    assert mem.hechos() == {} and m.get_memory_context() == ""
    mem.ruta.write_text("", encoding="utf-8")
    assert mem.hechos() == {} and m.get_memory_context() == ""
    assert mem.pedir("recuerda que mi coche es rojo").startswith("Hecho guardado")
    assert mem.hechos() == {"coche": "rojo"}


@pytest.mark.parametrize("contenido", [
    "hechos: [esto, no, es, un, mapa\n",           # YAML inválido
    "- una\n- lista\n",                               # válido pero no es un mapa
    "version: 1\nhechos: [lista]\n",                  # sección con el tipo equivocado
    "version: 1\nhechos: {}\nnotas: {a: b}\n",        # clave desconocida en el esquema
    "\xff\xfe binario",
])
def test_fichero_corrupto_no_se_sobrescribe_y_no_rompe_el_contexto(mem, contenido, capsys):
    mem.ruta.write_bytes(contenido.encode("utf-8", "surrogateescape"))
    original = mem.ruta.read_bytes()
    assert m.get_memory_context() == ""
    assert "memoria de hechos dañada" in capsys.readouterr().out
    r = mem.pedir("recuerda que mi coche es rojo")
    assert r.startswith("No puedo usar la memoria persistente") and "No lo modificaré" in r
    assert mem.pedir("olvida todo, confirmo").startswith("No puedo usar la memoria persistente")
    assert mem.pedir("¿qué recuerdas?").startswith("No puedo usar la memoria persistente")
    assert mem.ruta.read_bytes() == original
    assert not any(f.startswith(".facts-") for f in os.listdir(mem.ruta.parent))   # sin temporales huérfanos
    with pytest.raises(m.MemoriaHechosInvalida):
        m.listar_hechos()


def test_fallo_de_escritura_no_destruye_los_datos_ni_informa_exito(mem):
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
    assert mem.pedir("recuerda que mi ciudad es Bilbao").startswith("Hecho guardado")   # recuperado: vuelve a funcionar


def test_directorio_de_solo_lectura(mem):
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
    mem.pedir("recuerda que mi coche es rojo")
    monkeypatch.setattr(m, "_escribir_atomico", lambda ruta, contenido, prefijo: None)   # "escribe" sin escribir
    r = mem.pedir("recuerda que mi ciudad es Bilbao")
    assert r.startswith("No he podido guardar el cambio") and "verificación" in r
    assert mem.hechos() == {"coche": "rojo"}


def test_el_fichero_se_crea_con_directorios_intermedios(memoria_temporal, monkeypatch):
    ruta = memoria_temporal.dir / "config" / "data" / "facts.yaml"
    monkeypatch.setattr(m, "FACTS_PATH", str(ruta))
    assert procesar_comando_memoria("recuerda que mi coche es rojo").startswith("Hecho guardado")
    assert yaml.safe_load(ruta.read_text(encoding="utf-8"))["hechos"]["coche"]["valor"] == "rojo"
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600


def test_historial_ilegible_se_aparta_en_vez_de_sobrescribirse(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(m, "SESSION_FILE", str(tmp_path / "historial.json"))
    (tmp_path / "historial.json").write_text("{corrupto", encoding="utf-8")
    assert m.load_full_history() == []
    assert "conservado en" in capsys.readouterr().out
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
