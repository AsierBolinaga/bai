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
Antes de abrir la sesión, el lanzador comprueba el Qwen ligero configurado:
si falta, lo descarga de Hugging Face y verifica su SHA256. Esa preparación
sí necesita internet, pero no envía conversaciones. Después aplica el aislamiento.

DE OFFLINE A ONLINE: pulsa Online o escribe 'pasa a modo online'.
Con aislamiento de proceso, ofrezco guardar y reiniciar antes de cambiar.
Esa orden autoriza servicios externos para la sesión. La configuración actual
usa Copilot primero, sin respaldo local automático; otras configuraciones pueden
dar prioridad local.
'online: tu pregunta' pide el motor online sólo para ese turno, pero exige
haber autorizado antes el modo online. No cambia por sí solo el modo.
Los mensajes enviados a un servicio online pueden incluir contexto del historial
y de la memoria. Online necesita un servicio configurado, sus credenciales
y conectividad; cambiar de modo no instala modelos ni configura servicios.
Copilot usa la cuenta autenticada con 'copilot login', no la sesión de VS Code
automáticamente. Requiere Copilot CLI y requirements-copilot.txt. El chat no
tiene herramientas, permisos de archivos ni ejecución de comandos.
No escribas credenciales en el chat.

DE ONLINE A OFFLINE: pulsa Offline o escribe 'pasa a modo offline'.
Con aislamiento de proceso, ofrezco guardar y reiniciar para recuperar el
bloqueo del kernel. Con aislamiento Python cambio en la misma sesión.
Limito la generación a motores locales.
No borro el historial ni los hechos al cambiar de modo. Volver a offline no
retira información que ya se haya enviado a un servicio externo.
Escribe 'estado' para comprobar el modo y la protección realmente activos.

AISLAMIENTO: si el proceso arrancó en un namespace sin red, no puedo habilitar
online dentro de esa sesión: el lanzador externo debe reiniciarla, con confirmación
y sólo después de guardar. Si falla el guardado, no reinicio.
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
los hechos persistentes. El historial vacío se guarda inmediatamente; si falla
el guardado, te aviso. No equivale a borrar todos los archivos de historial.
Proceso un mensaje a la vez; puedes redimensionar la ventana y desplazarte
por el chat. Escribe 'salir' o cierra la ventana para terminar.
Si hay una generación en curso, el cierre espera sin congelar la ventana y
guarda al terminar. No cancela la generación: si el motor no termina, el cierre
sigue esperando. Si falla el guardado, la ventana queda abierta para reintentar.

VOZ LOCAL (VENTANA, FASE 9 EN PROGRESO)
Puedo leer respuestas y reconocer el micrófono localmente. La clonación de
voces no está implementada.
El botón 'Voz: OFF' activa la lectura con voz automática según el idioma de la respuesta.
'Voz: ON' la silencia y corta el audio. También se detiene al enviar un mensaje
nuevo o cerrar. Está desactivada al abrir; requiere Piper, un modelo de voz
instalado y el reproductor aplay con una salida de audio disponible.
Cada lectura empieza con tres segundos de silencio para dar tiempo a activar
la salida de audio sin perder las primeras palabras.
Uso Davefx para castellano, Antton para euskera y Northern English Male para
cualquier otro idioma. La detección es local y puede fallar con textos cortos
o mezclados. No traduzco el texto; la tercera voz está preparada para inglés.
Una vez instalada funciona
sin internet: no usa servicios online ni descarga modelos automáticamente.
No es la voz de JARVIS de las películas.
No hay selector manual ni botón de prueba: sólo estas tres voces automáticas.
Debajo de Voz, 'Escucha: OFF' activa el micrófono continuo; 'Escucha: ON' lo apaga
y descarta la frase pendiente. Arranca apagado y es independiente de la salida de voz.
Después de detectar habla, espero cinco segundos de silencio y envío la frase
automáticamente. El silencio inicial no envía mensajes. La transcripción y la respuesta
añaden tiempo de espera. Pauso el micrófono mientras transcribo, respondo o leo en voz
alta; después vuelvo a escuchar. Lo que digas durante esa pausa no se recoge.
El selector del micrófono permite Automático, Castellano, Euskera e Inglés.
Para euskera conviene seleccionar Euskera: la detección automática suele confundirlo.
Cambiar el idioma descarta la captura pendiente, sin modificar las voces de salida.
Requiere requirements-escucha.txt, PortAudio, un micrófono disponible y preparar
el modelo con 'venv/bin/python -m core.escucha --preparar' antes de arrancar.
Uso Whisper small multilingüe en CPU, sin traducir ni enviar audio a servicios externos.
No guardo grabaciones: la transcripción entra al chat y al historial como un mensaje
escrito. En modo online, esa transcripción se envía al motor online como cualquier texto.
El ruido, el acento y frases cortas pueden producir errores; no se garantiza exactitud.
Tras 90 segundos de captura sin terminar la frase, muestro un error y apago la escucha.
Un fallo de micrófono o transcripción también la apaga con aviso; puedes reactivarla.
No hay palabra de activación: mientras Escucha está ON recoge el habla de alrededor.
La esfera indica cuándo preparo la respuesta y cuándo la estoy leyendo;
su pulso es decorativo, no sigue la amplitud del sonido.

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
