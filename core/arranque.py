"""
Preparación del arranque de B.A.I (usado por bai.py antes de cargar nada más).

  python bai.py                   arranca según motors_config.yaml (offline por defecto)
  python bai.py --online          autoriza servicios online en esta sesión (sin
                                  aislamiento de proceso; prioridad local se mantiene)
  python bai.py --offline         fuerza el modo offline
  python bai.py --ui              abre la ventana gráfica (tkinter) en vez de la consola
  python bai.py --aislamiento python
                                  usa la guardia Python en vez del namespace de red
                                  (permite "pasa a modo online" en la misma sesión)

Si el modo inicial es offline y el aislamiento configurado es "proceso", el
proceso se mueve a un namespace de red propio AQUÍ, con un único hilo y antes
de importar motores. Si no es posible, se informa del motivo y se continúa con
la guardia Python (el estado lo refleja honestamente).
"""
import argparse

from config.motors_config import AISLAMIENTOS_VALIDOS, SOBRESCRITURAS, cargar_motors_config
from core import aislamiento


def analizar_argumentos(argv=None):
    parser = argparse.ArgumentParser(prog="bai.py", description="B.A.I — asistente personal modular")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--online", action="store_true",
                      help="autoriza el uso de servicios online en esta sesión (los motores locales siguen teniendo prioridad)")
    modo.add_argument("--offline", action="store_true", help="fuerza el modo offline")
    parser.add_argument("--ui", action="store_true", help="abre la interfaz gráfica en lugar de la consola")
    parser.add_argument("--aislamiento", choices=AISLAMIENTOS_VALIDOS, default=None,
                        help="nivel de aislamiento de red en modo offline (por defecto el de la configuración)")
    return parser.parse_args(argv)


def preparar_arranque(argv=None, salida=print):
    """Aplica las opciones de línea de comandos y, si procede, el aislamiento de proceso."""
    args = analizar_argumentos(argv)
    if args.online:
        SOBRESCRITURAS["modo_por_defecto"] = "online"
    elif args.offline:
        SOBRESCRITURAS["modo_por_defecto"] = "offline"
    if args.aislamiento:
        SOBRESCRITURAS["aislamiento_offline"] = args.aislamiento

    config = cargar_motors_config()
    if config["modo_por_defecto"] == "offline" and config["aislamiento_offline"] == "proceso":
        ok, detalle = aislamiento.aislar_proceso()
        if ok:
            salida("[B.A.I] Aislamiento de proceso activo: esta sesión no tiene acceso a la red externa "
                   "(bloqueo del kernel). Para autorizar servicios online: python bai.py --online")
            info = aislamiento.estado()
            if info["loopback"] is False:
                salida("[B.A.I] ATENCIÓN: no se pudo activar la interfaz loopback dentro del namespace: los "
                       "servicios locales por TCP/UDP (p. ej. Ollama en localhost) no funcionarán en esta sesión.")
            if info["mapa_uid"] is False:
                salida("[B.A.I] Nota: el mapa de uid no se aplicó: los ficheros pueden aparecer como 'nobody'.")
            if info["mapa_gid"] is False:
                salida("[B.A.I] Nota: el mapa de gid no se aplicó (getgid() devuelve 65534).")
            for incidencia in info["incidencias"]:
                salida(f"[B.A.I]   - {incidencia}")
        else:
            salida(f"[B.A.I] Aviso: aislamiento de proceso no disponible ({detalle}). "
                   "Se usa la guardia Python, que NO cubre subprocesos ni código nativo.")
    return config
