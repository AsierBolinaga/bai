"""
Aprendizaje natural local (fase 7): interpretación de las peticiones de memoria
en lenguaje natural — recordar, consultar, actualizar y olvidar hechos.

Principios (los mismos que los comandos de modo de core/ai_engine.py):

- Intención de memoria EXPLÍCITA. El mensaje completo debe ser una petición
  de memoria, con vocativo "B.A.I," y cortesías opcionales. Sólo escriben:
    · verbos que significan recordar/olvidar por sí mismos: recuerda, no
      olvides, memoriza, aprende, ten en cuenta, quiero que recuerdes, olvida,
      ya no recuerdes, remember, don't forget, keep in mind, learn, forget...
    · verbos genéricos (guarda, anota, apunta, borra, elimina, actualiza,
      cambia, save, note, store, delete, update, set...) SÓLO acompañados de un
      objeto de memoria explícito: "en tu memoria", "como hecho", "el hecho X",
      "lo que recuerdas de X", "in your memory", "the fact X"...
  Un comando genérico sin ese objeto ("guarda X", "set X to Y", "borra X") es
  conversación normal: no guarda, no cambia y no borra ningún hecho.
- Nada se aprende en silencio: frases afirmativas, preguntas, negaciones
  ("no recuerdes que...", "mi coche no es rojo"), ejemplos entrecomillados y
  comandos incrustados en otra frase NUNCA modifican la memoria. Las negaciones
  explícitas se contestan localmente sin escribir.
- Propiedad: "mi coche" y "el coche" son el mismo hecho; "tu coche", "su
  coche" o "el coche de Ana" son hechos distintos y no se mezclan.
- Todo el procesamiento es local y determinista: no se consulta ningún motor
  ni servicio, en ningún modo (tampoco con el prefijo "online:").
- Sólo se confirma una operación cuando la escritura en disco ha terminado
  bien; un fichero dañado, ilegible o con esquema desconocido se comunica sin
  tocarlo (ver core/memory_engine.py).
- Ante ambigüedad (hecho sin clave/valor claros, varios hechos candidatos,
  valor en conflicto, negación, borrado total) se pide aclaración o
  confirmación localmente en lugar de adivinar.

La única función pública es procesar_comando_memoria(texto) -> str | None.
Devuelve None si el texto no es una petición de memoria (mensaje normal).
"""
import re
import unicodedata

from core import memory_engine
from core.memory_engine import (ErrorLecturaMemoria, MemoriaHechosInvalida, clave_sin_articulo,
                                limpiar_valor, normalizar_clave)

