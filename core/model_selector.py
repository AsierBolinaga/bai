"""
Selección de motor/modelo según el modo de trabajo (online / offline).

Flujo de `ModelSelector.responder(messages)`:

    modo actual ──► candidatos(modo) ──► para cada candidato, en orden:
                                           1. ¿registrado e implementado?
                                           2. ¿tipo coherente con la sección? (un motor
                                              online nunca se ejecuta como offline)
                                           3. ¿disponible? (librería, modelo, API key)
                                           4. ¿conectividad? (sólo motores online)
                                           5. responder(messages recortados, config)
                                         ──► primera respuesta válida
                                         ──► si ninguno responde: SinMotorDisponible

Política de modos
-----------------
offline : SÓLO motores locales. Mientras el modo es offline hay una GuardiaRed
          de sesión activa (y otra alrededor de cada llamada a un motor offline),
          que bloquea conexiones/DNS externos del código Python sea cual sea la
          configuración del motor. Si B.A.I arrancó con aislamiento de proceso
          (core/aislamiento.py) la garantía la da el kernel y el modo online no
          es posible en esta sesión (set_modo lanza AislamientoActivo). Nunca se
          pasa a online automáticamente: eso requiere una orden explícita del
          usuario ("pasa a modo online" / `python bai.py --online`).
online  : el usuario ha autorizado el uso de servicios externos. El orden lo fija
          `online.prioridad`:
            local  (por defecto): motores locales primero; el motor online sólo
                   se usa cuando ningún motor local está disponible o responde.
            online: motor online primero; motores locales como respaldo si
                   `online.fallback_offline` es true.
          Degradar de online a local nunca requiere autorización (es más privado).

Orden de candidatos:
    offline                    : offline.motor, *offline.fallback
    online / prioridad local   : offline.motor, *offline.fallback, online.motor, *online.fallback
    online / prioridad online  : online.motor, *online.fallback, [+ offline si fallback_offline]

El selector no conoce los detalles de ningún motor: sólo usa el contrato
definido en core/motors/base.py y el registro de core/motors/registry.py.
"""
import os
import socket
from dataclasses import dataclass, field

from config.motors_config import MODOS_VALIDOS, PRIORIDADES_VALIDAS, cargar_motors_config
from core.motors import registry
from core.motors.base import MotorError, MotorNoDisponible, recortar_mensajes
from core import aislamiento
from core.network_guard import GuardiaRed


class AislamientoActivo(RuntimeError):
    """El proceso está aislado de la red: el modo online no es posible en esta sesión."""


class SinMotorDisponible(MotorError):
    """Ningún motor candidato ha podido responder en el modo solicitado."""

    def __init__(self, modo, errores):
        self.modo = modo
        self.errores = list(errores)
        detalle = "; ".join(f"{m}: {e}" for m, e in self.errores) or "sin candidatos"
        super().__init__(f"Ningún motor disponible en modo {modo} ({detalle})")


@dataclass
class Candidato:
    nombre: str
    tipo: str            # "online" | "offline"
    config: dict
    max_mensajes: int | None = None

    @property
    def modelo(self):
        """Nombre legible del modelo: 'modelo' o, si no, el fichero de 'model_path'."""
        if self.config.get("modelo"):
            return str(self.config["modelo"])
        if self.config.get("model_path"):
            return os.path.basename(str(self.config["model_path"]).rstrip("/\\")) or str(self.config["model_path"])
        return "?"


@dataclass
class RespuestaMotor:
    texto: str
    motor: str
    modelo: str
    tipo: str            # tipo del motor que respondió
    modo: str            # modo de trabajo activo al responder
    fallback_usado: bool = False
    errores: list = field(default_factory=list)  # [(motor, motivo), ...] de los candidatos descartados


