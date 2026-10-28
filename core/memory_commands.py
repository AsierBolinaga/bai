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
        "sugerencias": ("No tengo nada guardado exactamente como '{clave}'. Quizá te refieres a: {lista}. "
                        "Pregúntame por la clave completa."),
        "ambiguo": ("Eso puede referirse a varios hechos que tengo guardados: {lista}. "
                    "Dímelo con la clave completa para no cambiar el equivocado."),
        "ambiguo_division": ("No sé dónde acaba la clave y empieza el valor ({lista}). "
                             "Dímelo como 'recuerda que ahora <clave> es <valor>' o '<clave>: <valor>'."),
        "contradictorio": ("La petición se contradice (guardar y olvidar a la vez, o dos valores para la misma "
                           "clave). No he cambiado nada: dímelo en peticiones separadas."),
        "incompleto": "Te he entendido a medias: ¿qué debo {accion}? Dímelo como '{ejemplo}'.",
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
        "no_guardado": ("No he podido guardar el cambio ({error}). "
                        "La memoria anterior queda intacta y la operación NO se ha realizado."),
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
        "sugerencias": ("I have nothing stored exactly as '{clave}'. Did you mean: {lista}? "
                        "Ask me with the full key."),
        "ambiguo": ("That could refer to several stored facts: {lista}. "
                    "Say the full key so I don't change the wrong one."),
        "ambiguo_division": ("I can't tell where the key ends and the value starts ({lista}). "
                             "Say it like 'remember that now <key> is <value>' or '<key>: <value>'."),
        "contradictorio": ("The request contradicts itself (store and forget at once, or two values for the same "
                           "key). Nothing changed: say it as separate requests."),
        "incompleto": "I only half understood: what should I {accion}? Say it like '{ejemplo}'.",
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
        "no_guardado": ("I couldn't save the change ({error}). "
                        "Previous memory is intact and the operation was NOT performed."),
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

# Objeto de memoria explícito que convierte un verbo genérico en una petición de memoria.
_OBJ_MEMORIA = (r"(?:(?:en|a|de)\s+)?(?:tu\s+|la\s+|mi\s+|your\s+|the\s+)?(?:memoria|memory)"
                r"|(?:como|este|ese|el|un)\s+(?:hecho|dato)|(?:as|this|that|the)\s+(?:a\s+)?fact"
                r"|(?:in|to|into|from)\s+(?:your\s+)?memory|(?:lo\s+que|what\s+you)\s+(?:recuerdas|remember)")
_OBJ = r"(?:" + _OBJ_MEMORIA + r")"

# 1) Verbos con intención de memoria inequívoca: admiten el hecho directamente.
_V_RECORDAR = (r"(?P<verbo>recuerda|acuerdate\s+de|no\s+olvides|no\s+te\s+olvides\s+de|memoriza|"
               r"aprende|aprendete|ten\s+en\s+cuenta|quiero\s+que\s+recuerdes|necesito\s+que\s+recuerdes|"
               r"remember|don'?t\s+forget|do\s+not\s+forget|keep\s+in\s+mind|bear\s+in\s+mind|"
               r"memorize|memorise|learn)")
# 2) Verbos genéricos: sólo con objeto de memoria explícito.
_V_GENERICO_STORE = (r"(?P<verbo>guarda|guardate|graba|almacena|anota|anotame|apunta|apuntame|"
                     r"toma\s+nota|registra|save|store|note|note\s+down|write\s+down|make\s+a\s+note|"
                     r"record|jot\s+down|keep)")

_P_RECORDAR = [
    re.compile(_INI + _V_RECORDAR + r"(?:\s+" + _OBJ + r")?" + r"(?:\s+(?:que|that|esto|this|de\s+que))?"
               r"\s*:?\s+(?P<hecho>.+?)" + _FIN, re.S),
    re.compile(_INI + _V_GENERICO_STORE + r"(?:\s+(?:esto|this|lo\s+siguiente|the\s+following))?\s*[:,]?\s*"
               r"(?:\s*" + _OBJ + r")" + r"(?:\s+(?:que|that|de\s+que|esto|this))?\s*:?\s+(?P<hecho>.+?)" + _FIN, re.S),
]