# --------------------------------------------------------------------------- textos (es / en)
MENSAJES = {
    "es": {
        "guardado": "Hecho guardado: {clave} = {valor}. Lo recordaré entre sesiones.",
        "duplicado": "Ya lo tenía guardado: {clave} = {valor}. No he cambiado nada.",
        "conflicto": ("Ya tengo guardado que {clave} es {anterior}. No lo he sobreescrito: "
                      "si quieres reemplazarlo dime 'recuerda que ahora {clave} es {valor}'."),
        "actualizado": "Actualizado: {clave} = {valor} (antes era: {anterior}).",
        "creado": "No tenía ese dato; lo guardo ahora: {clave} = {valor}.",
        "olvidado": "Olvidado: {clave} (era: {valor}). Ya no lo usaré.",
        "no_existia": "No tenía nada guardado sobre '{clave}'.",
        "olvidar_conflicto": ("Tengo guardado que {clave} es {anterior}, no '{valor}'. "
                              "Si quieres que lo olvide de todos modos dime 'olvida {clave}'."),
        "sugerencias": "No tengo nada guardado como '{clave}'. Quizá te refieres a: {lista}.",
        "recuperado": "Sí, lo recuerdo: {clave} es {valor}.",
        "confirmado": "Sí: {clave} es {valor}.",
        "desmentido": "No exactamente: tengo guardado que {clave} es {anterior}.",
        "no_se": "No tengo nada guardado sobre '{clave}'.",
        "lista_cabecera": "Tengo {n} hecho(s) guardado(s):",
        "lista_vacia": "Aún no tengo ningún hecho guardado. Dime 'recuerda que <clave> es <valor>' para guardar uno.",
        "aclarar_hecho": ("No he entendido qué dato debo recordar. "
                          "Dímelo como 'recuerda que <clave> es <valor>' (p. ej. 'recuerda que mi coche es rojo')."),
        "aclarar_negado": ("Es una negación y no guardo negaciones. Si el dato tiene un valor nuevo dime "
                           "'recuerda que ahora <clave> es <valor>'; si quieres que lo olvide, 'olvida <clave>'."),
        "aclarar_citado": ("Eso va entre comillas, así que lo tomo como un ejemplo y no toco la memoria. "
                           "Si es una petición real, repítemela sin comillas."),
        "aclarar_actualizar": ("No he entendido qué dato debo actualizar. "
                               "Dímelo como 'recuerda que ahora <clave> es <valor>'."),
        "aclarar_olvidar": "¿Qué quieres que olvide exactamente? Dímelo como 'olvida <clave>' (p. ej. 'olvida mi coche').",
        "no_guardare": "De acuerdo: no guardaré nada sobre eso.",
        "no_guardare_existe": ("De acuerdo: no guardaré nada nuevo. Ahora mismo tengo guardado que {clave} es {valor}; "
                               "si quieres que lo borre dime 'olvida {clave}'."),
        "pedir_confirmacion": ("Eso borraría los {n} hechos guardados y no se puede deshacer. "
                               "Si estás seguro escribe: 'olvida todo, confirmo'."),
        "todo_olvidado": "Hecho: he olvidado los {n} hechos guardados.",
        "nada_que_olvidar": "No había ningún hecho guardado que olvidar.",
        "danada": ("No puedo usar la memoria persistente: el fichero {ruta} está dañado o tiene un formato "
                   "desconocido ({error}). No lo modificaré para no perder datos; corrígelo o renómbralo y vuelve a intentarlo."),
        "ilegible": ("No puedo leer la memoria persistente ({ruta}): {error}. "
                     "No he modificado nada; revisa los permisos del fichero."),
        "no_guardado": ("No he podido guardar el cambio ({error}). La memoria anterior queda intacta: "
                        "NINGÚN cambio de esta petición se ha guardado."),
        "aclarar_clave": ("No está claro a qué dato te refieres ({opciones}). Para no tocar el dato equivocado no he "
                          "cambiado nada; dímelo con la clave completa: 'recuerda que ahora <clave> es <valor>'."),
        "aclarar_ejemplo": ("Eso parece un ejemplo, así que no toco la memoria. "
                            "Si es una petición real, repítemela sin 'por ejemplo'."),
        "contradictorio": ("Tu petición contiene instrucciones contradictorias o mezcladas, así que no he cambiado nada. "
                           "Pídeme una sola operación de memoria por mensaje."),
        "aclarar_consulta": "¿Qué quieres que consulte? Pregúntame '¿cuál es mi <clave>?' o '¿qué recuerdas?' para verlo todo.",
        "aclarar_varios": ("Sólo guardo un valor por dato, así que no he cambiado nada. Si quieres sustituirlo dime "
                           "'recuerda que ahora <clave> es <valor>'."),
        "sugerencias_consulta": ("No tengo nada guardado exactamente como '{clave}'. Quizá te refieres a: {lista}. "
                                 "Pregúntamelo con el nombre completo."),
    },
    "en": {
        "guardado": "Fact stored: {clave} = {valor}. I will remember it across sessions.",
        "duplicado": "I already knew that: {clave} = {valor}. Nothing changed.",
        "conflicto": ("I already have {clave} = {anterior}. I did not overwrite it: "
                      "say 'remember that now {clave} is {valor}' if you want to replace it."),
        "actualizado": "Updated: {clave} = {valor} (was: {anterior}).",
        "creado": "I didn't have that one; stored now: {clave} = {valor}.",
        "olvidado": "Forgotten: {clave} (was: {valor}). I will no longer use it.",
        "no_existia": "I had nothing stored about '{clave}'.",
        "olvidar_conflicto": ("I have {clave} = {anterior}, not '{valor}'. "
                              "Say 'forget {clave}' if you want me to drop it anyway."),
        "sugerencias": "I have nothing stored as '{clave}'. Did you mean: {lista}?",
        "recuperado": "Yes, I remember: {clave} is {valor}.",
        "confirmado": "Yes: {clave} is {valor}.",
        "desmentido": "Not exactly: I have {clave} = {anterior}.",
        "no_se": "I have nothing stored about '{clave}'.",
        "lista_cabecera": "I have {n} stored fact(s):",
        "lista_vacia": "I have no stored facts yet. Say 'remember that <key> is <value>' to store one.",
        "aclarar_hecho": ("I couldn't tell which fact to store. "
                          "Say it like 'remember that <key> is <value>' (e.g. 'remember that my car is red')."),
        "aclarar_negado": ("That is a negation and I don't store negations. If the fact has a new value say "
                           "'remember that now <key> is <value>'; if you want me to drop it, 'forget <key>'."),
        "aclarar_citado": ("That is in quotes, so I take it as an example and won't touch memory. "
                           "If it is a real request, repeat it without quotes."),
        "aclarar_actualizar": "I couldn't tell which fact to update. Say it like 'remember that now <key> is <value>'.",
        "aclarar_olvidar": "What exactly should I forget? Say it like 'forget <key>' (e.g. 'forget my car').",
        "no_guardare": "Understood: I won't store anything about that.",
        "no_guardare_existe": ("Understood: I won't store anything new. Right now I have {clave} = {valor}; "
                               "say 'forget {clave}' if you want me to drop it."),
        "pedir_confirmacion": ("That would erase all {n} stored facts and cannot be undone. "
                               "If you are sure, write: 'forget everything, confirm'."),
        "todo_olvidado": "Done: I forgot all {n} stored facts.",
        "nada_que_olvidar": "There were no stored facts to forget.",
        "danada": ("I can't use persistent memory: the file {ruta} is corrupted or has an unknown format ({error}). "
                   "I won't touch it so no data is lost; fix or rename it and try again."),
        "ilegible": "I can't read persistent memory ({ruta}): {error}. Nothing was modified; check the file permissions.",
        "no_guardado": ("I couldn't save the change ({error}). Previous memory is intact: "
                        "NO change from this request was saved."),
        "aclarar_clave": ("It is not clear which fact you mean ({opciones}). To avoid changing the wrong one I changed "
                          "nothing; say it with the full key: 'remember that now <key> is <value>'."),
        "aclarar_ejemplo": "That looks like an example, so I won't touch memory. If it is a real request, repeat it without 'for example'.",
        "contradictorio": ("Your request contains contradictory or mixed instructions, so I changed nothing. "
                           "Ask for one memory operation per message."),
        "aclarar_consulta": "What should I look up? Ask 'what is my <key>?' or 'what do you remember?' to see everything.",
        "aclarar_varios": ("I keep a single value per fact, so I changed nothing. To replace it say "
                           "'remember that now <key> is <value>'."),
        "sugerencias_consulta": ("I have nothing stored exactly as '{clave}'. Did you mean: {lista}? "
                                 "Ask me with the full name."),
    },
}

_RE_INGLES = re.compile(r"\b(remember|forget|keep|bear|memorize|memorise|note|learn|save|"
                        r"store|update|change|set|correct|delete|remove|erase|stop|what|what's|"
                        r"show|list|tell|do|don't|my|everything|all|memory|fact|never|not)\b")


def _idioma(fragmento):
    return "en" if _RE_INGLES.search(fragmento.lower()) else "es"


def _msg(idioma, codigo, **kw):
    return MENSAJES[idioma][codigo].format(**kw)


# --------------------------------------------------------------------------- normalización alineada
def _plano(texto):
    """Copia en minúsculas y sin acentos, de la MISMA longitud que el original,
    para poder proyectar los grupos de las regex sobre el texto original."""
    salida = []
    for car in texto:
        base = "".join(c for c in unicodedata.normalize("NFKD", car) if not unicodedata.combining(c))
        salida.append(base if len(base) == 1 else car)
    return "".join(salida).lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


_PARES_COMILLAS = {('"', '"'), ("'", "'"), ("«", "»"), ("“", "”"), ("‘", "’"), ("`", "`")}


def _entre_comillas(texto):
    """True si el texto completo está entrecomillado: es un ejemplo, no una orden."""
    texto = texto.strip()
    if len(texto) >= 2 and (texto[0], texto[-1]) in _PARES_COMILLAS:
        return True
    return texto.startswith("<<") and texto.endswith(">>")


