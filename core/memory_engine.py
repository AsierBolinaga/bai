"""
Memoria de B.A.I. Dos almacenes independientes:

- Historial de conversación (history/historial.json): turnos user/assistant.
- Hechos persistentes (config/data/facts.yaml): datos que el usuario ha pedido
  recordar EXPLÍCITAMENTE ("recuerda que X es Y"...). Nunca se escriben de
  forma silenciosa a partir de la conversación; la interpretación de las
  peticiones en lenguaje natural vive en core/memory_commands.py.

Garantías del almacén de hechos:
- Escritura atómica (fichero temporal + os.replace): un fallo a mitad de
  escritura nunca destruye los datos anteriores.
- Un fichero dañado se detecta al cargar (MemoriaHechosInvalida) y NUNCA se
  sobreescribe: las operaciones fallan explicándolo y los datos quedan intactos.
- Claves normalizadas (minúsculas, sin acentos, sin artículo ni posesivo de
  primera persona iniciales) para que "mi Furgoneta" y "la furgoneta" sean el
  mismo hecho; la propiedad ajena se conserva ("tu coche", "el coche de Ana").
- Esquema versionado (version: 1): cualquier otra versión o clave desconocida
  se rechaza sin tocar el fichero.
- La memoria heredada de user_profile.yaml (fases anteriores) se migra una sola
  vez a facts.yaml, con copia de seguridad del perfil, para que sea consultable,
  editable y olvidable como cualquier otro hecho.
"""
import os
import json
import re
import shutil
import tempfile
import yaml
from datetime import datetime, timezone
import unicodedata

# Rutas absolutas respecto a la raíz del proyecto (independientes del directorio de trabajo)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(_PROJECT_ROOT, "history")
SESSION_FILE = os.path.join(HISTORY_DIR, "historial.json")
MEMORY_PATH = os.path.join(_PROJECT_ROOT, "config", "data", "user_profile.yaml")
FACTS_PATH = os.path.join(_PROJECT_ROOT, "config", "data", "facts.yaml")
MAX_MESSAGES = 5000
os.makedirs(HISTORY_DIR, exist_ok=True)


VERSION_ESQUEMA = 1


class MemoriaHechosInvalida(Exception):
    """El fichero de hechos existe pero no tiene un formato válido (YAML roto,
    esquema o versión desconocidos). No se sobreescribe nunca automáticamente."""


class ErrorLecturaMemoria(Exception):
    """No se ha podido LEER el fichero de hechos (permisos, E/S...). Distinto de
    un fallo de escritura: no se ha intentado modificar nada."""


# --------------------------------------------------------------------------- normalización
# Sólo se eliminan artículos y posesivos de PRIMERA persona: "mi coche" y "el
# coche" son el coche del usuario, pero "tu coche", "su coche" o "el coche de
# Ana" son hechos distintos y conservan su propietario.
_ARTICULOS = ("mi", "mis", "el", "la", "los", "las", "un", "una", "unos", "unas", "lo",
              "my", "the", "a", "an")
_COMILLAS = "\"'«»“”‘’"


def _sin_acentos(texto):
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def limpiar_valor(valor):
    """Quita espacios, puntuación final y comillas envolventes; conserva el texto original."""
    v = valor.strip().strip(".!").strip()
    if len(v) >= 2 and v[0] in _COMILLAS and v[-1] in _COMILLAS:
        v = v[1:-1].strip()
    return v


def normalizar_clave(clave):
    """Clave canónica: minúsculas, sin acentos, sin comillas ni puntuación final,
    sin artículo/posesivo inicial y con espacios colapsados."""
    c = _sin_acentos(limpiar_valor(clave)).lower()
    c = c.strip("¿?¡!,;:").strip()
    palabras = c.split()
    while len(palabras) > 1 and palabras[0] in _ARTICULOS:
        palabras = palabras[1:]
    return " ".join(palabras)


# --------------------------------------------------------------------------- almacén de hechos
_CLAVES_RAIZ = {"version", "hechos", "perfil_migrado"}
_CLAVES_ENTRADA = {"clave", "valor", "actualizado", "origen"}