# Negación explícita de una petición de memoria: se contesta localmente y no se escribe nada.
_P_NEGADO = re.compile(
    _INI + r"(?P<verbo>(?:no|nunca|jamas|no\s+quiero\s+que|no\s+hace\s+falta\s+que|"
    r"don'?t|do\s+not|never|i\s+don'?t\s+want\s+you\s+to|you\s+don'?t\s+need\s+to|please\s+don'?t)\s+"
    r"(?:recuerdes|guardes|memorices|apuntes|anotes|aprendas|grabes|almacenes|registres|te\s+acuerdes\s+de|"
    r"remember|save|store|learn|memorize|memorise|note|record|keep))" + _QUE + r"\s*:?\s*(?P<hecho>.*)$", re.S)

# Actualización explícita: "recuerda que ahora X es Y" (en _P_RECORDAR) o verbo genérico + objeto de memoria.
_V_ACTUALIZAR = r"(?P<verbo>actualiza|cambia|corrige|modifica|rectifica|update|change|set|correct|fix)"
_P_ACTUALIZAR = re.compile(_INI + _V_ACTUALIZAR + r"\s+" + _OBJ + r"(?:\s+(?:de|about|que|that))?\s*[:,]?\s+(?P<resto>.+?)" + _FIN, re.S)

# Olvidar: verbos inequívocos (objeto opcional) o genéricos con objeto de memoria.
_V_OLVIDAR = (r"(?P<verbo>olvidate\s+de|olvidate|olvida|ya\s+no\s+recuerdes|deja\s+de\s+recordar|"
              r"forget\s+about|forget|stop\s+remembering)")
_V_GENERICO_FORGET = r"(?P<verbo>borra|elimina|quita|descarta|delete|remove|erase|drop|clear)"
_P_OLVIDAR = [
    re.compile(_INI + _V_OLVIDAR + r"(?:\s+" + _OBJ + r"(?:\s+de|\s+about)?)?" + _QUE + r"\s*:?\s+(?P<resto>.+?)" + _FIN, re.S),
    # borra de tu memoria X / elimina el hecho X / delete the fact X / remove X from your memory
    re.compile(_INI + _V_GENERICO_FORGET + r"\s+" + _OBJ + r"(?:\s+de|\s+about)?" + _QUE + r"\s*:?\s+(?P<resto>.+?)" + _FIN, re.S),
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
    # ¿qué recuerdas (de X)? / what do you remember (about X)? / dime qué recuerdas...
    re.compile(_INI + _PREG + r"(?:dime|tell\s+me)?\s*(?P<verbo>que\s+recuerdas|lo\s+que\s+recuerdas|"
               r"what\s+do\s+you\s+remember|what\s+you\s+remember)"
               r"(?:\s+(?:de|sobre|about)\s+(?P<clave>.+?))?" + _FIN_PREGUNTA, re.S),
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
]