# --------------------------------------------------------------------------- gramática
_VOCATIVO = r"(?:b\.?a\.?i\.?\s*[,:]?\s+)?"
_CORTESIA = r"(?:por\s+favor[,]?\s+|please[,]?\s+|oye[,]?\s+|hey[,]?\s+)?"
_INI = r"^" + _VOCATIVO + _CORTESIA + _VOCATIVO
_FIN = r"(?:[,]?\s+por\s+favor|[,]?\s+please)?\s*[.!]*\s*$"
_FIN_PREGUNTA = r"(?:[,]?\s+por\s+favor|[,]?\s+please)?\s*[.!?]*\s*$"
_PREG = r"(?:[¿¡]\s*)?"
_QUE = r"(?:\s+(?:que|de\s+que|that))?"
_CORT_MEDIO = r"(?:\s*,\s*(?:por\s+favor|please)\s*,?|\s*,)?"   # "recuerda, por favor, que ..."

# Objeto de memoria explícito que convierte un verbo genérico en una petición de memoria.
_OBJ_MEMORIA = (r"(?:(?:en|a|de)\s+)?(?:tu\s+|la\s+|mi\s+|your\s+|the\s+)?(?:memoria|memory)"
                r"|(?:como|este|ese|el|un)\s+(?:hecho|dato)|(?:as|this|that|the)\s+(?:a\s+)?fact"
                r"|(?:in|to|into|from)\s+(?:your\s+)?memory|(?:lo\s+que|what\s+you)\s+(?:recuerdas|remember|sabes|know)")
_OBJ = r"(?:" + _OBJ_MEMORIA + r")"

# 1) Verbos con intención de memoria inequívoca: admiten el hecho directamente.
_V_RECORDAR = (r"(?P<verbo>recuerda|acuerdate\s+de|no\s+olvides|no\s+te\s+olvides\s+de|memoriza|"
               r"ten\s+en\s+cuenta|quiero\s+que\s+recuerdes|necesito\s+que\s+recuerdes|"
               r"remember|don'?t\s+forget|do\s+not\s+forget|keep\s+in\s+mind|bear\s+in\s+mind|"
               r"memorize|memorise)")
# 1b) Verbos que también tienen usos no relacionados con la memoria ("aprende python",
#     "learn how to cook") o formas corteses: exigen 'que'/'that'/':' antes del hecho.
_V_RECORDAR_MARCADO = (r"(?P<verbo>aprendete|aprende|learn|me\s+gustaria\s+que\s+recordaras|"
                       r"(?:puedes|podrias)\s+recordar|(?:i\s+want|i'?d\s+like)\s+you\s+to\s+remember|"
                       r"(?:could|can|would)\s+you(?:\s+please)?\s+remember)")
# 2) Verbos genéricos: sólo con objeto de memoria explícito.
_V_GENERICO_STORE = (r"(?P<verbo>guarda|guardate|graba|almacena|anota|anotame|apunta|apuntame|"
                     r"toma\s+nota|registra|save|store|note|note\s+down|write\s+down|make\s+a\s+note|"
                     r"record|jot\s+down|keep)")

_P_RECORDAR = [
    re.compile(_INI + _V_RECORDAR + _CORT_MEDIO + r"(?:\s+" + _OBJ + r")?" + r"(?:\s+(?:que|that|esto|this|de\s+que))?"
               r"\s*:?\s+(?P<hecho>.+?)" + _FIN, re.S),
    re.compile(_INI + _V_RECORDAR_MARCADO + _CORT_MEDIO + r"(?:\s+(?:que|that|esto|this)\s*:?|\s*:)\s+(?P<hecho>.+?)" + _FIN, re.S),
    re.compile(_INI + _V_GENERICO_STORE + r"(?:\s+(?:esto|this|lo\s+siguiente|the\s+following))?\s*[:,]?\s*"
               r"(?:\s*" + _OBJ + r")" + r"(?:\s+(?:que|that|de\s+que|esto|this))?\s*:?\s+(?P<hecho>.+?)" + _FIN, re.S),
]

# Negación explícita de una petición de memoria: se contesta localmente y no se escribe nada.
_P_NEGADO = re.compile(
    _INI + r"(?P<verbo>(?:no|nunca|jamas|no\s+quiero\s+que|no\s+hace\s+falta\s+que|"
    r"don'?t|do\s+not|never|i\s+don'?t\s+want\s+you\s+to|you\s+don'?t\s+need\s+to|please\s+don'?t)\s+"
    r"(?:recuerdes|guardes|memorices|apuntes|anotes|aprendas|grabes|almacenes|registres|te\s+acuerdes\s+de|"
    r"remember|save|store|learn|memorize|memorise|note|record|keep))(?!\s+mas\b)" + _QUE + r"\s*:?\s*(?P<hecho>.*)$", re.S)

# Actualización explícita: "recuerda que ahora X es Y" (en _P_RECORDAR) o verbo genérico + objeto de memoria.
_V_ACTUALIZAR = r"(?P<verbo>actualiza|cambia|corrige|modifica|rectifica|update|change|set|correct|fix)"
# actualiza en tu memoria X a Y | X: Y   /   corrige tu memoria: X es Y | que X es Y
_P_ACTUALIZAR = re.compile(_INI + _V_ACTUALIZAR + r"\s+" + _OBJ + r"(?:\s+de|\s+about)?"
                           r"(?P<marca>\s*[:,]\s*|\s+(?:que|that)\s+|\s+)(?P<resto>.+?)" + _FIN, re.S)

# Olvidar: verbos inequívocos (objeto opcional) o genéricos con objeto de memoria.
_V_OLVIDAR = (r"(?P<verbo>olvidate\s+de|olvidate|olvida|ya\s+no\s+recuerdes|deja\s+de\s+recordar|"
              r"no\s+recuerdes\s+mas|forget\s+about|forget|stop\s+remembering)")
_V_GENERICO_FORGET = r"(?P<verbo>borra|elimina|quita|descarta|delete|remove|erase|drop|clear)"
_SUFIJO_MEMORIA = r"(?:\s+(?:de|from)\s+(?:tu\s+|la\s+|your\s+|the\s+)?(?:memoria|memory))?"
# "borra (toda) tu memoria" / "erase your memory": petición de borrado total (pide confirmación)
_P_BORRAR_MEMORIA = re.compile(_INI + _V_GENERICO_FORGET + r"\s+(?:toda\s+|all\s+(?:of\s+)?)?(?:tu|la|your|the)\s+"
                               r"(?:memoria|memory)(?:\s+persistente)?" + _FIN, re.S)
