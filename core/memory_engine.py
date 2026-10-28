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
import hashlib
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
_CLAVES_RAIZ = {"version", "hechos", "legado_migrado"}
_CLAVES_ENTRADA = {"clave", "valor", "actualizado", "origen"}


def _validar_almacen(datos):
    """Valida el esquema completo. Un fichero vacío es un almacén vacío; todo lo
    demás debe ser {version: 1, hechos: {norma: {clave, valor, ...}},
    legado_migrado: [huellas]} (legado_migrado es opcional).
    Devuelve {"hechos": dict, "legado_migrado": set}."""
    if datos is None:
        return {"hechos": {}, "legado_migrado": set()}
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
    validados = {}
    for clave, entrada in hechos.items():
        if not isinstance(clave, str) or not isinstance(entrada, dict):
            raise MemoriaHechosInvalida(f"entrada inválida para '{clave}'")
        if set(entrada) - _CLAVES_ENTRADA:
            raise MemoriaHechosInvalida(f"entrada inválida para '{clave}': campos desconocidos")
        if not isinstance(entrada.get("clave"), str) or not isinstance(entrada.get("valor"), str):
            raise MemoriaHechosInvalida(f"entrada inválida para '{clave}': faltan 'clave'/'valor'")
        validados[clave] = dict(entrada)
    legado = datos.get("legado_migrado") or []
    if not isinstance(legado, list) or not all(isinstance(h, str) for h in legado):
        raise MemoriaHechosInvalida("'legado_migrado' debe ser una lista de huellas")
    return {"hechos": validados, "legado_migrado": set(legado)}


def _validar_hechos(datos):
    return _validar_almacen(datos)["hechos"]