# Petición reconocible pero incompleta ("recuerda", "olvida", "remember that", "actualiza en tu memoria"):
# se contesta localmente con una aclaración; nunca llega a un motor.
_P_INCOMPLETO = [
    (re.compile(_INI + _V_RECORDAR + r"(?:\s+" + _OBJ + r")?(?:\s+(?:que|that|esto|this|de\s+que))?\s*:?" + _FIN, re.S),
     "recordar"),
    (re.compile(_INI + _V_GENERICO_STORE + r"(?:\s+(?:esto|this))?\s*[:,]?\s*" + _OBJ + r"(?:\s+(?:que|that|de\s+que))?\s*:?" + _FIN, re.S),
     "recordar"),
    (re.compile(_INI + _V_ACTUALIZAR + r"\s+" + _OBJ + r"(?:\s+(?:que|that|de|about))?\s*[:,]?" + _FIN, re.S), "actualizar"),
    (re.compile(_INI + _V_OLVIDAR + r"(?:\s+" + _OBJ + r")?(?:\s+(?:que|that|de|about))?\s*:?" + _FIN, re.S), "olvidar"),
    (re.compile(_INI + _V_GENERICO_FORGET + r"\s+" + _OBJ + r"(?:\s+(?:que|that|de|about))?\s*:?" + _FIN, re.S), "olvidar"),
]
_EJEMPLOS = {
    "es": {"recordar": ("recordar", "recuerda que <clave> es <valor>"),
           "actualizar": ("actualizar", "recuerda que ahora <clave> es <valor>"),
           "olvidar": ("olvidar", "olvida <clave>")},
    "en": {"recordar": ("remember", "remember that <key> is <value>"),
           "actualizar": ("update", "remember that now <key> is <value>"),
           "olvidar": ("forget", "forget <key>")},
}
# Instrucciones contradictorias dentro de una misma petición (guardar y olvidar/no guardar a la vez).
_P_CONTRADICCION = re.compile(
    r"\b(?:olvida(?:lo|te)?|no\s+(?:lo\s+)?(?:guardes|recuerdes|memorices|apuntes|anotes)|borra(?:lo)?|elimina(?:lo)?|"
    r"forget(?:\s+it)?|don'?t\s+(?:save|store|remember|keep)(?:\s+it)?|do\s+not\s+(?:save|store|remember)|"
    r"delete\s+it|remove\s+it|erase\s+it)\b")
_P_CONTRADICCION_OLVIDO = re.compile(
    r"\b(?:recuerda|memoriza|guarda|aprende|remember|memorize|save|store|keep)\b")

_P_PAREJA = [  # clave <sep> valor, dentro del hecho
    r"^(?P<clave>.+?)\s+se\s+llaman?\s+(?P<valor>.+)$",
    r"^(?P<clave>.+?)'s\s+name\s+is\s+(?P<valor>.+)$",
    r"^(?P<clave>.+?)\s+(?:es|son)\s+(?P<valor>.+)$",
    r"^(?P<clave>.+?)\s+(?:is|are)\s+(?P<valor>.+)$",
    r"^(?P<clave>[^:=]+?)\s*[:=]\s*(?P<valor>.+)$",
]
# Un hecho negado nunca se guarda tal cual ("mi coche no es rojo" no define ningún valor).
_P_NEGACION_HECHO = re.compile(
    r"^(?:no|nunca|jamas|not|never|ya\s+no)\b"
    r"|\b(?:no|nunca|jamas|tampoco)\s+(?:es|son|era|eran|se\s+llaman?|vale|tengo|tiene)\b"
    r"|\b(?:ya\s+no)\b|\bno\s+longer\b|\bnot\s+anymore\b"
    r"|\b(?:is|are|was|were)\s*(?:n't|not)\b|\b(?:isn't|aren't|wasn't|weren't)\b", re.S)
_P_AHORA = re.compile(r"^(?:ahora|a\s+partir\s+de\s+ahora|desde\s+ahora|now|from\s+now\s+on)[,]?\s+(.+)$", re.S)
_P_SEPARADOR_HECHOS = re.compile(r"\s*(?:;|,\s+y\s+|\s+y\s+|,\s+and\s+|\s+and\s+)\s*", re.S)


_SEPARADORES_PAREJA = [r"\s+se\s+llaman?\s+", r"'s\s+name\s+is\s+", r"\s+(?:es|son)\s+", r"\s+(?:is|are)\s+", r"\s*[:=]\s*"]
_SEPARADORES_A = [r"\s+(?:a|por|to)\s+"]