# "lo de X", "(todo) lo que sabes de X", "everything about X": se queda sólo X
_P_PREFIJO_OLVIDO = re.compile(r"^(?:(?:todo\s+)?lo\s+que\s+(?:sabes|recuerdas|tienes\s+guardado)\s+(?:de|sobre|acerca\s+de)\s+"
                               r"|lo\s+de\s+|(?:everything|all)\s+(?:you\s+know\s+)?about\s+|what\s+you\s+know\s+about\s+)")
_SOBRE_MI = {"mi", "me", "mi mismo", "mi misma", "myself"}
_P_OLVIDAR = [
    re.compile(_INI + _V_OLVIDAR + _CORT_MEDIO + r"(?:\s+" + _OBJ + r"(?:\s+de|\s+about)?)?" + _QUE + r"\s*:?\s+(?P<resto>.+?)"
               + _SUFIJO_MEMORIA + _FIN, re.S),
    # borra de tu memoria X / elimina el hecho X / delete the fact X / remove X from your memory
    re.compile(_INI + _V_GENERICO_FORGET + r"\s+" + _OBJ + r"(?:\s+de|\s+about)?" + _QUE + r"\s*:?\s+(?P<resto>.+?)"
               + _SUFIJO_MEMORIA + _FIN, re.S),
    re.compile(_INI + _V_GENERICO_FORGET + _QUE + r"\s+(?P<resto>.+?)\s+(?:de|from)\s+(?:tu\s+|la\s+|your\s+)?(?:memoria|memory)" + _FIN, re.S),
]

_TOTALES = {"todo", "todos los hechos", "todos tus hechos", "todos los datos", "toda tu memoria",
            "toda la memoria", "la memoria", "tu memoria", "everything", "all facts", "all the facts",
            "all your facts", "your memory", "all stored facts", "all"}
_PRONOMBRES = {"eso", "esto", "lo", "eso ultimo", "esto ultimo", "it", "that", "this", "about it"}
_P_CONFIRMA_TODO = re.compile(r"^(?:todo|todos\s+los\s+hechos|everything|all\s+facts|all)[,]?\s+"
                              r"(?:confirmo|lo\s+confirmo|confirm(?:ed)?|i\s+confirm)$")

_POSESIVO = r"(?:mi|mis|my)\s+"
_P_RECUPERAR = [
    # ¿qué sabes de MI X? / what do you know about MY X?  (sin posesivo es una pregunta general)
    re.compile(_INI + _PREG + r"(?:dime|tell\s+me)?\s*(?P<verbo>que\s+sabes|what\s+do\s+you\s+know)\s+"
               r"(?:de|sobre|acerca\s+de|about)\s+(?P<clave>" + _POSESIVO + r".+?)" + _FIN_PREGUNTA, re.S),
    # ¿qué recuerdas (de X)? / what do you remember (about X)? / ¿qué tienes guardado sobre X? ...
    re.compile(_INI + _PREG + r"(?:dime|tell\s+me)?\s*(?P<verbo>que\s+recuerdas|lo\s+que\s+recuerdas|"
               r"que\s+tienes\s+guardado|que\s+has\s+guardado|what\s+have\s+you\s+(?:saved|stored)|"
               r"what\s+do\s+you\s+remember|what\s+you\s+remember)"
               r"(?:\s+(?:de|sobre|acerca\s+de|about)\s+(?P<clave>.+?))?" + _FIN_PREGUNTA, re.S),
    # ¿(no) recuerdas (que) X (es Y)? / do(n't) you remember (that) X?
    re.compile(_INI + _PREG + r"(?:no\s+)?(?P<verbo>te\s+acuerdas\s+de\s+que|te\s+acuerdas\s+de|te\s+acuerdas|"
               r"recuerdas\s+que|recuerdas|do\s+you\s+remember\s+that|do\s+you\s+remember|"
               r"don'?t\s+you\s+remember)\s+(?P<resto>.+?)" + _FIN_PREGUNTA, re.S),
    # ¿cuál es mi X? / what is my X?  (sólo con posesivo: lo demás es una pregunta normal)
    re.compile(_INI + _PREG + r"(?P<verbo>cual\s+es|cuales\s+son|what\s+is|what's|what\s+are)\s+"
               r"(?P<clave>" + _POSESIVO + r".+?)" + _FIN_PREGUNTA, re.S),
    # muestra/lista tus hechos / show your facts / ver hechos
    re.compile(_INI + _PREG + r"(?P<verbo>muestra(?:me)?|lista(?:me)?|ensena(?:me)?|ver|show(?:\s+me)?|list)\s+"
               r"(?:tus\s+|los\s+|mis\s+|the\s+|your\s+|my\s+|stored\s+|saved\s+)*"
               r"(?:hechos|recuerdos|datos\s+guardados|memoria\s+persistente|facts|memories)"
               r"(?:\s+guardados|\s+que\s+recuerdas)?" + _FIN_PREGUNTA, re.S),
    # muestra tu memoria / enséñame la memoria / show me your memory ('ver memoria' sigue siendo el comando
    # de historial de la CLI) y ¿qué sabes de mí? / ¿qué has aprendido? / what do you know about me?
    re.compile(_INI + _PREG + r"(?P<verbo>muestra(?:me)?|ensena(?:me)?|show(?:\s+me)?|ver)\s+(?:tu|la|your|the)\s+"
               r"(?:memoria|memory)(?:\s+persistente)?" + _FIN_PREGUNTA, re.S),
    re.compile(_INI + _PREG + r"(?:dime|tell\s+me|muestrame|ensename|show\s+me)?\s*(?P<verbo>que\s+sabes|que\s+recuerdas|"
               r"lo\s+que\s+sabes|lo\s+que\s+recuerdas|what\s+do\s+you\s+know|what\s+do\s+you\s+remember|"
               r"what\s+you\s+know)\s+(?:de|sobre|acerca\s+de|about)\s+(?:mi|me|mi\s+mism[oa]|myself)" + _FIN_PREGUNTA, re.S),
    re.compile(_INI + _PREG + r"(?P<verbo>que\s+has\s+aprendido|what\s+have\s+you\s+learn(?:ed|t))" + _FIN_PREGUNTA, re.S),
]

