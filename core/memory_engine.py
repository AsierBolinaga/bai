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
import stat
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
_MODO_DIR_PRIVADO = 0o700   # directorios de datos personales: sólo el usuario


def _crear_directorio_privado(ruta):
    """Crea `ruta` y los niveles que falten como 0700, sin tocar el umask del
    proceso ni los permisos de los directorios que ya existen (p. ej. el
    directorio del proyecto o config/). Lanza OSError si no se puede crear."""
    pendientes = []
    actual = os.path.abspath(ruta)
    while not os.path.isdir(actual):
        pendientes.append(actual)
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre
    for nivel in reversed(pendientes):
        try:
            os.mkdir(nivel, _MODO_DIR_PRIVADO)
        except FileExistsError:
            continue
        os.chmod(nivel, _MODO_DIR_PRIVADO)   # el umask no debe recortar lo que el usuario necesita


def _es_directorio_privado(directorio):
    """True si `directorio` es el de historial (o está dentro de él)."""
    base = os.path.abspath(HISTORY_DIR)
    d = os.path.abspath(directorio)
    return d == base or d.startswith(base + os.sep)


_crear_directorio_privado(HISTORY_DIR)


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
# Marcadores de migración del perfil heredado: 'perfil_migrado' (nombre canónico,
# también usado por almacenes anteriores) y 'legado_migrado' (alias). Contienen
# huellas: de cada hoja migrada (ruta + valor) o del perfil completo.
_CLAVES_MARCADOR = ("perfil_migrado", "legado_migrado")
_CLAVES_RAIZ = {"version", "hechos", *_CLAVES_MARCADOR}
_CLAVES_ENTRADA = {"clave", "valor", "actualizado", "origen"}


# Marcador presente pero sin contenido interpretable (vacío o nulo): no lo escribe
# ninguna versión propia, así que se conserva como marcador ajeno (incertidumbre).
_MARCADOR_VACIO = "ajeno:vacio"


def _huellas_de_marcador(nombre, valor, presente):
    """Huellas de un marcador de migración, de forma conservadora:
    - lista de cadenas / una cadena: todas cuentan (las que no sean huellas
      propias bien formadas se tratarán como de otra versión -> incertidumbre);
    - diccionario: se conservan TODOS sus valores de texto (o listas de texto),
      conocidos o no; nunca se descartan (descartarlos dejaría el marcador vacío
      y permitiría reimportar datos ya olvidados);
    - marcador presente pero vacío o nulo: marcador ajeno sin contenido;
    - cualquier otra forma (números, anidamientos...): esquema inválido."""
    if not presente:
        return set()
    if valor is None or valor == "" or valor == [] or valor == {}:
        return {_MARCADOR_VACIO}
    if isinstance(valor, str):
        return {valor}
    if isinstance(valor, list) and all(isinstance(h, str) for h in valor):
        return set(valor)
    if isinstance(valor, dict):
        huellas = set()
        for v in valor.values():
            if isinstance(v, str):
                huellas.add(v)
            elif isinstance(v, list) and all(isinstance(h, str) for h in v):
                huellas.update(v)
            else:
                raise MemoriaHechosInvalida(f"'{nombre}' debe contener huellas (cadenas)")
        return huellas or {_MARCADOR_VACIO}
    raise MemoriaHechosInvalida(f"'{nombre}' debe ser una lista de huellas")


def _validar_almacen(datos):
    """Valida el esquema completo. Un fichero vacío es un almacén vacío; todo lo
    demás debe ser {version: 1, hechos: {norma: {clave, valor, ...}}} más, de
    forma opcional, los marcadores de migración perfil_migrado / legado_migrado.
    Devuelve {"hechos": dict, "perfil_migrado": set}."""
    if datos is None:
        return {"hechos": {}, "perfil_migrado": set()}
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
    # 'legado_migrado' (alias) siempre contuvo huellas por hoja: se etiquetan como tales.
    marcadores = {h if ":" in h else "hoja:" + h
                  for h in _huellas_de_marcador("legado_migrado", datos.get("legado_migrado"), "legado_migrado" in datos)}
    marcadores |= _huellas_de_marcador("perfil_migrado", datos.get("perfil_migrado"), "perfil_migrado" in datos)
    return {"hechos": validados, "perfil_migrado": marcadores}