class ClaveAmbigua(Exception):
    """Varias claves encajan con la petición: hay que preguntar. `guardadas`
    indica si son hechos existentes (o sólo divisiones posibles del texto)."""

    def __init__(self, claves, guardadas=True):
        super().__init__(", ".join(claves))
        self.claves = claves
        self.guardadas = guardadas


def _candidatos(original, plano, separadores):
    """Todas las divisiones posibles clave/valor, en orden de preferencia
    (separador más específico primero; dentro de cada uno, de izquierda a derecha)."""
    vistos = set()
    resultado = []
    for sep in separadores:
        for m in re.finditer(sep, plano):
            clave, valor = original[:m.start()], original[m.end():]
            if normalizar_clave(clave) and limpiar_valor(valor) and normalizar_clave(clave) not in vistos:
                vistos.add(normalizar_clave(clave))
                resultado.append((clave, valor))
    return resultado


def _parse_hecho(original, plano):
    """Separa '<clave> es <valor>' (y variantes) SIN consultar el almacén:
    la división más a la izquierda. Devuelve (clave, valor) o None."""
    c = _candidatos(original, plano, _SEPARADORES_PAREJA)
    return c[0] if c else None


def _resolver_pareja(original, plano, separadores, exigir_unica=False):
    """Elige la división clave/valor resolviendo la clave COMPLETA contra el
    almacén: si exactamente una división coincide con un hecho guardado, es
    ésa ("viaje a Roma" frente a "viaje"); si varias coinciden -> ClaveAmbigua;
    si ninguna: la primera (o ClaveAmbigua si `exigir_unica` y hay varias).
    Devuelve None si no hay ninguna pareja clara. Lee el almacén (puede lanzar)."""
    pareja, _ = _resolver(original, plano, separadores, exigir_unica)
    return pareja


def _resolver(original, plano, separadores, exigir_unica=False):
    """Como _resolver_pareja, devolviendo además si la decidió el almacén."""
    candidatos = _candidatos(original, plano, separadores)
    if not candidatos:
        return None, False
    existentes = memory_engine.claves_existentes([c for c, _ in candidatos])
    if len(existentes) == 1:
        return next(p for p in candidatos if p[0] == existentes[0]), True
    if len(existentes) > 1:
        raise ClaveAmbigua([clave_sin_articulo(c) for c in existentes])
    if exigir_unica and len(candidatos) > 1:
        raise ClaveAmbigua([clave_sin_articulo(c) for c, _ in candidatos], guardadas=False)
    return candidatos[0], False


def _parse_hechos(original, plano):
    """Uno o varios hechos ("X es A y Y es B"), resolviendo cada clave contra
    el almacén. Sólo se divide cuando TODAS las partes son parejas claras; si
    no, se interpreta como un único hecho. Lee el almacén (puede lanzar)."""
    partes = []
    pos = 0
    for m in _P_SEPARADOR_HECHOS.finditer(plano):
        partes.append((pos, m.start()))
        pos = m.end()
    partes.append((pos, len(plano)))
    if len(partes) > 1:
        parejas = [_resolver_pareja(original[a:b], plano[a:b], _SEPARADORES_PAREJA) for a, b in partes]
        if all(p is not None for p in parejas):
            return parejas
    pareja = _resolver_pareja(original, plano, _SEPARADORES_PAREJA)
    return [pareja] if pareja is not None else None


def _claves_repetidas(parejas):
    """True si la misma clave aparece con valores distintos (petición contradictoria)."""
    valores = {}
    for clave, valor in parejas:
        norma = normalizar_clave(clave_sin_articulo(clave))
        v = limpiar_valor(valor).strip().lower()
        if valores.setdefault(norma, v) != v:
            return True
    return False


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
    except ClaveAmbigua as e:
        return _msg(idioma, "ambiguo" if e.guardadas else "ambiguo_division",
                    lista=", ".join(f"'{c}'" for c in e.claves))