# Separadores clave/valor, por prioridad. Se usa el primer tipo presente y se
# enumeran TODAS sus posiciones para resolver la clave completa antes de escribir.
_SEP_HECHO = [
    r"\s+se\s+llaman?\s+",
    r"'s\s+name\s+is\s+",
    r"\s+(?:es|son)\s+",
    r"\s+(?:is|are)\s+",
    r"\s+(?:esta|estan)\s+",                  # "mi coche está en el garaje"
    r"\s*[:=]\s*",
]
# Una clave no puede ser una oración subordinada ("tengo que llamar a Juan porque es su cumpleaños").
_P_CLAVE_SUBORDINADA = re.compile(r"\b(?:porque|because|cuando|when|aunque|although|though|si|if|ya\s+que|since|pero|but)\b")
# "ahora"/"now" pegado a la clave o al valor indica actualización, nunca forma parte del dato.
_P_AHORA_CLAVE = re.compile(r"[\s,]+(?:ahora|now)$")
_P_AHORA_VALOR = re.compile(r"^(?:ahora|now)\s+(?:(?:es|son|is|are)\s+)?")
# Hechos con varios valores ("también", "also"): sólo se guarda un valor por dato.
_P_VARIOS_VALORES = re.compile(r"\b(?:tambien|ademas|also|too|as\s+well)\b")
_SEP_A = [r"\s*[:=]\s*", r"\s+(?:a|por|to)\s+"]   # "X a Y": 'a' también aparece dentro de claves ("viaje a Roma")
# Un hecho negado nunca se guarda tal cual ("mi coche no es rojo" no define ningún valor).
_P_NEGACION_HECHO = re.compile(
    r"^(?:no|nunca|jamas|not|never|ya\s+no)\b"
    r"|\b(?:no|nunca|jamas|tampoco)\s+(?:es|son|era|eran|esta|estan|se\s+llaman?|vale|tengo|tiene)\b"
    r"|\b(?:ya\s+no)\b|\bno\s+longer\b|\bnot\s+anymore\b"
    r"|\b(?:is|are|was|were)\s*(?:n't|not)\b|\b(?:isn't|aren't|wasn't|weren't)\b", re.S)
_P_AHORA = re.compile(r"^(?:ahora|a\s+partir\s+de\s+ahora|desde\s+ahora|now|from\s+now\s+on)[,]?\s+(.+)$", re.S)
_P_SEPARADOR_HECHOS = re.compile(r"\s*(?:;|,\s+y\s+|\s+y\s+|,\s+and\s+|\s+and\s+)\s*", re.S)
# Ejemplos: nunca son peticiones reales.
_P_EJEMPLO = re.compile(r"\b(?:por\s+ejemplo|como\s+ejemplo|ejemplo|supongamos|imagina|hipoteticamente|"
                        r"for\s+example|for\s+instance|as\s+an\s+example|example|suppose|hypothetically)\b"
                        r"|\b(?:p\.\s*ej\.?|e\.\s*g\.?)(?=\s|,|$)")
# Comillas de cita (no apóstrofos dentro de palabras como "Ana's" o "don't").
_P_CITA = re.compile(r"[\"«»“”]|<<|>>|(?:^|\s)['‘`]|['’`](?:\s|$|[.,;:!?])")
# Otra operación de memoria encadenada a la petición ("...y olvídalo", "..., no lo guardes"):
_P_CONTRADICCION = re.compile(
    r"(?:^(?:y|e|pero|and|but)\s+|[,;]\s*(?:(?:y|e|pero|and|but|then|luego)\s+)?"
    r"|\s(?:y|e|pero|aunque|luego|despues|and|but|then|though)\s+)"
    r"(?:no\s+lo\s+|no\s+la\s+|no\s+|nunca\s+|don'?t\s+|do\s+not\s+|never\s+)?"
    r"\b(?:recuerda(?:lo|la)?|recuerdes|acuerdate|olvida(?:lo|la)?|olvides|olvidate|guarda(?:lo|la)?|guardes|"
    r"borra(?:lo|la)?|borres|elimina(?:lo|la)?|elimines|memoriza(?:lo|la)?|memorices|"
    r"remember|forget|save|store|delete|remove|erase)\b")


def _divisiones(original, plano, separadores):
    """Todas las formas de partir el texto en (clave, valor) con el primer tipo
    de separador presente. [] si no hay ninguna pareja clara. Se descartan las
    claves que son oraciones subordinadas y se quita 'ahora'/'now' de los extremos."""
    for sep in separadores:
        candidatos = []
        for m in re.finditer(sep, plano):
            c_ini, c_fin, v_ini = 0, m.start(), m.end()
            clave_plano = plano[c_ini:c_fin]
            if _P_CLAVE_SUBORDINADA.search(clave_plano):
                continue
            a = _P_AHORA_CLAVE.search(clave_plano)
            if a:
                c_fin = a.start()
            b = _P_AHORA_VALOR.match(plano[v_ini:])
            if b:
                v_ini += b.end()
            clave, valor = original[c_ini:c_fin], original[v_ini:]
            if normalizar_clave(clave) and limpiar_valor(valor):
                candidatos.append((clave, valor))
        if candidatos:
            return candidatos
    return []


def _marca_ahora(plano):
    """True si el hecho contiene 'ahora'/'now' junto al separador (actualización explícita)."""
    return bool(re.search(r"(?:\s|,)(?:ahora|now)\s+(?:es|son|is|are)\s|\s(?:es|son|is|are)\s+(?:ahora|now)\s"
                          r"|[:=]\s*(?:ahora|now)\s", " " + plano + " "))


def _parse_hecho(original, plano):
    """Primera pareja (clave, valor) — sólo para lecturas; las escrituras
    resuelven todas las divisiones posibles con _resolver()."""
    candidatos = _divisiones(original, plano, _SEP_HECHO)
    return candidatos[0] if candidatos else None


def _parse_hechos(original, plano, separadores=_SEP_HECHO):
    """Lista de hechos; cada hecho es la lista de sus divisiones posibles.
    "X es A y Y es B" se divide sólo si TODAS las partes son parejas claras."""
    partes, pos = [], 0
    for m in _P_SEPARADOR_HECHOS.finditer(plano):
        partes.append((pos, m.start()))
        pos = m.end()
    partes.append((pos, len(plano)))
    if len(partes) > 1:
        divisiones = [_divisiones(original[a:b], plano[a:b], separadores) for a, b in partes]
        if all(divisiones):
            return divisiones
    completo = _divisiones(original, plano, separadores)
    return [completo] if completo else None