def hay_conexion(host="api.openai.com", port=443, timeout=3):
    """Comprobación de conectividad TCP básica."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class ModelSelector:
    """
    Mantiene el modo de trabajo actual y elige el motor/modelo adecuado.

    Parámetros:
        config            : configuración normalizada (ver config.motors_config).
                            Si es None se carga motors_config.yaml.
        comprobar_conexion: callable(host) -> bool. Inyectable para tests.
        obtener_motor     : callable(nombre) -> módulo motor. Inyectable para tests.
    """

    def __init__(self, config=None, comprobar_conexion=None, obtener_motor=None):
        self.config = config if config is not None else cargar_motors_config()
        self._comprobar_conexion = comprobar_conexion or hay_conexion
        self._obtener_motor = obtener_motor or registry.obtener_motor
        self._modo = self.config["modo_por_defecto"]
        self._guardia_sesion = None
        self._aplicar_guardia_sesion()

    # ------------------------------------------------------------------ modo
    @property
    def modo(self):
        return self._modo

    def set_modo(self, modo):
        modo = str(modo).lower().strip()
        if modo not in MODOS_VALIDOS:
            raise ValueError(f"Modo desconocido: {modo!r}. Válidos: {MODOS_VALIDOS}")
        if modo == "online" and aislamiento.en_namespace_aislado():
            raise AislamientoActivo(
                "Esta sesión está aislada de la red a nivel de proceso: el modo online no es posible. "
                "Para autorizar servicios online reinicia B.A.I con `python bai.py --online`.")
        self._modo = modo
        self._aplicar_guardia_sesion()
        return self._modo

    # ---------------------------------------------------------- aislamiento
    def _aplicar_guardia_sesion(self):
        """Guardia Python de sesión: activa mientras el modo sea offline."""
        if self._modo == "offline":
            if self._guardia_sesion is None:
                self._guardia_sesion = GuardiaRed().activar()
        elif self._guardia_sesion is not None:
            self._guardia_sesion.desactivar()
            self._guardia_sesion = None

    def cerrar(self):
        """Libera la guardia de sesión (p. ej. al terminar de usar un selector temporal)."""
        if self._guardia_sesion is not None:
            self._guardia_sesion.desactivar()
            self._guardia_sesion = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()
        return False

    def aislamiento(self):
        """Nivel de aislamiento de red vigente ('proceso' | 'python' | 'ninguno') y su descripción."""
        nivel = aislamiento.nivel_activo()
        return {"nivel": nivel, "descripcion": aislamiento.describir(nivel),
                "configurado": self.config.get("aislamiento_offline", "proceso")}

    # ------------------------------------------------------------ candidatos
    def _candidatos_seccion(self, tipo):
        seccion = self.config[tipo]
        nombres = [seccion["motor"]] + [m for m in seccion.get("fallback", []) if m != seccion["motor"]]
        vistos, resultado = set(), []
        for nombre in nombres:
            if nombre in vistos:
                continue
            vistos.add(nombre)
            cfg = dict(seccion["motores"].get(nombre, {}))
            max_msgs = cfg.pop("max_mensajes_contexto", seccion.get("max_mensajes_contexto"))
            resultado.append(Candidato(nombre=nombre, tipo=tipo, config=cfg, max_mensajes=max_msgs))
        return resultado

    @property
    def prioridad(self):
        return self.config["online"].get("prioridad", "local")

    def candidatos(self, modo=None, fallback_offline=None, prioridad=None):
        """
        Lista ordenada de candidatos para el modo indicado (o el actual).
        En modo online:
          - `prioridad` ('local' | 'online') sobrescribe online.prioridad.
          - `fallback_offline` sobrescribe online.fallback_offline (sólo aplica
            con prioridad 'online').
        En modo offline sólo hay candidatos locales, sin excepción.
        """
        modo = modo or self._modo
        if modo not in MODOS_VALIDOS:
            raise ValueError(f"Modo desconocido: {modo!r}")
        if modo == "offline":
            return self._candidatos_seccion("offline")

        prioridad = prioridad or self.prioridad
        if prioridad not in PRIORIDADES_VALIDAS:
            raise ValueError(f"Prioridad desconocida: {prioridad!r}. Válidas: {PRIORIDADES_VALIDAS}")
        online = self._candidatos_seccion("online")
        if prioridad == "local":
            return self._candidatos_seccion("offline") + online
        if fallback_offline is None:
            fallback_offline = self.config["online"].get("fallback_offline", True)
        return online + (self._candidatos_seccion("offline") if fallback_offline else [])

    # --------------------------------------------------------- disponibilidad
    def comprobar(self, candidato):
        """
        Devuelve (modulo, "") si el candidato puede usarse ahora mismo o
        (None, motivo) en caso contrario. No carga el modelo.
        """
        try:
            modulo = self._obtener_motor(candidato.nombre)
        except MotorNoDisponible as e:
            return None, str(e)

        tipo_motor = getattr(modulo, "TIPO", candidato.tipo)
        if tipo_motor != candidato.tipo:
            return None, f"el motor es de tipo '{tipo_motor}' pero está configurado como '{candidato.tipo}'"

        try:
            if candidato.tipo == "offline":
                with GuardiaRed() as guardia:
                    ok, motivo = modulo.disponible(candidato.config)
                if guardia.intentos:
                    return None, f"intentó acceder a la red al comprobar disponibilidad ({', '.join(guardia.intentos)})"
            else:
                ok, motivo = modulo.disponible(candidato.config)
        except Exception as e:
            return None, f"error comprobando disponibilidad: {e}"
        if not ok:
            return None, motivo or "no disponible"

        if candidato.tipo == "online":
            host = candidato.config.get("host_conectividad") or getattr(modulo, "HOST_CONECTIVIDAD", None)
            if host and not self._comprobar_conexion(host):
                return None, f"sin conexión con {host}"

        return modulo, ""

    def seleccionar(self, modo=None):
        """
        Devuelve (candidato, modulo, errores) del primer candidato utilizable,
        o (None, None, errores) si no hay ninguno.
        """
        errores = []
        for candidato in self.candidatos(modo):
            modulo, motivo = self.comprobar(candidato)
            if modulo is not None:
                return candidato, modulo, errores
            errores.append((candidato.nombre, motivo))
        return None, None, errores

    # --------------------------------------------------------------- responder
    def _generar(self, modulo, candidato, messages):
        """Invoca al motor. Los motores offline se ejecutan bajo GuardiaRed."""
        mensajes = recortar_mensajes(messages, candidato.max_mensajes)
        if candidato.tipo != "offline":
            return modulo.responder(mensajes, candidato.config)
        with GuardiaRed() as guardia:
            texto = modulo.responder(mensajes, candidato.config)
        if guardia.intentos:
            # Respondió, pero intentó salir a la red: se descarta por seguridad.
            raise MotorError(f"intentó acceder a la red durante la generación ({', '.join(guardia.intentos)})")
        return texto

    def responder(self, messages, modo=None, fallback_offline=None, prioridad=None):
        """
        Pide respuesta al primer candidato disponible; si falla al generar,
        continúa con el siguiente. Lanza SinMotorDisponible si ninguno responde.
        """
        modo = modo or self._modo
        errores = []
        candidatos = self.candidatos(modo, fallback_offline=fallback_offline, prioridad=prioridad)

        for indice, candidato in enumerate(candidatos):
            modulo, motivo = self.comprobar(candidato)
            if modulo is None:
                errores.append((candidato.nombre, motivo))
                continue

            try:
                texto = self._generar(modulo, candidato, messages)
            except MotorError as e:
                errores.append((candidato.nombre, str(e)))
                continue
            except Exception as e:  # bug interno del motor: no debe tumbar al asistente
                errores.append((candidato.nombre, f"error inesperado: {e}"))
                continue

            if not texto or not str(texto).strip():
                errores.append((candidato.nombre, "respuesta vacía"))
                continue

            return RespuestaMotor(
                texto=str(texto).strip(),
                motor=candidato.nombre,
                modelo=candidato.modelo,
                tipo=candidato.tipo,
                modo=modo,
                fallback_usado=indice > 0,
                errores=errores,
            )

        raise SinMotorDisponible(modo, errores)

    # ------------------------------------------------------------------ estado
    def estado(self, modo=None):
        """Resumen del modo y la disponibilidad de cada candidato (para diagnóstico)."""
        modo = modo or self._modo
        detalle = []
        for c in self.candidatos(modo):
            modulo, motivo = self.comprobar(c)
            detalle.append({
                "motor": c.nombre,
                "tipo": c.tipo,
                "modelo": c.modelo,
                "disponible": modulo is not None,
                "motivo": motivo,
            })
        return {"modo": modo, "prioridad": self.prioridad if modo == "online" else None,
                "aislamiento": self.aislamiento(), "candidatos": detalle}