def _hacer_recordar(idioma, clave, valor):
    estado, anterior = memory_engine.recordar_hecho(clave, valor)
    visible = clave_sin_articulo(clave)
    if estado == "guardado":
        return _msg(idioma, "guardado", clave=visible, valor=limpiar_valor(valor))
    if estado == "duplicado":
        return _msg(idioma, "duplicado", clave=visible, valor=anterior)
    return _msg(idioma, "conflicto", clave=visible, anterior=anterior, valor=limpiar_valor(valor))


def _hacer_actualizar(idioma, clave, valor):
    estado, anterior = memory_engine.actualizar_hecho(clave, valor)
    visible = clave_sin_articulo(clave)
    if estado == "creado":
        return _msg(idioma, "creado", clave=visible, valor=limpiar_valor(valor))
    return _msg(idioma, "actualizado", clave=visible, valor=limpiar_valor(valor), anterior=anterior)


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


def _hacer_consultar(idioma, clave):
    visible = clave_sin_articulo(clave)
    resultado = memory_engine.obtener_hecho(clave)
    if resultado is not None:
        return _msg(idioma, "recuperado", clave=resultado[0], valor=resultado[1])
    parecidos = memory_engine.buscar_hechos(clave)
    if parecidos:   # coincidencias parciales: sólo sugerencias, nunca un hecho confirmado
        lista = ", ".join(f"'{c}'" for c, _ in parecidos)
        return _msg(idioma, "sugerencias", clave=visible, lista=lista)
    return _msg(idioma, "no_se", clave=visible)


def _hacer_comparar(idioma, clave, valor):
    """'¿recuerdas que X es Y?' -> confirma, desmiente o dice que no lo sabe. Nunca guarda."""
    visible = clave_sin_articulo(clave)
    resultado = memory_engine.obtener_hecho(clave)
    if resultado is None:
        return _msg(idioma, "no_se", clave=visible)
    guardado = resultado[1]
    if guardado.strip().lower() == limpiar_valor(valor).strip().lower():
        return _msg(idioma, "confirmado", clave=resultado[0], valor=guardado)
    return _msg(idioma, "desmentido", clave=resultado[0], anterior=guardado)


def _hacer_recordar_varios(idioma, parejas, actualizar):
    """Varios hechos en una petición con UNA escritura atómica: o se persisten
    todos los que procede escribir o ninguno (y entonces no se confirma nada).
    Los conflictos no se escriben y se informan uno a uno."""
    respuestas = []
    for visible, estado, valor, anterior in memory_engine.aplicar_hechos(parejas, reemplazar=actualizar):
        if estado == "guardado":
            respuestas.append(_msg(idioma, "guardado", clave=visible, valor=valor))
        elif estado == "creado":
            respuestas.append(_msg(idioma, "creado", clave=visible, valor=valor))
        elif estado == "actualizado":
            respuestas.append(_msg(idioma, "actualizado", clave=visible, valor=valor, anterior=anterior))
        elif estado == "duplicado":
            respuestas.append(_msg(idioma, "duplicado", clave=visible, valor=valor))
        else:
            respuestas.append(_msg(idioma, "conflicto", clave=visible, anterior=anterior, valor=valor))
    return "\n".join(respuestas)


# --------------------------------------------------------------------------- intentos por operación
def _intentar_recuperar(original, plano):
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
        if not normalizar_clave(resto):
            return _con_almacen(idioma, lambda: _hacer_listar(idioma))

        def consultar():
            pareja = None if _P_NEGACION_HECHO.search(resto_plano) else _resolver_pareja(resto, resto_plano, _SEPARADORES_PAREJA)
            if pareja is not None:
                return _hacer_comparar(idioma, pareja[0], pareja[1])
            return _hacer_consultar(idioma, resto)
        return _con_almacen(idioma, consultar)

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
    pareja = _parse_hecho(hecho, hecho_plano) if hecho else None
    clave = pareja[0] if pareja else (hecho if hecho and normalizar_clave(hecho) else None)

    def responder():
        if clave:
            existente = memory_engine.obtener_hecho(clave)
            if existente is not None:
                return _msg(idioma, "no_guardare_existe", clave=existente[0], valor=existente[1])
        return _msg(idioma, "no_guardare")
    return _con_almacen(idioma, responder)


