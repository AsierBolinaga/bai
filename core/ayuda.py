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
El arranque offline no descarga modelos ni comprueba conectividad.
Si falta el Qwen configurado, abro en modo degradado; ayuda, memoria y estado
siguen disponibles. Para descargarlo o verificarlo, cierra B.A.I. y ejecuta
'./bai.sh --preparar-modelo'. Esa acción explícita necesita red si falta el modelo,
verifica tamaño y SHA256 y termina sin abrir el chat ni enviar conversaciones.
Después inicia B.A.I. normalmente; cambiar a Online requiere tu autorización.

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
Mientras genero, Enviar se sustituye por Cancelar; también puedes pulsar Escape.
Cancelo el proceso del motor y descarto el turno interrumpido, sin probar otro
motor ni añadir una respuesta parcial al historial. Puedes volver a preguntar;
tras cancelar, el modelo local tendrá que cargarse de nuevo.
Cerrar cancela la generación y guarda sólo los turnos completados, sin esperar
a que responda el backend. Si el guardado no confirma el cierre en tres segundos,
ofrezco cerrar sin confirmarlo (con riesgo de perder cambios) o seguir esperando.
Si el guardado falla, la ventana queda abierta para reintentar.
En consola, Ctrl+C durante una respuesta la cancela; Ctrl+C en la entrada sale.
Cancelar no deshace órdenes de memoria ya ejecutadas ni retira datos enviados
online. Detengo el worker y sus hijos locales, pero no puedo garantizar que un
servidor remoto deje de calcular o facturar una petición que ya recibió.

VOZ LOCAL (VENTANA, FASE 9 EN PROGRESO)
Puedo leer respuestas y reconocer el micrófono localmente. La clonación de
voces no está implementada.
El botón 'Voz: OFF' activa la lectura con voz automática según el idioma de la respuesta.
'Voz: ON' la silencia y corta el audio. También se detiene al enviar un mensaje
nuevo o cerrar. Está desactivada al abrir; requiere Piper, un modelo de voz
instalado y el reproductor aplay con una salida de audio disponible.
Cada lectura empieza por defecto con tres segundos de silencio para dar tiempo a activar
la salida de audio sin perder las primeras palabras.
Uso Davefx para castellano, Antton para euskera y Northern English Male para
cualquier otro idioma. La detección es local y puede fallar con textos cortos
o mezclados. No traduzco el texto; la tercera voz está preparada para inglés.
Una vez instalada funciona
sin internet: no usa servicios online ni descarga modelos automáticamente.
No es la voz de JARVIS de las películas.
No hay selector manual ni botón de prueba: sólo estas tres voces automáticas.
Las voces son independientes: basta instalar una con sus archivos .onnx y
.onnx.json. Si falta la correspondiente al idioma, uso una instalada en orden
castellano, euskera, inglés, y muestro un aviso sin apagar Voz. No traduzco el
texto: la pronunciación con otra voz puede no ser adecuada. Si no queda ninguna
voz completa, aviso del error; instala una y vuelve a activar Voz. Un modelo
corrupto o un fallo de reproducción sigue siendo un error, no una voz ausente.
Debajo de Voz, 'Escucha: OFF' activa el micrófono continuo; 'Escucha: ON' lo apaga
y descarta la frase pendiente. Arranca apagado y es independiente de la salida de voz.
Cada captura calibra el ruido durante un segundo: guarda silencio hasta ver
'Escuchando'. Después muestra 'Voz detectada' y la cuenta de silencio.
Si hablas durante la calibración o muy bajo, puede no detectar tu voz.
Después de detectar habla, espero por defecto cinco segundos de silencio y envío la frase
automáticamente. El silencio inicial no envía mensajes. La transcripción y la respuesta
añaden tiempo de espera. Pauso el micrófono mientras transcribo, respondo o leo en voz
alta; después vuelvo a escuchar. Lo que digas durante esa pausa no se recoge.
El selector del micrófono permite Automático, Castellano, Euskera e Inglés.
Para euskera conviene seleccionar Euskera: la detección automática suele confundirlo.
Cambiar el idioma descarta la captura pendiente, sin modificar las voces de salida.
Requiere requirements-escucha.txt, PortAudio, un micrófono disponible y preparar
el modelo con 'venv/bin/python -m core.escucha --preparar' antes de arrancar.
Uso Whisper small multilingüe en CPU, sin traducir ni enviar audio a servicios externos.
Whisper permanece cargado mientras Escucha está ON; Piper conserva las voces usadas
mientras Voz está ON. Las pausas no recargan los modelos. OFF y el cierre liberan
los workers y su memoria. Esto reduce las cargas repetidas, pero ocupa más RAM.
En config/audio_config.yaml puedes ajustar silencio_escucha (0.3–30 s) y
silencio_reproduccion (0–10 s). Apaga y enciende la función para releerlo.
Los valores iniciales siguen siendo 5 y 3 s; bajar el segundo puede volver a cortar
las primeras palabras. La calibración, transcripción y generación añaden su tiempo.
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