def _validar_hechos(datos):
    """Valida el esquema completo. Un fichero vacío es un almacén vacío; todo lo
    demás debe ser exactamente {version: 1, hechos: {norma: {clave, valor, ...}}}."""
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        raise MemoriaHechosInvalida(f"la raíz debe ser un diccionario, no {type(datos).__name__}")
    desconocidas = set(datos) - _CLAVES_RAIZ
    if desconocidas:
        raise MemoriaHechosInvalida(f"esquema desconocido: claves {sorted(map(str, desconocidas))}")
    version = datos.get("version")
    if version != VERSION_ESQUEMA or isinstance(version, bool):
        raise MemoriaHechosInvalida(f"versión de esquema no soportada: {version!r} (esperada {VERSION_ESQUEMA})")
    hechos = datos.get("hechos", {})
    if hechos is None:
        hechos = {}
    if not isinstance(hechos, dict):
        raise MemoriaHechosInvalida("'hechos' debe ser un diccionario")
    if "perfil_migrado" in datos and not isinstance(datos["perfil_migrado"], str):
        raise MemoriaHechosInvalida("'perfil_migrado' debe ser una cadena")
    validados = {}
    for clave, entrada in hechos.items():
        if not isinstance(clave, str) or not isinstance(entrada, dict):
            raise MemoriaHechosInvalida(f"entrada inválida para '{clave}'")
        if set(entrada) - _CLAVES_ENTRADA:
            raise MemoriaHechosInvalida(f"entrada inválida para '{clave}': campos desconocidos")
        if not isinstance(entrada.get("clave"), str) or not isinstance(entrada.get("valor"), str):
            raise MemoriaHechosInvalida(f"entrada inválida para '{clave}': faltan 'clave'/'valor'")
        validados[clave] = dict(entrada)
    return validados