def _intentar_olvidar(original, plano):
    m = None
    for patron in _P_OLVIDAR:
        m = patron.match(plano)
        if m:
            break
    if not m:
        return None
    idioma = _idioma(m.group("verbo"))
    resto, resto_plano = _recorte(original, plano, m, "resto")
    resto_compacto = " ".join(resto_plano.split()).strip(" ¿?¡!.").strip()

    if _P_CONFIRMA_TODO.match(resto_compacto):
        def borrar_todo():
            cuantos = memory_engine.olvidar_todos()
            if cuantos == 0:
                return _msg(idioma, "nada_que_olvidar")
            return _msg(idioma, "todo_olvidado", n=cuantos)
        return _con_almacen(idioma, borrar_todo)

    if resto_compacto in _TOTALES:
        def pedir_confirmacion():
            cuantos = len(memory_engine.listar_hechos())
            if cuantos == 0:
                return _msg(idioma, "nada_que_olvidar")
            return _msg(idioma, "pedir_confirmacion", n=cuantos)
        return _con_almacen(idioma, pedir_confirmacion)

    if resto_compacto in _PRONOMBRES:
        return _msg(idioma, "aclarar_olvidar")
    if _entre_comillas(resto):
        return _msg(idioma, "aclarar_citado")
    if _P_CONTRADICCION_OLVIDO.search(resto_plano):
        return _msg(idioma, "contradictorio")
    if _P_NEGACION_HECHO.search(resto_plano):
        return _msg(idioma, "aclarar_negado")

    def olvidar():
        pareja = _resolver_pareja(resto, resto_plano, _SEPARADORES_PAREJA)
        if pareja is None:
            return _hacer_olvidar(idioma, resto)          # sólo coincidencia EXACTA; si no, sugerencias
        clave, valor = pareja
        visible = clave_sin_articulo(clave)
        resultado = memory_engine.obtener_hecho(clave)
        if resultado is None:
            return _msg(idioma, "no_existia", clave=visible)
        if resultado[1].strip().lower() != limpiar_valor(valor).strip().lower():
            return _msg(idioma, "olvidar_conflicto", clave=visible, anterior=resultado[1], valor=limpiar_valor(valor))
        memory_engine.olvidar_hecho(clave)
        return _msg(idioma, "olvidado", clave=visible, valor=resultado[1])
    return _con_almacen(idioma, olvidar)


def _intentar_actualizar(original, plano):
    m = _P_ACTUALIZAR.match(plano)
    if not m:
        return None
    idioma = _idioma(m.group("verbo"))
    resto, resto_plano = _recorte(original, plano, m, "resto")
    if _entre_comillas(resto):
        return _msg(idioma, "aclarar_citado")
    if _P_CONTRADICCION.search(resto_plano):
        return _msg(idioma, "contradictorio")
    if _P_NEGACION_HECHO.search(resto_plano):
        return _msg(idioma, "aclarar_negado")

    def actualizar():
        # 1) '<clave> es/: <valor>' decidido por el almacén (separador explícito y clave completa existente)
        pareja, por_almacen = _resolver(resto, resto_plano, _SEPARADORES_PAREJA)
        if pareja is not None and por_almacen:
            return _hacer_recordar_varios(idioma, [pareja], actualizar=True)
        # 2) '<clave> a/por/to <valor>': la clave completa se resuelve contra el almacén; si nada
        #    encaja, manda el separador explícito (es/:) y, si no lo hay y caben varias
        #    divisiones, se pregunta en lugar de adivinar.
        pareja_a, por_almacen_a = _resolver(resto, resto_plano, _SEPARADORES_A, exigir_unica=pareja is None)
        if pareja_a is not None and (por_almacen_a or pareja is None):
            pareja = pareja_a
        if pareja is None:
            return _msg(idioma, "aclarar_actualizar")
        if _entre_comillas(pareja[0]) or _entre_comillas(pareja[1]):
            return _msg(idioma, "aclarar_citado")
        return _hacer_recordar_varios(idioma, [pareja], actualizar=True)
    return _con_almacen(idioma, actualizar)