def _resolver(candidatos, hechos, siempre_ambiguo_si_varios=False):
    """Elige la división cuya clave es la COMPLETA antes de escribir.
    ('ok', (clave, valor)) o ('ambiguo', [claves posibles]).
    - Una sola división: sin duda.
    - Varias: la lectura natural es la primera, salvo que otra división
      nombre un hecho ya guardado (p. ej. "viaje" y "viaje a Roma") -> aclarar.
    - Con separadores que también aparecen dentro de claves ('a', 'por', 'to')
      varias divisiones son siempre ambiguas."""
    if len(candidatos) == 1:
        return "ok", candidatos[0]
    existentes = [c for c in candidatos if normalizar_clave(c[0]) in hechos]
    if siempre_ambiguo_si_varios and len(existentes) == 1 and existentes[0] is max(candidatos, key=lambda c: len(c[0])):
        # La única clave guardada es la más larga posible ("viaje a Roma"): usarla nunca
        # recorta una clave compuesta; si la guardada fuera la corta se pregunta.
        return "ok", existentes[0]
    if not siempre_ambiguo_si_varios and (not existentes or existentes == [candidatos[0]]):
        return "ok", candidatos[0]
    return "ambiguo", [clave_sin_articulo(c[0]) for c in candidatos]


def _problema_en_carga(idioma, original, plano):
    """Motivo (mensaje) para NO mutar la memoria con este texto, o None.
    Se comprueba sobre todo el contenido de la petición antes de resolver nada."""
    if _entre_comillas(original) or _P_CITA.search(original.replace("’", "'")):
        return _msg(idioma, "aclarar_citado")
    if _P_EJEMPLO.search(plano):
        return _msg(idioma, "aclarar_ejemplo")
    if _P_VARIOS_VALORES.search(plano):
        return _msg(idioma, "aclarar_varios")
    if _P_CONTRADICCION.search(plano):
        return _msg(idioma, "contradictorio")
    if _P_NEGACION_HECHO.search(plano):
        return _msg(idioma, "aclarar_negado")
    return None


def _recorte(original, plano, m, grupo):
    """(texto_original, texto_plano) del grupo `grupo` del match `m`."""
    if m.group(grupo) is None:
        return None, None
    ini, fin = m.span(grupo)
    return original[ini:fin], plano[ini:fin]


# --------------------------------------------------------------------------- operaciones protegidas
def _con_almacen(idioma, operacion):
    """Ejecuta una operación sobre el almacén informando con honestidad:
    fichero dañado/ilegible -> no se toca; fallo de escritura -> no se confirma nada."""
    try:
        return operacion()
    except MemoriaHechosInvalida as e:
        return _msg(idioma, "danada", ruta=memory_engine.FACTS_PATH, error=e)
    except ErrorLecturaMemoria as e:
        return _msg(idioma, "ilegible", ruta=memory_engine.FACTS_PATH, error=e)
    except OSError as e:
        return _msg(idioma, "no_guardado", error=e)


def _formatear_resultado(idioma, estado, clave, valor, anterior):
    if estado in ("guardado", "creado"):
        return _msg(idioma, estado, clave=clave, valor=valor)
    if estado == "duplicado":
        return _msg(idioma, "duplicado", clave=clave, valor=anterior)
    if estado == "conflicto":
        return _msg(idioma, "conflicto", clave=clave, anterior=anterior, valor=valor)
    return _msg(idioma, "actualizado", clave=clave, valor=valor, anterior=anterior)


def _escribir_hechos(idioma, hechos_candidatos, modo, separadores_ambiguos=False):
    """Resuelve la clave completa de cada hecho contra lo guardado y escribe
    TODOS en una única operación atómica. Si algo es ambiguo o contradictorio
    no se escribe nada. Debe ejecutarse dentro de _con_almacen."""
    hechos = memory_engine.cargar_hechos()
    elegidos = []
    for candidatos in hechos_candidatos:
        estado, dato = _resolver(candidatos, hechos, separadores_ambiguos)
        if estado == "ambiguo":
            return _msg(idioma, "aclarar_clave", opciones=", ".join(f"'{c}'" for c in dato))
        elegidos.append(dato)
    vistos, unicos = {}, []
    for clave, valor in elegidos:
        norma = normalizar_clave(clave)
        if norma in vistos:
            if vistos[norma] != limpiar_valor(valor).strip().lower():
                return _msg(idioma, "contradictorio")      # la misma clave con dos valores
            continue
        vistos[norma] = limpiar_valor(valor).strip().lower()
        unicos.append((clave, valor))
    resultados = memory_engine.aplicar_cambios([(modo, c, v) for c, v in unicos])
    return "\n".join(_formatear_resultado(idioma, *r) for r in resultados)


def _hacer_olvidar(idioma, clave):
    visible = clave_sin_articulo(clave)
    valor = memory_engine.olvidar_hecho(clave)
    if valor is not None:
        return _msg(idioma, "olvidado", clave=visible, valor=valor)
    parecidos = memory_engine.buscar_hechos(clave)
    if parecidos:
        lista = ", ".join(f"'{c}'" for c, _ in parecidos)
        return _msg(idioma, "sugerencias", clave=visible, lista=lista)
    return _msg(idioma, "no_existia", clave=visible)


def _hacer_listar(idioma):
    hechos = memory_engine.listar_hechos()
    if not hechos:
        return _msg(idioma, "lista_vacia")
    lineas = [_msg(idioma, "lista_cabecera", n=len(hechos))]
    lineas.extend(f"- {clave}: {valor}" for clave, valor in hechos)
    return "\n".join(lineas)


def _sugerir(idioma, clave, codigo_si_nada):
    """Coincidencias parciales: sólo como sugerencia (sin valores), nunca como hecho confirmado."""
    parecidos = memory_engine.buscar_hechos(clave)
    visible = clave_sin_articulo(clave)
    if parecidos:
        lista = ", ".join(f"'{c}'" for c, _ in parecidos)
        return _msg(idioma, "sugerencias_consulta", clave=visible, lista=lista)
    return _msg(idioma, codigo_si_nada, clave=visible)


def _hacer_consultar(idioma, clave):
    resultado = memory_engine.obtener_hecho(clave)
    if resultado is not None:
        return _msg(idioma, "recuperado", clave=resultado[0], valor=resultado[1])
    return _sugerir(idioma, clave, "no_se")