def _validar_hechos(datos):
    return _validar_almacen(datos)["hechos"]


def _leer_almacen():
    """Lee y valida FACTS_PATH sin efectos secundarios."""
    try:
        with open(FACTS_PATH, "r", encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except FileNotFoundError:
        return {"hechos": {}, "perfil_migrado": set()}
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise MemoriaHechosInvalida(f"YAML ilegible: {e}") from e
    except OSError as e:          # existe pero no se puede leer: nunca se trata como vacío
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


_MODO_PRIVADO = 0o600   # datos personales: sólo el usuario (sin tocar el umask del proceso)


def _modo_para(ruta):
    """Permisos con los que debe quedar `ruta` tras escribirla: los que ya tenía
    (nunca se amplían) o 0600 si es nueva o no se pueden determinar."""
    try:
        return stat.S_IMODE(os.stat(ruta).st_mode) & 0o777
    except OSError:
        return _MODO_PRIVADO


def _escribir_atomico(ruta, contenido, prefijo):
    """Escribe `contenido` en `ruta` vía fichero temporal + os.replace.
    Lanza OSError si falla; el fichero anterior queda intacto. El temporal nace
    0600 (mkstemp) y se deja con los permisos previos del fichero, o 0600 si es nuevo."""
    directorio = os.path.dirname(ruta) or "."
    if _es_directorio_privado(directorio):
        _crear_directorio_privado(directorio)        # historial, rescates, manifiestos
    else:
        os.makedirs(directorio, exist_ok=True)       # config/data: directorio compartido, permisos habituales
    fd, temporal = tempfile.mkstemp(dir=directorio, prefix=prefijo, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
        os.chmod(temporal, _modo_para(ruta))
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def guardar_hechos(hechos, perfil_migrado=None):
    """Escritura atómica del almacén completo. Lanza OSError si no se puede
    escribir; en ese caso el fichero anterior queda intacto. Si no se indican,
    se conservan las huellas de migración ya guardadas (así olvidar un hecho
    heredado nunca permite reimportarlo). Los marcadores se escriben siempre
    bajo 'perfil_migrado' (los alias leídos se consolidan ahí)."""
    if perfil_migrado is None:
        perfil_migrado = _leer_almacen()["perfil_migrado"]
    datos = {"version": VERSION_ESQUEMA, "hechos": hechos}
    if perfil_migrado:
        datos["perfil_migrado"] = sorted(perfil_migrado)
    contenido = yaml.safe_dump(datos, allow_unicode=True, sort_keys=True)
    _escribir_atomico(FACTS_PATH, contenido, ".facts-")
    # Verificación tras escribir: sólo se confirma lo que realmente ha quedado en disco.
    try:
        leido = _leer_almacen()
    except (MemoriaHechosInvalida, ErrorLecturaMemoria) as e:
        raise OSError(f"verificación tras escribir fallida: {e}") from e
    if leido["hechos"] != hechos or leido["perfil_migrado"] != set(perfil_migrado):
        raise OSError("verificación tras escribir fallida: el contenido leído no coincide con lo escrito")


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


def _texto_legado(valor):
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    return str(valor)


def _huella(ruta, valor_str):
    """Identidad estable de una hoja del perfil (ruta + valor)."""
    return "hoja:" + hashlib.sha256(("/".join(ruta) + "\0" + valor_str).encode("utf-8")).hexdigest()


def _huella_perfil(texto):
    """Identidad del perfil completo tal y como está en disco."""
    return "perfil:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _huellas_perfil_completo(texto, perfil):
    """Huellas (sin etiqueta) con las que otras versiones pudieron marcar el perfil ENTERO."""
    formas = [texto, texto.strip(),
              yaml.safe_dump(perfil, allow_unicode=True, sort_keys=True),
              yaml.safe_dump(perfil, sort_keys=True), yaml.safe_dump(perfil)]
    huellas = set()
    for forma in formas:
        for algoritmo in ("sha256", "sha1", "md5"):
            huellas.add(hashlib.new(algoritmo, forma.encode("utf-8")).hexdigest())
    return huellas


_RE_MARCADOR_PROPIO = re.compile(r"^(?:hoja|perfil):[0-9a-f]{64}$")


def _marcadores_ajenos(marcadores):
    """Marcadores que no son huellas propias bien formadas ('hoja:'/'perfil:' +
    sha256). Cualquier otra cosa —con o sin ':'— se considera de otra versión."""
    return {m for m in marcadores if not _RE_MARCADOR_PROPIO.match(m)}


def _ya_guardada(nombre, valor, hechos):
    """True si este valor heredado ya está en los hechos (con su nombre o como
    'X (perfil anterior N)'): entonces no hay nada que conciliar."""
    valor = valor.strip().lower()
    base = normalizar_clave(nombre)
    if base in hechos and hechos[base]["valor"].strip().lower() == valor:
        return True
    prefijo = normalizar_clave(f"{clave_sin_articulo(nombre)} (perfil anterior")
    return any(norma.startswith(prefijo) and e["valor"].strip().lower() == valor for norma, e in hechos.items())


def _clasificar_hojas(texto, perfil, hojas, marcadores, hechos):
    """Clasifica las hojas del perfil según los marcadores del almacén.

    Devuelve (migradas, inciertas, reconocidos, motivo):
    - migradas: índices ya importados con certeza: huella 'hoja:' propia, huella
      'perfil:' propia, o marcador ajeno que coincide con el perfil completo
      tal y como está (entonces TODAS), o valor ya presente en los hechos;
    - inciertas: sólo cuando hay marcadores que no son huellas propias bien
      formadas (con o sin ':') y no identifican este perfil: hojas que podrían
      ser hechos ya migrados y luego olvidados.
      No se importan, no se inyectan y el perfil no se toca: quedan pendientes
      de conciliación (el usuario decide con 'recuerda que X es Y');
    - reconocidos: marcadores ajenos identificados (pueden sustituirse por
      huellas propias sin perder información)."""
    todas = set(range(len(hojas)))
    if not marcadores:
        return set(), set(), set(), None
    ajenos = _marcadores_ajenos(marcadores)
    reconocidos = ajenos & _huellas_perfil_completo(texto, perfil)   # identifica ESTE perfil: certeza
    if _huella_perfil(texto) in marcadores or reconocidos:
        return todas, set(), reconocidos, "perfil completo"
    migradas = {i for i, (ruta, valor) in enumerate(hojas) if _huella(ruta, valor) in marcadores}
    if not ajenos:
        return migradas, set(), set(), ("hojas" if migradas else None)
    nombres = _nombres_legado(hojas)
    migradas |= {i for i in todas - migradas if _ya_guardada(nombres[i][0], hojas[i][1], hechos)}
    inciertas = todas - migradas
    return migradas, inciertas, set(), ("marcador no reconocido" if inciertas else "hojas")


def _leer_perfil_texto():
    """(texto, dict) del perfil heredado, o (None, None) si no existe / no es legible / no es un dict."""
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            texto = f.read()
        perfil = yaml.safe_load(texto)
    except FileNotFoundError:
        return None, None
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        _avisar_una_vez(("perfil-ilegible", MEMORY_PATH),
                        f"[B.A.I] Aviso: no puedo leer el perfil heredado ({e}); lo dejo como está.")
        return None, None
    return (texto, perfil) if isinstance(perfil, dict) else (None, None)


def _clave_libre(nombre, hechos, valor):
    """Clave para un valor heredado que choca con un hecho ya guardado: se conserva
    aparte ('X (perfil anterior)', 'X (perfil anterior 2)', ...), nunca se descarta.
    Devuelve None si ese mismo valor ya está guardado bajo alguna de esas claves."""
    base = clave_sin_articulo(nombre)
    n = 1
    while True:
        candidata = f"{base} (perfil anterior)" if n == 1 else f"{base} (perfil anterior {n})"
        norma = normalizar_clave(candidata)
        if norma not in hechos:
            return candidata
        if hechos[norma]["valor"].strip().lower() == valor.strip().lower():
            return None
        n += 1


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
    return _leer_perfil_texto()[1]


def _vaciar_perfil():
    _escribir_atomico(MEMORY_PATH, yaml.safe_dump({"aprendido_durante_sesion": {}}), ".perfil-")


def migrar_perfil_legado():
    """Mueve los datos de user_profile.yaml a facts.yaml.

    Cada hoja del perfil se identifica por una huella (ruta + valor) que se
    guarda en facts.yaml EN LA MISMA escritura atómica que los hechos. Así:
    - una hoja ya migrada nunca se vuelve a importar, aunque vaciar el perfil
      falle o el perfil se edite después (un hecho heredado olvidado no resucita);
    - los almacenes marcados por versiones anteriores se respetan: si el
      marcador identifica este perfil, se considera migrado; si no se puede
      interpretar, las hojas que no estén ya en los hechos quedan PENDIENTES
      de conciliación (ni se importan, ni se inyectan, ni se borra el perfil);
    - si la escritura de hechos falla no se ha importado nada y el perfil sigue intacto;
    - un valor heredado cuya clave choca con un hecho distinto se guarda aparte
      ('X (perfil anterior)'), nunca se descarta.
    Orden: copia de respaldo del perfil -> hechos + huellas (atómico) -> perfil vaciado.
    Devuelve el número de hechos nuevos importados."""
    texto, perfil = _leer_perfil_texto()
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
    hechos, migradas = dict(almacen["hechos"]), set(almacen["perfil_migrado"])

    ya_migradas, inciertas, reconocidos, motivo = _clasificar_hojas(texto, perfil, hojas, migradas, hechos)
    nombres = _nombres_legado(hojas)
    pendientes = [(ruta, valor, nombre) for i, ((ruta, valor), (nombre, _)) in enumerate(zip(hojas, nombres))
                  if i not in ya_migradas and i not in inciertas]
    huellas_nuevas = {_huella(ruta, valor) for i, (ruta, valor) in enumerate(hojas) if i in ya_migradas} - migradas
    if reconocidos:
        # Un marcador ajeno que identifica ESTE perfil se sustituye por huellas propias
        # (sólo ese: los que no se reconocen se conservan tal cual).
        huellas_nuevas.add(_huella_perfil(texto))
        migradas -= reconocidos
        _avisar_una_vez(("marcado", MEMORY_PATH, _huella_perfil(texto)),
                        f"[B.A.I] El perfil heredado ya está marcado como migrado ({motivo}): no reimporto sus "
                        f"{len(hojas)} dato(s); sus hechos siguen en la memoria y el perfil se conserva en copia.")
    if inciertas:
        claves = ", ".join(f"'{nombres[i][0]}'" for i in sorted(inciertas))
        _avisar_una_vez(("inciertas", MEMORY_PATH, _huella_perfil(texto)),
                        f"[B.A.I] Aviso: {len(inciertas)} dato(s) de user_profile.yaml están pendientes de conciliar "
                        f"({claves}). La memoria tiene una marca de migración de otra versión que no sé interpretar, "
                        f"así que podrían ser hechos que ya migraste y después olvidaste. No los importo ni los uso "
                        f"como contexto, y dejo user_profile.yaml intacto. Si quieres conservar alguno, dímelo con "
                        f"'recuerda que <clave> es <valor>'.")

    if not pendientes:
        # Nada nuevo con certeza: sólo anotar huellas que faltaran y, si no queda nada
        # pendiente de conciliar, (re)intentar vaciar el perfil.
        if inciertas:
            return 0               # con datos pendientes de conciliar no se toca ni el perfil ni el almacén
        if huellas_nuevas:
            try:
                _respaldar_perfil(texto)
                guardar_hechos(hechos, migradas | huellas_nuevas)
            except OSError as e:
                _avisar_una_vez(("no-huellas", FACTS_PATH),
                                f"[B.A.I] Aviso: no he podido anotar las huellas de migración ({e}); no se reimporta nada.")
                return 0
        _vaciar_perfil_con_respaldo(texto, solo_si_hace_falta=True)
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
            # Conflicto con un hecho ya guardado: se conserva el heredado aparte, sin sobreescribir ni descartar.
            nombre = _clave_libre(nombre, hechos, valor)
            if nombre is None:
                continue
            norma = normalizar_clave(nombre)
        hechos[norma] = {"clave": clave_sin_articulo(nombre), "valor": valor,
                         "actualizado": _ahora(), "origen": "user_profile.yaml"}
        importados += 1

    try:
        respaldo = _respaldar_perfil(texto)
        guardar_hechos(hechos, migradas | huellas_nuevas)          # hechos + huellas: todo o nada
    except OSError as e:
        _avisar_una_vez(("no-migrado", MEMORY_PATH),
                        f"[B.A.I] Aviso: no he podido migrar el perfil heredado ({e}); no se ha importado nada "
                        f"y el perfil sigue intacto en {MEMORY_PATH}.")
        return 0
    print(f"[B.A.I] Memoria heredada migrada: {importados} dato(s) de user_profile.yaml ahora son hechos "
          f"(consultables, editables y olvidables). Copia del perfil original: {respaldo}")
    if inciertas:
        return importados          # el perfil se conserva: aún tiene datos pendientes de conciliar
    try:
        _vaciar_perfil()
    except OSError as e:
        _avisar_una_vez(("no-vacio", MEMORY_PATH),
                        f"[B.A.I] Aviso: no he podido vaciar el perfil tras migrarlo ({e}); sus datos no se "
                        f"reimportarán ni se inyectarán dos veces, y se reintentará más tarde.")
    return importados


def _respaldar_perfil(texto):
    """Copia de seguridad del perfil antes de tocarlo. Si ya existe una copia
    con exactamente este contenido (de este u otro proceso) se reutiliza, así
    un fallo persistente no genera una copia por turno ni por sesión.
    Devuelve la ruta de la copia. Lanza OSError si no se puede copiar."""
    directorio = os.path.dirname(MEMORY_PATH) or "."
    base = os.path.basename(MEMORY_PATH)
    datos = texto.encode("utf-8")
    try:
        for nombre in sorted(os.listdir(directorio)):
            if nombre.startswith(base + ".legado-") and nombre.endswith(".bak"):
                ruta = os.path.join(directorio, nombre)
                with open(ruta, "rb") as f:
                    if f.read() == datos:
                        return ruta
    except OSError:
        pass
    respaldo = MEMORY_PATH + _SUFIJO_RESPALDO.format(ts=datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    _copiar_privado(MEMORY_PATH, respaldo)
    return respaldo


def _copiar_privado(origen, destino):
    """Copia de seguridad creada como 0600 desde el principio (sin pasar por el umask)."""
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _MODO_PRIVADO)
    try:
        with open(origen, "rb") as f, os.fdopen(fd, "wb") as g:
            shutil.copyfileobj(f, g)
    except BaseException:
        try:
            os.unlink(destino)
        except OSError:
            pass
        raise


def _vaciar_perfil_con_respaldo(texto, solo_si_hace_falta=False):
    """Vacía un perfil cuyo contenido ya está migrado, conservando antes una copia."""
    if solo_si_hace_falta and not texto.strip():
        return
    try:
        _respaldar_perfil(texto)
        _vaciar_perfil()
    except OSError as e:
        _avisar_una_vez(("no-vacio", MEMORY_PATH),
                        f"[B.A.I] Aviso: no puedo vaciar el perfil ya migrado ({e}); se ignora, sus datos ya son hechos.")


def huellas_migradas():
    """Marcadores de migración del almacén (None si no se puede leer)."""
    try:
        return _leer_almacen()["perfil_migrado"]
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


_SUFIJO_MANIFIESTO = ".absorbidos"   # no termina en .json: nunca se carga como sesión


def _leer_manifiesto(destino):
    """{nombre_fichero: sha256} de lo que `destino` ya contiene. {} si no hay o es ilegible."""
    ruta = destino + _SUFIJO_MANIFIESTO
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"[B.A.I] Aviso: no puedo leer {ruta} ({e}); lo ignoro.")
        return {}
    if not isinstance(datos, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in datos.items()):
        print(f"[B.A.I] Aviso: {ruta} tiene un formato inesperado; lo ignoro.")
        return {}
    return datos


def load_full_history():
    """Carga y consolida el historial de forma idempotente.

    Se leen historial.json y los *.json del directorio (sesiones antiguas y de
    rescate), se escribe todo en el destino de esta sesión y después se borran
    los ficheros absorbidos. Si alguno no se puede borrar, queda anotado (por
    nombre y huella de contenido) en el manifiesto '<destino>.absorbidos', y
    los arranques siguientes lo saltan mientras su contenido siga contenido en
    un destino que se haya podido leer. Así ni un historial dañado que no se
    puede apartar ni un borrado que falla duplican sesiones."""
    messages = []
    _HISTORIAL_PROTEGIDO.pop(SESSION_FILE, None)

    _crear_directorio_privado(HISTORY_DIR)

    absorbidos = {}   # nombre -> huella de lo que algún destino leído ya contiene
    # Cargar historial activo si existe
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            messages.extend(_turnos_validos(json.load(f)))
        absorbidos.update(_leer_manifiesto(SESSION_FILE))       # sólo si el principal se ha podido leer
    except FileNotFoundError:
        pass
    except (ValueError, UnicodeDecodeError) as e:           # JSON roto o estructura inesperada
        _apartar_corrupto(SESSION_FILE, e)                    # si no se puede apartar, queda protegido
    except OSError as e:                                      # existe pero no se puede leer: no se toca
        _proteger_historial(f"no puedo leer el historial ({e})")

    # Leer sesiones anteriores y de rescate (los ficheros ilegibles se conservan sin tocar)
    leidos = []   # (ruta, nombre, huella, turnos)
    for file in sorted(os.listdir(HISTORY_DIR)):
        if file.endswith(".json") and file != os.path.basename(SESSION_FILE):
            path = os.path.join(HISTORY_DIR, file)
            try:
                with open(path, "rb") as f:
                    bruto = f.read()
                turnos = _turnos_validos(json.loads(bruto.decode("utf-8")))
            except Exception as e:
                print(f"[B.A.I] Error cargando {file}: {e}")
                continue
            leidos.append((path, file, hashlib.sha256(bruto).hexdigest(), turnos))
            absorbidos.update(_leer_manifiesto(path))

    for path, nombre, huella, turnos in leidos:
        if absorbidos.get(nombre) != huella:          # ya contenido en un destino leído: no se repite
            messages.extend(turnos)

    messages = messages[-MAX_MESSAGES:]

    # Consolidación: todo lo cargado se escribe en el destino de esta sesión
    # (historial.json o, si está protegido, su fichero de rescate) y sólo
    # entonces se borran los ficheros ya absorbidos.
    if not save_chat_history(messages):
        return messages   # no se borran las sesiones antiguas si no se ha podido consolidar

    destino = _destino_historial()
    pendientes = {}
    for path, nombre, huella, _ in leidos:
        try:
            os.remove(path)
        except Exception as e:
            print(f"[B.A.I] Error borrando {path}: {e}")
            pendientes[nombre] = huella
            continue
        try:
            if os.path.exists(path + _SUFIJO_MANIFIESTO):
                os.remove(path + _SUFIJO_MANIFIESTO)
        except OSError:
            pass   # un manifiesto huérfano se ignora: sólo cuentan los de destinos leídos
    manifiesto = destino + _SUFIJO_MANIFIESTO
    try:
        if pendientes:
            _escribir_atomico(manifiesto, json.dumps(pendientes, indent=2, sort_keys=True), ".absorbidos-")
        elif os.path.exists(manifiesto):
            os.remove(manifiesto)
    except OSError as e:
        print(f"[B.A.I] Aviso: no he podido anotar los ficheros ya absorbidos ({e}); "
              f"podrían volver a cargarse si tampoco se pueden borrar.")

    return messages


def _contexto_perfil():
    """Texto con los datos del perfil (user_profile.yaml) que AÚN no se han
    migrado a hechos. Nunca lanza: un perfil ausente o dañado no debe impedir
    conversar. Ni las hojas ya migradas ni las pendientes de conciliación se
    inyectan: si se olvidaron como hecho, no deben volver a llegar al motor."""
    texto_perfil, perfil = _leer_perfil_texto()
    if not perfil:
        return []
    hojas = _hojas_perfil(perfil)
    migradas = huellas_migradas()
    if migradas is None:
        ya = set()            # almacén ilegible: no se puede migrar ni olvidar, el perfil sigue visible
    else:
        planas = [(ruta, ", ".join(_texto_legado(v) for v in valor) if isinstance(valor, list) else _texto_legado(valor))
                  for ruta, valor in hojas]
        try:
            hechos = _leer_hechos()
        except (MemoriaHechosInvalida, ErrorLecturaMemoria):
            hechos = {}
        migradas_idx, inciertas, _, _ = _clasificar_hojas(texto_perfil, perfil, planas, migradas, hechos)
        ya = migradas_idx | inciertas     # lo incierto podría estar olvidado: nunca se inyecta
    texto = []
    for i, (ruta, valor) in enumerate(hojas):
        if i in ya:
            continue
        valor_str = ", ".join(_texto_legado(v) for v in valor) if isinstance(valor, list) else _texto_legado(valor)
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