def _intentar_recordar(original, plano):
    for patron in _P_RECORDAR:
        m = patron.match(plano)
        if not m:
            continue
        idioma = _idioma(m.group("verbo"))
        hecho, hecho_plano = _recorte(original, plano, m, "hecho")
        if _entre_comillas(hecho):
            # 'recuerda que "X es Y"': un ejemplo citado -> aclarar, nunca guardar a ciegas.
            return _msg(idioma, "aclarar_citado")
        # "recuerda que ahora X es Y" es una actualización explícita (se permite reemplazar)
        ahora = _P_AHORA.match(hecho_plano)
        actualizar = ahora is not None
        if actualizar:
            hecho = hecho[ahora.start(1):ahora.end(1)]
            hecho_plano = hecho_plano[ahora.start(1):ahora.end(1)]
        if _P_CONTRADICCION.search(hecho_plano):
            return _msg(idioma, "contradictorio")
        if _P_NEGACION_HECHO.search(hecho_plano):
            return _msg(idioma, "aclarar_negado")

        def recordar():
            parejas = _parse_hechos(hecho, hecho_plano)
            if parejas is None:
                return _msg(idioma, "aclarar_hecho")
            if _claves_repetidas(parejas):
                return _msg(idioma, "contradictorio")
            return _hacer_recordar_varios(idioma, parejas, actualizar)
        return _con_almacen(idioma, recordar)
    return None


def _intentar_incompleto(original, plano):
    """Petición de memoria reconocible pero sin el dato: aclaración local."""
    for patron, accion in _P_INCOMPLETO:
        m = patron.match(plano)
        if m:
            idioma = _idioma(m.group("verbo"))
            verbo, ejemplo = _EJEMPLOS[idioma][accion]
            return _msg(idioma, "incompleto", accion=verbo, ejemplo=ejemplo)
    return None


def _reconocible(texto):
    """True si `texto` tiene forma de petición de memoria (sin ejecutarla)."""
    plano = _plano(texto.strip())
    patrones = ([p for p in _P_RECUPERAR] + [_P_NEGADO] + _P_OLVIDAR + [_P_ACTUALIZAR] + _P_RECORDAR
                + [p for p, _ in _P_INCOMPLETO])
    return any(p.match(plano) for p in patrones)


def _sin_comillas(texto):
    texto = texto.strip()
    if texto.startswith("<<") and texto.endswith(">>"):
        return texto[2:-2]
    return texto[1:-1]


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
    if not original:
        return None
    if _entre_comillas(original):
        # Un ejemplo entrecomillado reconocible se rechaza localmente (nunca se ejecuta ni se envía a un motor).
        interior = _sin_comillas(original)
        if _reconocible(interior):
            return _msg(_idioma(_plano(interior)), "aclarar_citado")
        return None
    plano = _plano(original)

    # Las consultas se intentan siempre (muchas son preguntas legítimas de memoria).
    respuesta = _intentar_recuperar(original, plano)
    if respuesta is not None:
        return respuesta

    # Un mensaje con forma de pregunta nunca escribe, actualiza ni olvida nada.
    if plano.startswith("¿") or plano.rstrip(" .!").endswith("?"):
        return None

    # Las incompletas van primero: sus patrones exigen que no haya nada tras el verbo.
    for intentar in (_intentar_incompleto, _intentar_negado, _intentar_olvidar, _intentar_actualizar,
                     _intentar_recordar):
        respuesta = intentar(original, plano)
        if respuesta is not None:
            return respuesta
    return None
