"""Descripción y guía local, compartidas por la ventana y la consola."""
import unicodedata

DESCRIPCION_BAI = ("B.A.I — Boli Artificial Intelligence: tu asistente personal "
                   "con memoria local y acceso online bajo tu control.")

AYUDA_BAI = """Soy B.A.I — Boli Artificial Intelligence, tu asistente personal con memoria local.

CONVERSACIÓN
Escribe un mensaje y pulsa Enter o Enviar. Para conversar necesito un motor
disponible: un modelo local instalado o un servicio online configurado.
Si ninguno responde, te indico el motivo; no invento una respuesta.

MODOS Y PRIVACIDAD
OFFLINE: es el modo de arranque por defecto. Sólo uso motores locales y no
contacto servicios externos, ni salto a online si falla un modelo.
Puedes usar la memoria, la ayuda y el estado sin ningún motor disponible.

DE OFFLINE A ONLINE: pulsa Online o escribe 'pasa a modo online'.
Esa orden autoriza servicios externos para la sesión; no obliga a enviar
cada mensaje a internet. Sigo la prioridad configurada: local primero y online
como respaldo, o bien online primero y locales como respaldo.
'online: tu pregunta' pide el motor online sólo para ese turno, pero exige
haber autorizado antes el modo online. No cambia por sí solo el modo.
Los mensajes enviados a un servicio online pueden incluir contexto del historial
y de la memoria. Online necesita un servicio configurado, sus credenciales
y conectividad; cambiar de modo no instala modelos ni configura servicios.
No escribas credenciales en el chat.

DE ONLINE A OFFLINE: pulsa Offline o escribe 'pasa a modo offline'.
Reactivo la protección de red Python y limito la generación a motores locales.
No borro el historial ni los hechos al cambiar de modo. Volver a offline no
retira información que ya se haya enviado a un servicio externo.
Escribe 'estado' para comprobar el modo y la protección realmente activos.

AISLAMIENTO: si el proceso arrancó en un namespace sin red, no puedo habilitar
online dentro de esa sesión: mantengo offline y explico cómo reiniciar.
Para autorizar online al arrancar usa 'python bai.py --ui --online'
(sin '--ui' para la consola). Con '--aislamiento python' se permiten cambios
en la misma sesión, pero esa protección no cubre subprocesos ni código nativo.

ESTADO Y MOTORES
Pulsa Estado o escribe 'estado' para consultar el modo, el aislamiento y los
motores disponibles. Autorizar online no instala motores ni configura servicios.
Un modelo ausente o un servicio sin configurar no puede responder.

MEMORIA PERSISTENTE
Las órdenes de memoria se procesan localmente, incluso sin motor:
  - 'recuerda que mi apodo es Boli': guarda un hecho.
  - '¿qué recuerdas?': lista los hechos.
  - '¿cuál es mi apodo?': consulta uno.
  - 'recuerda que ahora mi apodo es Asier': actualiza un hecho.
  - 'olvida mi apodo': elimina ese hecho.
La conversación ordinaria no autoriza cambios persistentes. Si una petición es
ambigua, pido aclaración; no todas las formas de lenguaje natural se reconocen.
Sólo confirmo una escritura cuando se ha guardado correctamente.

HISTORIAL Y VENTANA
Cargo el historial guardado al iniciar y guardo la conversación tras los turnos
y al cerrar. Limpiar o 'limpiar'/'reset' vacía la sesión en curso; no elimina
los hechos persistentes. En la ventana, ese vaciado se guarda en el siguiente
turno o al cerrar. No equivale a borrar todos los archivos de historial.
Proceso un mensaje a la vez; puedes redimensionar la ventana y desplazarte
por el chat. Escribe 'salir' o cierra la ventana para terminar.

AYUDA
Pulsa Ayuda o escribe 'ayuda', 'cómo funcionas' o 'explícame cómo funcionas'.
Esta guía y las consultas de estado no requieren un modelo ni acceso online."""

_PETICIONES = {
    "ayuda", "help", "como funcionas", "explicame como funcionas",
    "como funciona bai", "como funciona b.a.i", "que es bai", "que es b.a.i",
}


def es_peticion_ayuda(texto):
    normalizado = unicodedata.normalize("NFD", texto.casefold())
    normalizado = "".join(c for c in normalizado if not unicodedata.combining(c))
    return " ".join(normalizado.strip(" \t\r\n¿?¡!.").split()) in _PETICIONES