def _leer_almacen():
    """Lee y valida FACTS_PATH sin efectos secundarios."""
    if not os.path.exists(FACTS_PATH):
        return {"hechos": {}, "legado_migrado": set()}
    try:
        with open(FACTS_PATH, "r", encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise MemoriaHechosInvalida(f"YAML ilegible: {e}") from e
    except OSError as e:
        raise ErrorLecturaMemoria(str(e)) from e
    return _validar_almacen(datos)


def _leer_hechos():
    return _leer_almacen()["hechos"]


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


def guardar_hechos(hechos, legado_migrado=None):
    """Escritura atómica del almacén completo. Lanza OSError si no se puede
    escribir; en ese caso el fichero anterior queda intacto. Si no se indican,
    se conservan las huellas de migración ya guardadas (así olvidar un hecho
    heredado nunca permite reimportarlo)."""
    if legado_migrado is None:
        legado_migrado = _leer_almacen()["legado_migrado"]
    datos = {"version": VERSION_ESQUEMA, "hechos": hechos}
    if legado_migrado:
        datos["legado_migrado"] = sorted(legado_migrado)
    contenido = yaml.safe_dump(datos, allow_unicode=True, sort_keys=True)
    _escribir_atomico(FACTS_PATH, contenido, ".facts-")


# --------------------------------------------------------------------------- migración del perfil heredado
_SUFIJO_RESPALDO = ".legado-{ts}.bak"


def _hojas_perfil(datos):
    """[(ruta, valor_original)] de todas las hojas no vacías del perfil."""
    hojas = []

    def recorrer(valor, ruta):
        if isinstance(valor, dict):
            for k, v in valor.items():
                recorrer(v, ruta + [str(k)])
        elif valor is None or valor == "" or valor == [] or valor == {}:
            return
        else:
            hojas.append((ruta, valor))

    recorrer(datos, [])
    return hojas


def _aplanar_perfil(datos):
    """Convierte el perfil heredado (diccionarios anidados, listas, escalares)
    en una lista [(ruta, valor_str)] sin perder ninguna hoja."""
    return [(ruta, ", ".join(_texto_legado(v) for v in valor) if isinstance(valor, list) else _texto_legado(valor))
            for ruta, valor in _hojas_perfil(datos)]


def _huella(ruta, valor_str):
    """Identidad estable de una hoja del perfil (ruta + valor)."""
    return hashlib.sha256(("/".join(ruta) + "\0" + valor_str).encode("utf-8")).hexdigest()


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


_AVISOS_MOSTRADOS = set()


def _avisar_una_vez(clave, texto):
    """Evita repetir el mismo aviso en cada turno (la migración se reintenta a menudo)."""
    if clave not in _AVISOS_MOSTRADOS:
        _AVISOS_MOSTRADOS.add(clave)
        print(texto)


def _leer_perfil():
    """Perfil heredado como dict, o None si no existe / no se puede leer / no es un dict."""
    if not os.path.exists(MEMORY_PATH):
        return None
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            perfil = yaml.safe_load(f)
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        _avisar_una_vez(("perfil-ilegible", MEMORY_PATH),
                        f"[B.A.I] Aviso: no puedo leer el perfil heredado ({e}); lo dejo como está.")
        return None
    return perfil if isinstance(perfil, dict) else None


def _vaciar_perfil():
    _escribir_atomico(MEMORY_PATH, yaml.safe_dump({"aprendido_durante_sesion": {}}), ".perfil-")


def migrar_perfil_legado():
    """Mueve los datos de user_profile.yaml a facts.yaml.

    Cada hoja del perfil se identifica por una huella (ruta + valor) que se
    guarda en facts.yaml EN LA MISMA escritura atómica que los hechos. Así:
    - una hoja ya migrada nunca se vuelve a importar, aunque vaciar el perfil
      falle o el perfil se edite después (un hecho heredado olvidado no resucita);
    - si la escritura de hechos falla no se ha importado nada y el perfil sigue intacto.
    Orden: copia de respaldo del perfil -> hechos + huellas (atómico) -> perfil vaciado.
    Devuelve el número de hechos nuevos importados."""
    perfil = _leer_perfil()
    if not perfil:
        return 0
    hojas = _aplanar_perfil(perfil)
    if not hojas:
        return 0

    try:
        almacen = _leer_almacen()
    except (MemoriaHechosInvalida, ErrorLecturaMemoria) as e:
        _avisar_una_vez(("no-migro", MEMORY_PATH, FACTS_PATH),
                        f"[B.A.I] Aviso: no migro el perfil heredado porque la memoria de hechos no está disponible ({e}).")
        return 0
    hechos, migradas = dict(almacen["hechos"]), set(almacen["legado_migrado"])

    nombres = _nombres_legado(hojas)
    pendientes = [(ruta, valor, nombre) for (ruta, valor), (nombre, _) in zip(hojas, nombres)
                  if _huella(ruta, valor) not in migradas]
    if not pendientes:
        # Todo ya migrado: sólo falta (re)intentar vaciar el perfil. Nunca se reimporta nada.
        try:
            _vaciar_perfil()
        except OSError as e:
            _avisar_una_vez(("no-vacio", MEMORY_PATH),
                            f"[B.A.I] Aviso: no puedo vaciar el perfil ya migrado ({e}); se ignora, sus datos ya son hechos.")
        return 0

    importados = 0
    for ruta, valor, nombre in pendientes:
        migradas.add(_huella(ruta, valor))
        norma = normalizar_clave(nombre)
        if not norma:
            continue
        if norma in hechos and hechos[norma]["valor"].strip().lower() == valor.strip().lower():
            continue
        if norma in hechos:
            # Conflicto con un hecho ya guardado: se conserva el heredado aparte, sin sobreescribir.
            nombre = f"{clave_sin_articulo(nombre)} (perfil anterior)"
            norma = normalizar_clave(nombre)
            if norma in hechos:
                continue
        hechos[norma] = {"clave": clave_sin_articulo(nombre), "valor": valor,
                         "actualizado": _ahora(), "origen": "user_profile.yaml"}
        importados += 1

    respaldo = MEMORY_PATH + _SUFIJO_RESPALDO.format(ts=datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    try:
        shutil.copyfile(MEMORY_PATH, respaldo)
        guardar_hechos(hechos, migradas)          # hechos + huellas: todo o nada
    except OSError as e:
        _avisar_una_vez(("no-migrado", MEMORY_PATH),
                        f"[B.A.I] Aviso: no he podido migrar el perfil heredado ({e}); no se ha importado nada "
                        f"y el perfil sigue intacto en {MEMORY_PATH}.")
        return 0
    print(f"[B.A.I] Memoria heredada migrada: {importados} dato(s) de user_profile.yaml ahora son hechos "
          f"(consultables, editables y olvidables). Copia del perfil original: {respaldo}")
    try:
        _vaciar_perfil()
    except OSError as e:
        _avisar_una_vez(("no-vacio", MEMORY_PATH),
                        f"[B.A.I] Aviso: no he podido vaciar el perfil tras migrarlo ({e}); sus datos no se "
                        f"reimportarán ni se inyectarán dos veces, y se reintentará más tarde.")
    return importados


def huellas_migradas():
    """Huellas de las hojas del perfil ya migradas (None si el almacén no se puede leer)."""
    try:
        return _leer_almacen()["legado_migrado"]
    except (MemoriaHechosInvalida, ErrorLecturaMemoria):
        return None


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def aplicar_cambios(cambios):
    """Aplica varios cambios en UNA sola escritura atómica (todo o nada).

    `cambios`: lista de (modo, clave, valor) con modo 'recordar' (no
    sobreescribe: 'guardado' | 'duplicado' | 'conflicto') o 'actualizar'
    ('actualizado' | 'creado'). Devuelve [(estado, clave_visible, valor, anterior)].
    Si la escritura falla lanza OSError y NINGÚN cambio queda guardado."""
    hechos = dict(cargar_hechos())
    resultados, cambiado = [], False
    for modo, clave, valor in cambios:
        valor = limpiar_valor(valor)
        norma = normalizar_clave(clave)
        existente = hechos.get(norma)
        if modo == "recordar":
            if existente is not None:
                igual = existente["valor"].strip().lower() == valor.strip().lower()
                resultados.append(("duplicado" if igual else "conflicto", existente["clave"], valor, existente["valor"]))
                continue
            hechos[norma] = {"clave": clave_sin_articulo(clave), "valor": valor, "actualizado": _ahora()}
            resultados.append(("guardado", hechos[norma]["clave"], valor, None))
        else:
            visible = existente["clave"] if existente else clave_sin_articulo(clave)
            hechos[norma] = {"clave": visible, "valor": valor, "actualizado": _ahora()}
            resultados.append(("actualizado" if existente else "creado", visible, valor,
                               existente["valor"] if existente else None))
        cambiado = True
    if cambiado:
        guardar_hechos(hechos)
    return resultados


def recordar_hecho(clave, valor):
    """Guarda un hecho nuevo. Devuelve ('guardado', None) | ('duplicado', valor)
    | ('conflicto', valor_existente). En caso de conflicto NO sobreescribe.
    Sólo devuelve 'guardado' si la escritura en disco ha terminado bien."""
    estado, _, _, anterior = aplicar_cambios([("recordar", clave, valor)])[0]
    return estado, anterior


def clave_sin_articulo(clave):
    """Versión legible de la clave sin el artículo/posesivo inicial (conserva acentos)."""
    c = limpiar_valor(clave).strip("¿?¡!,;:").strip()
    palabras = c.split()
    while len(palabras) > 1 and _sin_acentos(palabras[0]).lower() in _ARTICULOS:
        palabras = palabras[1:]
    return " ".join(palabras)


def actualizar_hecho(clave, valor):
    """Crea o reemplaza el valor de un hecho (operación explícita de actualización).
    Devuelve ('actualizado', valor_anterior) o ('creado', None)."""
    estado, _, _, anterior = aplicar_cambios([("actualizar", clave, valor)])[0]
    return estado, anterior


def obtener_hecho(clave):
    """(clave_visible, valor) o None. Sólo lectura."""
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
    pertenecen al MISMO propietario (la propiedad ajena nunca se mezcla)."""
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
    """Elimina un hecho. Devuelve el valor olvidado o None si no existía.
    Sólo devuelve un valor tras persistir el borrado sin errores."""
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

# Si historial.json está dañado o es ilegible y NO se ha podido apartar, queda
# protegido: los guardados de esta sesión van a un fichero de rescate (que el
# siguiente arranque consolida) y nunca sobreescriben el original.
_HISTORIAL_PROTEGIDO = {}   # ruta protegida -> ruta de rescate


def _destino_historial():
    return _HISTORIAL_PROTEGIDO.get(SESSION_FILE, SESSION_FILE)


def save_chat_history(history):
    """Guarda el historial de forma atómica. Devuelve True si se ha escrito;
    si falla avisa y devuelve False (la copia anterior en disco queda intacta).
    Nunca sobreescribe un historial dañado que no se haya podido apartar."""
    try:
        contenido = json.dumps(history, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        print(f"[B.A.I] Aviso: no puedo serializar el historial ({e}); no lo guardo.")
        return False
    try:
        _escribir_atomico(_destino_historial(), contenido, ".historial-")
        return True
    except OSError as e:
        print(f"[B.A.I] Aviso: no he podido guardar el historial ({e}).")
        return False


def _proteger_historial(motivo):
    """historial.json no se puede leer ni apartar: se deja intacto y esta sesión
    guarda en un fichero de rescate *.json que el próximo arranque consolidará."""
    rescate = os.path.join(HISTORY_DIR, f"historial-rescate-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json")
    _HISTORIAL_PROTEGIDO[SESSION_FILE] = rescate
    print(f"[B.A.I] Aviso: {motivo}; no tocaré {SESSION_FILE}. Esta sesión se guardará en {rescate}.")


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
    respaldo = f"{path}.corrupto-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.bak"
    try:
        os.replace(path, respaldo)
        print(f"[B.A.I] Aviso: historial ilegible ({motivo}); conservado en {respaldo}. Empiezo uno nuevo.")
        return True
    except OSError as e:
        _proteger_historial(f"historial ilegible ({motivo}) y no puedo apartarlo ({e})")
        return False


def load_full_history():
    messages = []
    archivos_a_borrar = []
    reescribir = True   # sólo se reescribe historial.json si se ha podido leer (o apartar) sin pérdida
    _HISTORIAL_PROTEGIDO.pop(SESSION_FILE, None)

    os.makedirs(HISTORY_DIR, exist_ok=True)

    # Cargar historial activo si existe
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                messages.extend(_turnos_validos(json.load(f)))
        except (ValueError, UnicodeDecodeError) as e:       # JSON roto o estructura inesperada
            reescribir = _apartar_corrupto(SESSION_FILE, e)
        except OSError as e:                                  # no se puede leer: no se toca
            _proteger_historial(f"no puedo leer el historial ({e})")
            reescribir = False

    # Cargar sesiones anteriores y de rescate (los ficheros ilegibles se conservan sin tocar)
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
    """Texto con los datos del perfil (user_profile.yaml) que AÚN no se han
    migrado a hechos. Nunca lanza: un perfil ausente o dañado no debe impedir
    conversar. Las hojas ya migradas no se inyectan (si se olvidaron como
    hecho, no deben volver a llegar al motor por esta vía)."""
    perfil = _leer_perfil()
    if not perfil:
        return []
    migradas = huellas_migradas()
    if migradas is None:
        migradas = set()      # almacén ilegible: no se puede migrar ni olvidar, el perfil sigue visible
    texto = []
    for ruta, valor in _hojas_perfil(perfil):
        valor_str = ", ".join(_texto_legado(v) for v in valor) if isinstance(valor, list) else _texto_legado(valor)
        if _huella(ruta, valor_str) in migradas:
            continue
        nombre = str(ruta[-1]).capitalize()
        if isinstance(valor, list):
            texto.append(f"{nombre} incluye: {valor_str}.")
        else:
            texto.append(f"{nombre} es {valor_str}.")
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