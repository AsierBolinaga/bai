"""
Orquestador de B.A.I: construye el contexto (prompt de sistema + memoria +
historial) y delega la generación en el ModelSelector, que elige el motor y
modelo según el modo de trabajo (online / offline).
"""
import re

from core.ayuda import AYUDA_BAI, es_peticion_ayuda
from core.contexto import avisos_contexto
from core.cancelacion import comprobar_cancelacion
from config.personalizacion import ruta_personalizacion
from core.memory_commands import procesar_comando_memoria
from core.memory_engine import get_memory_context
from core.model_selector import AislamientoActivo, ModelSelector, SinMotorDisponible, hay_conexion  # noqa: F401

SYSTEM_PROMPT_PATH = ruta_personalizacion("system_prompt.txt")

# Comandos de control del modo de trabajo.
#
# Sintaxis aceptada (el mensaje COMPLETO debe ser el comando; mayúsculas indiferentes):
#   Español : [B.A.I,] [por favor,] pasa|pasar|cambia|cambiar a[l] modo online|offline [por favor] [.!]
#   Inglés  : [B.A.I,] [please,] switch to online|offline mode [please] [.!]
# Cualquier otra cosa (negaciones, preguntas, comandos entre comillas, o el
# comando dentro de una frase) es un mensaje normal y NUNCA cambia el modo:
#   "No quiero cambiar a modo online"           -> mensaje normal
#   "Explica qué significa <<pasa a modo online>>" -> mensaje normal
#   "¿Puedo pasar a modo online?"               -> mensaje normal
_VOCATIVO = r"(?:b\.?a\.?i\.?\s*[,:]?\s+)?"
_COMANDOS_MODO = (
    re.compile(r"^" + _VOCATIVO + r"(?:por\s+favor[,]?\s+)?(?:pasa|pasar|cambia|cambiar)\s+al?\s+modo\s+"
               r"(?P<modo>online|offline)(?:[,]?\s+por\s+favor)?[.!]*$", re.I),
    re.compile(r"^" + _VOCATIVO + r"(?:please[,]?\s+)?switch\s+to\s+(?P<modo>online|offline)\s+mode"
               r"(?:[,]?\s+please)?[.!]*$", re.I),
)
_COMANDOS_ESTADO = {"estado", "modo actual", "que modo usas", "qué modo usas", "status", "current mode"}
# Prefijo para pedir explícitamente el motor online en un único turno (sólo en modo online)
_PREFIJO_ONLINE = re.compile(r"^\s*(online|en\s+l[ií]nea)\s*:\s*(.+)$", re.I | re.S)

AUTORIZACION_ONLINE = ("Para autorizar el uso de servicios online escribe 'pasa a modo online' "
                       "(B.A.I nunca lo hace por su cuenta).")

_selector = None
_avisador = print  # destino de los avisos de respaldo (la interfaz gráfica lo sustituye)
ultima_respuesta = None  # RespuestaMotor del último turno generado (None si falló o fue un comando)


def set_avisador(funcion):
    """Cambia el destino de los avisos de respaldo; None restaura la consola."""
    global _avisador
    _avisador = funcion or print


def get_selector():
    """Instancia única del selector (se crea de forma perezosa)."""
    global _selector
    if _selector is None:
        _selector = ModelSelector()
        _selector.activar_worker()
    return _selector


def set_selector(selector):
    """Permite sustituir el selector (tests o configuración alternativa)."""
    global _selector
    _selector = selector


def get_system_prompt():
    with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def detectar_comando_modo(texto):
    """
    Devuelve 'online' / 'offline' si el mensaje completo es un comando explícito
    de cambio de modo (ver sintaxis en _COMANDOS_MODO), o None en cualquier otro
    caso: negaciones, preguntas, comillas o comandos incrustados en otra frase.
    """
    if not isinstance(texto, str):
        return None
    limpio = " ".join(texto.split())  # normaliza espacios; no se quitan signos de interrogación ni comillas
    for patron in _COMANDOS_MODO:
        m = patron.match(limpio)
        if m:
            return m.group("modo").lower()
    return None


def es_comando_estado(texto):
    return texto.strip().lower().rstrip("?¿!.") in _COMANDOS_ESTADO


def construir_mensajes(user_input, chat_history, system_prompt=None, memory_context=None):
    """Construye la lista de mensajes que se envía al motor (online u offline)."""
    if system_prompt is None:
        system_prompt = get_system_prompt()
    if memory_context is None:
        memory_context = get_memory_context()

    mensajes = [m for m in (chat_history or []) if m.get("role") != "system"]
    mensajes.insert(0, {"role": "system", "content": system_prompt})
    if memory_context and memory_context.strip():
        mensajes.insert(1, {"role": "system", "content": memory_context})
    mensajes.append({"role": "system", "content": "Responde siempre en el idioma del usuario."})
    mensajes.append({"role": "user", "content": user_input})
    return mensajes


def etiqueta_motor(respuesta):
    """Etiqueta corta con el backend que ha respondido: motor · modelo · tipo [· fallback]."""
    partes = [respuesta.motor, respuesta.modelo, respuesta.tipo]
    if respuesta.fallback_usado:
        partes.append("fallback")
    return "[" + " · ".join(partes) + "]"


def _mostrar_motor(selector):
    return bool(selector.config.get("mostrar_motor", True))