def _leer_almacen():
    """(hechos, meta) validados de FACTS_PATH, sin efectos secundarios.
    `meta` son las claves de raíz distintas de 'hechos'/'version' (p. ej. perfil_migrado)."""
    if not os.path.exists(FACTS_PATH):
        return {}, {}
    try:
        with open(FACTS_PATH, "r", encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise MemoriaHechosInvalida(f"YAML ilegible: {e}") from e
    except OSError as e:
        raise ErrorLecturaMemoria(str(e)) from e
    hechos = _validar_hechos(datos)
    meta = {k: v for k, v in (datos or {}).items() if k not in ("hechos", "version")}
    return hechos, meta


def _leer_hechos():
    return _leer_almacen()[0]


def cargar_hechos():
    """Diccionario clave_normalizada -> {clave, valor, actualizado}. {} si no hay fichero.
    Lanza MemoriaHechosInvalida si el fichero está dañado y ErrorLecturaMemoria
    si no se puede leer. Antes de leer migra (una sola vez) la memoria heredada."""
    migrar_perfil_legado()
    return _leer_hechos()


def _escribir_atomico(ruta, contenido, prefijo):
    """Escribe `contenido` en `ruta` vía fichero temporal + os.replace.
    Lanza OSError si falla; el fichero anterior queda intacto."""
    directorio = os.path.dirname(ruta) or "."
    os.makedirs(directorio, exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=directorio, prefix=prefijo, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def guardar_hechos(hechos, meta=None):
    """Escritura atómica del almacén completo (una sola operación: o se escribe
    todo o no se escribe nada). Lanza OSError si no se puede escribir; en ese
    caso el fichero anterior queda intacto. Conserva los metadatos (marca de
    migración) salvo que se pasen explícitamente."""
    if meta is None:
        try:
            meta = _leer_almacen()[1]
        except (MemoriaHechosInvalida, ErrorLecturaMemoria):
            meta = {}
    datos = dict(meta)
    datos.update({"version": VERSION_ESQUEMA, "hechos": hechos})
    contenido = yaml.safe_dump(datos, allow_unicode=True, sort_keys=True)
    _escribir_atomico(FACTS_PATH, contenido, ".facts-")


# --------------------------------------------------------------------------- migración del perfil heredado
_SUFIJO_RESPALDO = ".legado-{ts}.bak"


def _aplanar_perfil(datos):
    """Convierte el perfil heredado (diccionarios anidados, listas, escalares)
    en una lista [(ruta, valor_str)] sin perder ninguna hoja."""
    hojas = []

    def recorrer(valor, ruta):
        if isinstance(valor, dict):
            for k, v in valor.items():
                recorrer(v, ruta + [str(k)])
        elif valor is None or valor == "" or valor == [] or valor == {}:
            return
        elif isinstance(valor, list):
            hojas.append((ruta, ", ".join(_texto_legado(v) for v in valor)))
        else:
            hojas.append((ruta, _texto_legado(valor)))

    recorrer(datos, [])
    return hojas


def _texto_legado(valor):
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    return str(valor)


def _nombres_legado(hojas):
    """Nombre legible para cada hoja: la última parte de la ruta ("vehiculo"),
    con su padre inmediato si está anidada más de un nivel ("pareja nombre") y
    ampliada con más padres sólo si hiciera falta para no colisionar."""
    def partes_de(ruta):
        return [p.replace("_", " ") for p in ruta if p != "aprendido_durante_sesion"] or list(ruta)

    pendientes = {i: partes_de(r) for i, (r, _) in enumerate(hojas)}
    nombres = {}
    nivel = 1
    while pendientes:
        # sección.hoja -> "hoja"; sección.subsección.hoja -> "subsección hoja" (conserva el contexto)
        candidatos = {i: " ".join(p[-min(max(nivel, 2 if len(p) > 2 else 1), len(p)):])
                      for i, p in pendientes.items()}
        cuentas = {}
        for c in candidatos.values():
            cuentas[normalizar_clave(c)] = cuentas.get(normalizar_clave(c), 0) + 1
        for i, c in list(candidatos.items()):
            if cuentas[normalizar_clave(c)] == 1 or nivel >= len(pendientes[i]):
                nombres[i] = c
                del pendientes[i]
        nivel += 1
    return [(nombres[i], v) for i, (_, v) in enumerate(hojas)]


def _huella(ruta):
    import hashlib
    with open(ruta, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _vaciar_perfil():
    _escribir_atomico(MEMORY_PATH, yaml.safe_dump({"aprendido_durante_sesion": {}}), ".perfil-")


def migrar_perfil_legado():
    """Mueve los datos de user_profile.yaml a facts.yaml (una sola vez).

    Orden seguro: copia de respaldo del perfil -> escritura atómica de los
    hechos (que incluye la huella del perfil importado) -> perfil vaciado.
    Si algo falla no se pierde nada (el perfil original sigue ahí o en la
    copia) y se avisa. La huella evita que un perfil que no se pudo vaciar se
    vuelva a importar y resucite hechos olvidados después.
    Devuelve el número de datos migrados (0 si no había nada que migrar)."""
    if not os.path.exists(MEMORY_PATH):
        return 0
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            perfil = yaml.safe_load(f)
        huella = _huella(MEMORY_PATH)
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        print(f"[B.A.I] Aviso: no puedo leer el perfil heredado para migrarlo ({e}); lo dejo como está.")
        return 0
    if not isinstance(perfil, dict):
        return 0
    hojas = _aplanar_perfil(perfil)
    if not hojas:
        return 0

    try:
        hechos, meta = _leer_almacen()
    except (MemoriaHechosInvalida, ErrorLecturaMemoria) as e:
        print(f"[B.A.I] Aviso: no migro el perfil heredado porque la memoria de hechos no está disponible ({e}).")
        return 0

    if meta.get("perfil_migrado") == huella:
        # Ya importado en un intento anterior cuyo vaciado del perfil falló: NO se reimporta
        # (podría resucitar hechos olvidados desde entonces); sólo se reintenta vaciar el perfil.
        try:
            _vaciar_perfil()
        except OSError as e:
            print(f"[B.A.I] Aviso: el perfil heredado ya está migrado pero sigo sin poder vaciarlo ({e}).")
        return 0

    migrados = 0
    for nombre, valor in _nombres_legado(hojas):
        norma = normalizar_clave(nombre)
        if not norma:
            continue
        if norma in hechos and hechos[norma]["valor"].strip().lower() == valor.strip().lower():
            continue
        if norma in hechos:
            # Conflicto con un hecho ya guardado: se conserva el heredado aparte, sin sobreescribir.
            nombre, norma = f"{clave_sin_articulo(nombre)} (perfil anterior)", normalizar_clave(f"{nombre} (perfil anterior)")
            if norma in hechos:
                continue
        hechos[norma] = {"clave": clave_sin_articulo(nombre), "valor": valor,
                         "actualizado": _ahora(), "origen": "user_profile.yaml"}
        migrados += 1

    respaldo = MEMORY_PATH + _SUFIJO_RESPALDO.format(ts=datetime.now().strftime("%Y%m%d-%H%M%S"))
    try:
        shutil.copyfile(MEMORY_PATH, respaldo)
        meta = dict(meta, perfil_migrado=huella)
        guardar_hechos(hechos, meta)
    except OSError as e:
        print(f"[B.A.I] Aviso: no he podido migrar el perfil heredado ({e}); sigue intacto en {MEMORY_PATH}.")
        return 0
    try:
        _vaciar_perfil()
    except OSError as e:
        print(f"[B.A.I] Aviso: perfil heredado migrado pero no he podido vaciarlo ({e}); "
              f"no se volverá a importar.")
    print(f"[B.A.I] Memoria heredada migrada: {migrados} dato(s) de user_profile.yaml ahora son hechos "
          f"(consultables, editables y olvidables). Copia del perfil original: {respaldo}")
    return migrados


# --------------------------------------------------------------------------- operaciones sobre hechos
def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clave_sin_articulo(clave):
    """Versión legible de la clave sin el artículo/posesivo inicial (conserva acentos)."""
    c = limpiar_valor(clave).strip("¿?¡!,;:").strip()
    palabras = c.split()
    while len(palabras) > 1 and _sin_acentos(palabras[0]).lower() in _ARTICULOS:
        palabras = palabras[1:]
    return " ".join(palabras)


def recordar_hecho(clave, valor):
    """Guarda un hecho nuevo. Devuelve ('guardado', None) | ('duplicado', valor)
    | ('conflicto', valor_existente). En caso de conflicto NO sobreescribe.
    Sólo devuelve 'guardado' si la escritura en disco ha terminado bien."""
    (_, estado, valor, anterior), = aplicar_hechos([(clave, valor)], reemplazar=False)
    if estado == "guardado":
        return "guardado", None
    if estado == "duplicado":
        return "duplicado", valor
    return "conflicto", anterior


def actualizar_hecho(clave, valor):
    """Crea o reemplaza el valor de un hecho (operación explícita de actualización).
    Devuelve ('actualizado', valor_anterior) o ('creado', None)."""
    (_, estado, _, anterior), = aplicar_hechos([(clave, valor)], reemplazar=True)
    if estado == "duplicado":
        return "actualizado", anterior if anterior is not None else limpiar_valor(valor)
    return estado, anterior


def aplicar_hechos(parejas, reemplazar=False):
    """Aplica varios hechos con UNA sola escritura atómica: o se persisten
    todos los cambios o ninguno. Devuelve [(clave_visible, estado, valor, anterior)]
    con estado en guardado | creado | actualizado | duplicado | conflicto.
    Los 'conflicto' (valor distinto sin `reemplazar`) no se escriben."""
    hechos = cargar_hechos()
    resultados = []
    cambios = False
    for clave, valor in parejas:
        visible, valor = clave_sin_articulo(clave), limpiar_valor(valor)
        norma = normalizar_clave(visible)
        existente = hechos.get(norma)
        if existente is not None and existente["valor"].strip().lower() == valor.strip().lower():
            resultados.append((existente["clave"], "duplicado", existente["valor"], None))
            continue
        if existente is not None and not reemplazar:
            resultados.append((existente["clave"], "conflicto", valor, existente["valor"]))
            continue
        hechos[norma] = {"clave": existente["clave"] if existente else visible,
                         "valor": valor, "actualizado": _ahora()}
        cambios = True
        if existente is None:
            resultados.append((visible, "creado" if reemplazar else "guardado", valor, None))
        else:
            resultados.append((existente["clave"], "actualizado", valor, existente["valor"]))
    if cambios:
        guardar_hechos(hechos)
    return resultados


def claves_existentes(candidatas):
    """Entre varias claves candidatas, las que existen tal cual en el almacén
    (normalizadas), sin repetidos y en el mismo orden. Sirve para resolver la
    clave COMPLETA antes de modificar nada ("viaje a Roma" frente a "viaje")."""
    hechos = cargar_hechos()
    vistas = set()
    resultado = []
    for c in candidatas:
        norma = normalizar_clave(c)
        if norma in hechos and norma not in vistas:
            vistas.add(norma)
            resultado.append(c)
    return resultado


def obtener_hecho(clave):
    """(clave_visible, valor) o None. Sólo lectura y sólo coincidencia EXACTA."""
    entrada = cargar_hechos().get(normalizar_clave(clave))
    if entrada is None:
        return None
    return entrada["clave"], entrada["valor"]


_RE_PROPIETARIO = re.compile(
    r"^(?:tu|tus|su|sus|your|his|her|their|our|nuestr[oa]s?|vuestr[oa]s?)\b"      # "tu coche"
    r"|\bde\s+(?:mi|mis|tu|tus|su|sus|nuestr[oa]s?|my|your|his|her|their|our)\b.*$"  # "coche de mi hermano"
    r"|\bde\s+[A-ZÁÉÍÓÚÑ]\w*.*$"                                                  # "coche de Ana"
    r"|\b\w+'s\b")                                                               # "Ana's car"


def propietario(clave):
    """Firma de propiedad de una clave legible ('' = del usuario). Sirve para que
    "coche" nunca se confunda con "tu coche", "el coche de Ana" o "Ana's car"."""
    m = _RE_PROPIETARIO.search(clave.strip())
    return _sin_acentos(m.group(0)).lower() if m else ""


def buscar_hechos(texto):
    """Hechos cuya clave contiene (o está contenida en) el texto normalizado y
    pertenecen al MISMO propietario. Son SUGERENCIAS (coincidencias parciales),
    nunca hechos confirmados."""
    aguja = normalizar_clave(texto)
    if not aguja:
        return []
    dueno = propietario(clave_sin_articulo(texto))
    resultados = []
    for norma, entrada in sorted(cargar_hechos().items()):
        if (aguja in norma or norma in aguja) and propietario(entrada["clave"]) == dueno:
            resultados.append((entrada["clave"], entrada["valor"]))
    return resultados


def listar_hechos():
    """Lista ordenada de (clave_visible, valor)."""
    return [(e["clave"], e["valor"]) for _, e in sorted(cargar_hechos().items())]


def olvidar_hecho(clave):
    """Elimina un hecho por coincidencia EXACTA de clave. Devuelve el valor
    olvidado o None si no existía. Sólo devuelve un valor tras persistir."""
    norma = normalizar_clave(clave)
    hechos = cargar_hechos()
    entrada = hechos.pop(norma, None)
    if entrada is None:
        return None
    guardar_hechos(hechos)
    return entrada["valor"]


def olvidar_todos():
    """Vacía el almacén de hechos. Devuelve cuántos había."""
    hechos = cargar_hechos()
    cuantos = len(hechos)
    if cuantos:
        guardar_hechos({})
    return cuantos


# --------------------------------------------------------------------------- historial
# Ficheros de historial ilegibles que no se han podido apartar: nunca se sobreescriben.
_historiales_protegidos = set()


def _destino_historial():
    """Ruta donde guardar el historial: la normal, o una alternativa si la
    normal contiene un historial ilegible que no se pudo apartar."""
    if SESSION_FILE in _historiales_protegidos and os.path.exists(SESSION_FILE):
        base, ext = os.path.splitext(SESSION_FILE)
        return f"{base}.nuevo-{datetime.now().strftime('%Y%m%d-%H%M%S')}{ext}"
    return SESSION_FILE


def save_chat_history(history):
    """Guarda el historial de forma atómica. Devuelve True si se ha escrito;
    si falla avisa y devuelve False (la copia anterior en disco queda intacta).
    Un historial.json ilegible que no se pudo apartar nunca se sobreescribe:
    se guarda en un fichero nuevo junto a él."""
    try:
        contenido = json.dumps(history, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        print(f"[B.A.I] Aviso: no puedo serializar el historial ({e}); no lo guardo.")
        return False
    destino = _destino_historial()
    try:
        _escribir_atomico(destino, contenido, ".historial-")
        if destino != SESSION_FILE:
            print(f"[B.A.I] Aviso: {SESSION_FILE} es ilegible y se conserva; historial guardado en {destino}.")
        return True
    except OSError as e:
        print(f"[B.A.I] Aviso: no he podido guardar el historial ({e}).")
        return False


def _turnos_validos(session):
    if not isinstance(session, list):
        raise ValueError("el historial debe ser una lista de mensajes")
    turnos = []
    for m in session:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            turnos.append({"role": m["role"], "content": m["content"]})
    return turnos


def _apartar_corrupto(path, motivo):
    """Renombra un fichero de historial ilegible para conservarlo (nunca se sobreescribe)."""
    respaldo = f"{path}.corrupto-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    try:
        os.replace(path, respaldo)
        _historiales_protegidos.discard(path)
        print(f"[B.A.I] Aviso: historial ilegible ({motivo}); conservado en {respaldo}. Empiezo uno nuevo.")
        return True
    except OSError as e:
        _historiales_protegidos.add(path)
        print(f"[B.A.I] Aviso: historial ilegible ({motivo}) y no puedo apartarlo ({e}); no lo tocaré.")
        return False


def load_full_history():
    messages = []
    archivos_a_borrar = []
    reescribir = True   # sólo se reescribe historial.json si se ha podido leer (o apartar) sin pérdida

    os.makedirs(HISTORY_DIR, exist_ok=True)

    # Cargar historial activo si existe
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                messages.extend(_turnos_validos(json.load(f)))
        except (ValueError, UnicodeDecodeError) as e:       # JSON roto o estructura inesperada
            reescribir = _apartar_corrupto(SESSION_FILE, e)
        except OSError as e:                                  # no se puede leer: no se toca
            _historiales_protegidos.add(SESSION_FILE)
            print(f"[B.A.I] Aviso: no puedo leer {SESSION_FILE} ({e}); sigo sin historial y no lo modificaré.")
            reescribir = False
        else:
            _historiales_protegidos.discard(SESSION_FILE)

    # Cargar sesiones anteriores (los ficheros ilegibles se conservan sin tocar)
    for file in sorted(os.listdir(HISTORY_DIR)):
        if file.endswith(".json") and file != os.path.basename(SESSION_FILE):
            path = os.path.join(HISTORY_DIR, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    messages.extend(_turnos_validos(json.load(f)))
                    archivos_a_borrar.append(path)
            except Exception as e:
                print(f"[B.A.I] Error cargando {file}: {e}")

    messages = messages[-MAX_MESSAGES:]

    if reescribir and not save_chat_history(messages):
        return messages   # no se borran las sesiones antiguas si no se ha podido consolidar

    if reescribir:
        for path in archivos_a_borrar:
            try:
                os.remove(path)
            except Exception as e:
                print(f"[B.A.I] Error borrando {path}: {e}")

    return messages


def _contexto_perfil():
    """Texto con el perfil estático (user_profile.yaml). Nunca lanza: un perfil
    ausente o dañado no debe impedir conversar."""
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            memory = yaml.safe_load(f)
    except FileNotFoundError:
        return []
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        print(f"[B.A.I] Aviso: no se puede leer el perfil ({e}); sigo sin él.")
        return []
    if not isinstance(memory, dict):
        if memory is not None:
            print("[B.A.I] Aviso: perfil con formato inesperado; lo ignoro.")
        return []

    aprendido = memory.get("aprendido_durante_sesion", {}) or {}
    texto = []
    for k, v in memory.items():
        if k == "aprendido_durante_sesion":
            continue
        if isinstance(v, dict):
            for subk, subv in v.items():
                if isinstance(subv, dict):
                    for ssubk, ssubv in subv.items():
                        texto.append(f"{ssubk.capitalize()} es {ssubv}.")
                elif isinstance(subv, list):
                    texto.append(f"{subk.capitalize()} incluye: {', '.join(map(str, subv))}.")
                else:
                    texto.append(f"{subk.capitalize()} es {subv}.")
        elif isinstance(v, list):
            texto.append(f"{k.capitalize()} incluye: {', '.join(map(str, v))}.")
        else:
            texto.append(f"{k.capitalize()} es {v}.")
    if isinstance(aprendido, dict):
        for k, v in aprendido.items():
            texto.append(f"{str(k).capitalize()} es {v}.")
    return texto


def _contexto_hechos():
    """Líneas con los hechos persistentes. Un fichero dañado no rompe el turno
    (se avisa por consola y las operaciones explícitas informarán del problema)."""
    try:
        hechos = listar_hechos()
    except MemoriaHechosInvalida as e:
        print(f"[B.A.I] Aviso: memoria de hechos dañada ({e}); no la inyecto en el contexto.")
        return []
    except ErrorLecturaMemoria as e:
        print(f"[B.A.I] Aviso: no puedo leer la memoria de hechos ({e}); sigo sin ella.")
        return []
    if not hechos:
        return []
    lineas = ["Hechos que el usuario pidió recordar (memoria persistente):"]
    lineas.extend(f"- {clave}: {valor}" for clave, valor in hechos)
    return lineas


def get_memory_context():
    """Contexto de memoria que se inyecta como mensaje de sistema: perfil
    estático + hechos persistentes. Devuelve '' si no hay nada."""
    hechos = _contexto_hechos()      # primero: dispara la migración del perfil heredado si procede
    return "\n".join(_contexto_perfil() + hechos)