def _hacer_comparar(idioma, clave, valor):
    """'¿recuerdas que X es Y?' -> confirma, desmiente o dice que no lo sabe. Nunca guarda."""
    resultado = memory_engine.obtener_hecho(clave)
    if resultado is None:
        return _sugerir(idioma, clave, "no_se")
    guardado = resultado[1]
    if guardado.strip().lower() == limpiar_valor(valor).strip().lower():
        return _msg(idioma, "confirmado", clave=resultado[0], valor=guardado)
    return _msg(idioma, "desmentido", clave=resultado[0], anterior=guardado)


# --------------------------------------------------------------------------- intentos por operación
def _intentar_recuperar(original, plano):
    for patron in _P_RECUPERAR[5:]:            # listados: "muestra tu memoria", "¿qué sabes de mí?"...
        m = patron.match(plano)
        if m:
            idioma = _idioma(m.group("verbo"))
            return _con_almacen(idioma, lambda: _hacer_listar(idioma))
    for patron in _P_RECUPERAR[:2]:
        m = patron.match(plano)
        if m:
            idioma = _idioma(m.group("verbo"))
            clave, _ = _recorte(original, plano, m, "clave")
            if clave is None or not normalizar_clave(clave):
                return _con_almacen(idioma, lambda: _hacer_listar(idioma))
            return _con_almacen(idioma, lambda: _hacer_consultar(idioma, clave))

    m = _P_RECUPERAR[2].match(plano)
    if m:
        idioma = _idioma(m.group("verbo"))
        resto, resto_plano = _recorte(original, plano, m, "resto")
        # ¿recuerdas cuál es mi X?
        interno = re.match(r"^(?:cual\s+es|cuales\s+son|what\s+is|what's|what\s+are)\s+(.+)$", resto_plano, re.S)
        if interno:
            resto = resto[interno.start(1):interno.end(1)]
            return _con_almacen(idioma, lambda: _hacer_consultar(idioma, resto))
        pareja = _parse_hecho(resto, resto_plano)
        if pareja is not None and not _P_NEGACION_HECHO.search(resto_plano):
            return _con_almacen(idioma, lambda: _hacer_comparar(idioma, pareja[0], pareja[1]))
        if not normalizar_clave(resto):
            return _con_almacen(idioma, lambda: _hacer_listar(idioma))
        return _con_almacen(idioma, lambda: _hacer_consultar(idioma, resto))

    m = _P_RECUPERAR[3].match(plano)
    if m:
        idioma = _idioma(m.group("verbo"))
        clave, _ = _recorte(original, plano, m, "clave")
        return _con_almacen(idioma, lambda: _hacer_consultar(idioma, clave))

    m = _P_RECUPERAR[4].match(plano)
    if m:
        idioma = _idioma(m.group("verbo"))
        return _con_almacen(idioma, lambda: _hacer_listar(idioma))
    return None


def _intentar_negado(original, plano):
    """'no recuerdes que X es Y' / 'don't save my password': respuesta local, sin escribir."""
    m = _P_NEGADO.match(plano)
    if not m:
        return None
    idioma = _idioma(m.group("verbo"))
    hecho, hecho_plano = _recorte(original, plano, m, "hecho")
    if hecho and _P_CONTRADICCION.search(hecho_plano):
        return _msg(idioma, "contradictorio")
    pareja = _parse_hecho(hecho, hecho_plano) if hecho else None
    clave = pareja[0] if pareja else (hecho if hecho and normalizar_clave(hecho) else None)

    def responder():
        if clave:
            existente = memory_engine.obtener_hecho(clave)
            if existente is not None:
                return _msg(idioma, "no_guardare_existe", clave=existente[0], valor=existente[1])
        return _msg(idioma, "no_guardare")
    return _con_almacen(idioma, responder)


def _pedir_confirmacion_total(idioma):
    def pedir():
        cuantos = len(memory_engine.listar_hechos())
        if cuantos == 0:
            return _msg(idioma, "nada_que_olvidar")
        return _msg(idioma, "pedir_confirmacion", n=cuantos)
    return _con_almacen(idioma, pedir)


def _intentar_olvidar(original, plano):
    total = _P_BORRAR_MEMORIA.match(plano)
    if total:
        return _pedir_confirmacion_total(_idioma(total.group("verbo")))
    m = None
    for patron in _P_OLVIDAR:
        m = patron.match(plano)
        if m:
            break
    if not m:
        return None
    idioma = _idioma(m.group("verbo"))
    resto, resto_plano = _recorte(original, plano, m, "resto")
    prefijo = _P_PREFIJO_OLVIDO.match(resto_plano)
    if prefijo:
        resto, resto_plano = resto[prefijo.end():], resto_plano[prefijo.end():]
    resto_compacto = " ".join(resto_plano.split()).strip(" ¿?¡!.").strip()
    sobre_el_usuario = prefijo or re.search(r"lo\s+que\s+(?:sabes|recuerdas)|what\s+you\s+(?:know|remember)",
                                            plano[:m.start("resto")])
    if sobre_el_usuario and resto_compacto in _SOBRE_MI:   # "olvida lo que sabes de mí" = todo (con confirmación)
        return _pedir_confirmacion_total(idioma)

    if _P_CONFIRMA_TODO.match(resto_compacto):
        def borrar_todo():
            cuantos = memory_engine.olvidar_todos()
            if cuantos == 0:
                return _msg(idioma, "nada_que_olvidar")
            return _msg(idioma, "todo_olvidado", n=cuantos)
        return _con_almacen(idioma, borrar_todo)

    if resto_compacto in _TOTALES:
        return _pedir_confirmacion_total(idioma)

    if resto_compacto in _PRONOMBRES:
        return _msg(idioma, "aclarar_olvidar")
    problema = _problema_en_carga(idioma, resto, resto_plano)
    if problema:
        return problema

    candidatos = _divisiones(resto, resto_plano, _SEP_HECHO)
    if candidatos:
        def olvidar_comprobando():
            # Sólo se borra la clave COMPLETA y sólo si el valor coincide.
            estado, dato = _resolver(candidatos, memory_engine.cargar_hechos())
            if estado == "ambiguo":
                return _msg(idioma, "aclarar_clave", opciones=", ".join(f"'{c}'" for c in dato))
            clave, valor = dato
            visible = clave_sin_articulo(clave)
            resultado = memory_engine.obtener_hecho(clave)
            if resultado is None:
                return _msg(idioma, "no_existia", clave=visible)
            if resultado[1].strip().lower() != limpiar_valor(valor).strip().lower():
                return _msg(idioma, "olvidar_conflicto", clave=visible,
                            anterior=resultado[1], valor=limpiar_valor(valor))
            memory_engine.olvidar_hecho(clave)
            return _msg(idioma, "olvidado", clave=visible, valor=resultado[1])
        return _con_almacen(idioma, olvidar_comprobando)

    return _con_almacen(idioma, lambda: _hacer_olvidar(idioma, resto))