def describir_motor_activo(selector, modo=None):
    """Frase con el motor que respondería ahora mismo en `modo` (o por qué ninguno)."""
    candidato, _, errores = selector.seleccionar(modo)
    if candidato is not None:
        return f"Motor activo: {candidato.nombre} [{candidato.modelo}] ({candidato.tipo})."
    detalle = "; ".join(f"{m}: {e}" for m, e in errores) or "sin candidatos"
    return f"ATENCIÓN: ningún motor disponible en este modo ({detalle})."


def describir_politica(selector):
    """Una línea que explica qué implica el modo actual en cuanto a servicios externos."""
    if selector.modo == "offline":
        return (f"Sólo motores locales. {selector.aislamiento()['descripcion']} "
                "No se pasará a online sin tu orden explícita.")
    if selector.prioridad == "local":
        return ("Uso de servicios online AUTORIZADO. Prioridad local: el motor online sólo se usa si ningún "
                "motor local responde (o con el prefijo 'online:' en un mensaje).")
    return "Uso de servicios online AUTORIZADO. Prioridad online: motor online primero, locales como respaldo."


def describir_estado(selector=None):
    """Texto legible con el modo actual y la disponibilidad de cada motor candidato."""
    selector = selector or get_selector()
    estado = selector.estado()
    lineas = [f"Modo actual: {estado['modo'].upper()} — {describir_politica(selector)}"]
    for c in estado["candidatos"]:
        marca = "OK " if c["disponible"] else "-- "
        detalle = "" if c["disponible"] else f" ({c['motivo']})"
        lineas.append(f"  {marca}{c['tipo']:<7} {c['motor']:<10} modelo={c['modelo']}{detalle}")
    return "\n".join(lineas)


def ask(user_input, chat_history, selector=None):
    """
    Punto de entrada del asistente. Devuelve el texto de respuesta y añade el
    turno (user/assistant) a `chat_history` sólo si un motor ha respondido.
    """
    if es_peticion_ayuda(user_input):
        return AYUDA_BAI
    selector = selector or get_selector()
    if chat_history is None:
        chat_history = []

    # --- comandos de control (no se envían al motor ni se "aprenden") ---------
    nuevo_modo = detectar_comando_modo(user_input)
    if nuevo_modo:
        try:
            selector.set_modo(nuevo_modo)
        except AislamientoActivo as e:
            return f"Sigo en modo OFFLINE. {e}"
        if nuevo_modo == "offline":
            aviso = "Modo cambiado a OFFLINE."
        else:
            aviso = "Modo cambiado a ONLINE (autorizado por ti)."
        return f"{aviso} {describir_politica(selector)} {describir_motor_activo(selector)}"

    if es_comando_estado(user_input):
        return describir_estado(selector)

    # --- prefijo 'online:' (sólo se aplica a la generación, más abajo) ----------
    prioridad_turno = None
    m = _PREFIJO_ONLINE.match(user_input)
    texto = m.group(2).strip() if m else user_input

    # --- peticiones de memoria en lenguaje natural (fase 7) --------------------
    # Se resuelven LOCALMENTE antes de tocar el selector, con o sin prefijo
    # 'online:' y en cualquier modo: nunca provocan inferencia (ni online ni
    # offline) ni comprobaciones de conectividad. Sólo las peticiones
    # explícitas llegan aquí; la conversación normal no escribe nada.
    respuesta_memoria = procesar_comando_memoria(texto)
    if respuesta_memoria is not None:
        return respuesta_memoria

    # --- petición explícita de motor online para este turno ---------------------
    if m:
        if selector.modo == "offline":
            # Sin autorización previa no se contacta con ningún servicio externo.
            return f"Estás en modo OFFLINE: no usaré el motor online para este mensaje. {AUTORIZACION_ONLINE}"
        prioridad_turno = "online"
        user_input = texto

    # --- generación ------------------------------------------------------------
    global ultima_respuesta
    ultima_respuesta = None
    mensajes = construir_mensajes(user_input, chat_history)

    try:
        with avisos_contexto(_avisador):
            respuesta = selector.responder(mensajes, prioridad=prioridad_turno)
    except SinMotorDisponible as e:
        # Turno fallido: ni historial ni memoria se modifican, y el modo no cambia.
        detalle = "\n".join(f"  - {motor}: {motivo}" for motor, motivo in e.errores)
        texto = (f"Ningún motor ha podido responder en modo {e.modo.upper()}.\n{detalle}\n"
                 f"Revisa config/motors_config.yaml o escribe 'estado' para diagnosticar.")
        if e.modo == "offline":
            texto += f"\nNo se ha contactado con ningún servicio externo. {AUTORIZACION_ONLINE}"
        return texto

    if respuesta.fallback_usado:
        descartados = ", ".join(f"{m} ({e})" for m, e in respuesta.errores)
        if respuesta.tipo == "online":
            _avisador(f"[B.A.I] Aviso: ningún motor local ha respondido ({descartados}). "
                  f"Uso el motor online autorizado {respuesta.motor} [{respuesta.modelo}].")
        else:
            _avisador(f"[B.A.I] Aviso: motor principal no disponible ({descartados}). "
                  f"Respondo con {respuesta.motor} [{respuesta.modelo}].")

    # Turno completado: se persiste el historial. La memoria persistente NO se
    # toca: sólo escriben las peticiones explícitas (procesar_comando_memoria).
    comprobar_cancelacion()
    ultima_respuesta = respuesta
    chat_history.append({"role": "user", "content": user_input})
    chat_history.append({"role": "assistant", "content": respuesta.texto})

    if _mostrar_motor(selector):
        return f"{respuesta.texto}\n{etiqueta_motor(respuesta)}"
    return respuesta.texto