def _intentar_actualizar(original, plano):
    m = _P_ACTUALIZAR.match(plano)
    if not m:
        return None
    idioma = _idioma(m.group("verbo"))
    resto, resto_plano = _recorte(original, plano, m, "resto")
    problema = _problema_en_carga(idioma, resto, resto_plano)
    if problema:
        return problema
    if m.group("marca").strip():
        # "corrige tu memoria: X es Y" / "actualiza tu memoria que X es Y": uno o varios hechos
        hechos = _parse_hechos(resto, resto_plano)
        if hechos is None:
            return _msg(idioma, "aclarar_actualizar")
        return _con_almacen(idioma, lambda: _escribir_hechos(idioma, hechos, "actualizar"))
    # "actualiza en tu memoria X a Y" / "X: Y": 'a/por/to' también aparece dentro de claves,
    # así que varias divisiones posibles siempre se aclaran (la forma 'X: Y' es inequívoca).
    candidatos = _divisiones(resto, resto_plano, _SEP_A)
    if not candidatos:
        return _msg(idioma, "aclarar_actualizar")
    return _con_almacen(idioma, lambda: _escribir_hechos(idioma, [candidatos], "actualizar",
                                                          separadores_ambiguos=True))


def _intentar_recordar(original, plano):
    for patron in _P_RECORDAR:
        m = patron.match(plano)
        if not m:
            continue
        idioma = _idioma(m.group("verbo"))
        hecho, hecho_plano = _recorte(original, plano, m, "hecho")
        # "recuerda que ahora X es Y" es una actualización explícita (se permite reemplazar)
        ahora = _P_AHORA.match(hecho_plano)
        actualizar = ahora is not None
        if actualizar:
            hecho = hecho[ahora.start(1):ahora.end(1)]
            hecho_plano = hecho_plano[ahora.start(1):ahora.end(1)]
        actualizar = actualizar or _marca_ahora(hecho_plano)   # "mi coche ahora es azul", "my car is now blue"
        problema = _problema_en_carga(idioma, hecho, hecho_plano)
        if problema:
            return problema
        hechos = _parse_hechos(hecho, hecho_plano)
        if hechos is None:
            return _msg(idioma, "aclarar_hecho")
        modo = "actualizar" if actualizar else "recordar"
        return _con_almacen(idioma, lambda: _escribir_hechos(idioma, hechos, modo))
    return None


# Peticiones de memoria reconocibles pero incompletas ("recuerda", "olvídalo",
# "borra de tu memoria", "¿recuerdas?"): se aclaran LOCALMENTE, nunca van a un motor.
_COLA_VACIA = r"(?:\s+(?:que|that|de\s+que|de|about|esto|this|eso|lo|it))?\s*[:,]?"
_P_INCOMPLETO = [
    (re.compile(_INI + r"(?:" + _V_RECORDAR + r"|(?P<v2>recuerdalo|recuerdala|memorizalo|memorizala|remember\s+it)"
                r"|" + _V_GENERICO_STORE.replace("?P<verbo>", "?P<v3>") + r"\s*" + _OBJ + r")"
                + _COLA_VACIA + _FIN, re.S), "aclarar_hecho"),
    (re.compile(_INI + r"(?:" + _V_OLVIDAR + r"|(?P<v2>olvidalo|olvidala|borralo\s+de\s+tu\s+memoria)"
                r"|" + _V_GENERICO_FORGET.replace("?P<verbo>", "?P<v3>") + r"\s+" + _OBJ + r")"
                + _COLA_VACIA + _FIN, re.S), "aclarar_olvidar"),
    (re.compile(_INI + _V_ACTUALIZAR + r"\s+" + _OBJ + _COLA_VACIA + _FIN, re.S), "aclarar_actualizar"),
    (re.compile(_INI + _PREG + r"(?:no\s+)?(?P<verbo>te\s+acuerdas(?:\s+de)?|recuerdas|do\s+you\s+remember|"
                r"don'?t\s+you\s+remember|que\s+sabes\s+de|what\s+do\s+you\s+know\s+about|"
                r"cual\s+es\s+mi|what\s+is\s+my|what's\s+my)" + _FIN_PREGUNTA, re.S), "aclarar_consulta"),
]


def _intentar_incompleto(original, plano):
    for patron, codigo in _P_INCOMPLETO:
        m = patron.match(plano)
        if m:
            verbo = next((g for g in m.groups() if g), plano)
            return _msg(_idioma(verbo), codigo)
    return None


# --------------------------------------------------------------------------- entrada pública
def procesar_comando_memoria(texto):
    """
    Si `texto` es una petición explícita de memoria, la ejecuta LOCALMENTE y
    devuelve la respuesta para el usuario. Devuelve None si es un mensaje
    normal (afirmaciones, preguntas generales, citas, comandos genéricos sin
    objeto de memoria, comandos incrustados...): en ese caso no se lee ni se
    escribe nada.
    """
    if not isinstance(texto, str):
        return None
    original = texto.strip()
    if not original or _entre_comillas(original):
        return None
    plano = _plano(original)

    # Las consultas se intentan siempre (muchas son preguntas legítimas de memoria).
    respuesta = _intentar_recuperar(original, plano)
    if respuesta is not None:
        return respuesta

    # Un mensaje con forma de pregunta nunca escribe, actualiza ni olvida nada.
    if plano.startswith("¿") or plano.rstrip(" .!").endswith("?"):
        return _intentar_incompleto(original, plano) if _P_INCOMPLETO[3][0].match(plano) else None

    for intentar in (_intentar_negado, _intentar_olvidar, _intentar_actualizar, _intentar_recordar,
                     _intentar_incompleto):
        respuesta = intentar(original, plano)
        if respuesta is not None:
            return respuesta
    return None
