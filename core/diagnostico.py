"""
Diagnóstico de motores de B.A.I.

    python -m core.diagnostico                 # estado de configuración, librerías y modelos
    python -m core.diagnostico --probar        # además, genera una respuesta real en modo offline
    python -m core.diagnostico --probar --bloquear-red
                                               # igual, demostrando que no se abre ninguna conexión externa
    python -m core.diagnostico --probar --aislar
                                               # igual, dentro de un namespace de red (kernel): demuestra
                                               # el aislamiento de proceso si el sistema lo permite
    python -m core.diagnostico --probar --modo online
                                               # prueba el modo online (requiere OPENAI_API_KEY)

No requiere credenciales: sin OPENAI_API_KEY simplemente informa de que el
motor online no está disponible. Devuelve código de salida 0 si el modo
solicitado tiene al menos un motor utilizable, 1 en caso contrario.
"""
import argparse
import importlib.metadata
import os
import sys
import time

from config.motors_config import MODOS_VALIDOS, cargar_motors_config, resolver_ruta
from core import aislamiento
from core.model_selector import ModelSelector, SinMotorDisponible
from core.motors.base import libreria_instalada, validar_gguf
from core.network_guard import GuardiaRed

LIBRERIAS = {"openai": "openai", "llama_cpp": "llama-cpp-python", "gpt4all": "gpt4all"}


def _version(paquete):
    try:
        return importlib.metadata.version(paquete)
    except importlib.metadata.PackageNotFoundError:
        return None


def informe_librerias():
    lineas = []
    for modulo, paquete in LIBRERIAS.items():
        if libreria_instalada(modulo):
            lineas.append(f"  OK  {paquete:<18} {_version(paquete) or ''}")
        else:
            lineas.append(f"  --  {paquete:<18} no instalada (pip install {paquete})")
    return lineas


def informe_modelos(config):
    lineas, vistos = [], set()
    for seccion in ("offline",):
        for nombre, cfg in config[seccion]["motores"].items():
            ruta = cfg.get("model_path")
            if not ruta or ruta in vistos:
                continue
            vistos.add(ruta)
            absoluta = resolver_ruta(ruta)
            ok, motivo = validar_gguf(absoluta)
            if ok:
                tam = os.path.getsize(absoluta) / (1024 ** 3)
                lineas.append(f"  OK  {ruta}  ({tam:.2f} GiB, cabecera GGUF válida)")
            else:
                lineas.append(f"  --  {ruta}  -> {motivo}")
    return lineas


def informe_estado(selector, modo):
    estado = selector.estado(modo)
    lineas = []
    for c in estado["candidatos"]:
        marca = "OK " if c["disponible"] else "-- "
        detalle = "" if c["disponible"] else f"  ({c['motivo']})"
        lineas.append(f"  {marca}{c['tipo']:<7} {c['motor']:<10} modelo={c['modelo']}{detalle}")
    return lineas, any(c["disponible"] for c in estado["candidatos"])


def probar(selector, modo, pregunta, bloquear_red=False):
    mensajes = [
        {"role": "system", "content": "Eres B.A.I, un asistente modular. Responde en el idioma del usuario."},
        {"role": "user", "content": pregunta},
    ]
    bloqueo = GuardiaRed() if bloquear_red else None
    inicio = time.time()
    try:
        if bloqueo:
            with bloqueo:
                r = selector.responder(mensajes, modo=modo)
        else:
            r = selector.responder(mensajes, modo=modo)
    except SinMotorDisponible as e:
        return False, f"  FALLO: {e}", bloqueo
    duracion = time.time() - inicio
    texto = r.texto.replace("\n", " ")
    if len(texto) > 160:
        texto = texto[:160] + "..."
    resumen = (f"  OK  {r.motor} [{r.modelo}] ({r.tipo}{', fallback' if r.fallback_usado else ''}) "
               f"en {duracion:.1f}s\n  Respuesta: {texto}")
    if r.errores:
        resumen += "\n  Descartados: " + "; ".join(f"{m}: {e}" for m, e in r.errores)
    return True, resumen, bloqueo


def main(argv=None):
    parser = argparse.ArgumentParser(description="Diagnóstico de motores de B.A.I")
    parser.add_argument("--modo", choices=MODOS_VALIDOS, default="offline",
                        help="modo a diagnosticar/probar (por defecto: offline)")
    parser.add_argument("--probar", action="store_true", help="genera una respuesta real con el motor seleccionado")
    parser.add_argument("--pregunta", default="Hola, ¿quién eres?", help="texto para la prueba")
    parser.add_argument("--bloquear-red", action="store_true",
                        help="bloquea toda conexión no local durante la prueba (verifica que offline no usa la red)")
    parser.add_argument("--aislar", action="store_true",
                        help="activa el aislamiento de proceso (namespace de red) antes de la prueba")
    parser.add_argument("--config", default=None, help="ruta alternativa a motors_config.yaml")
    args = parser.parse_args(argv)

    config = cargar_motors_config(args.config)

    if args.aislar:
        ok, detalle = aislamiento.aislar_proceso()
        print("Aislamiento de proceso: " + ("ACTIVADO" + (f" ({detalle})" if detalle else "") if ok else f"NO DISPONIBLE ({detalle})"))

    selector = ModelSelector(config=config)
    selector.cerrar()  # el diagnóstico gestiona su propia guardia (--bloquear-red)

    print(f"Configuración: modo_por_defecto={config['modo_por_defecto']}  "
          f"aislamiento_offline={config['aislamiento_offline']}  "
          f"online.prioridad={config['online']['prioridad']}  mostrar_motor={config['mostrar_motor']}")
    info = aislamiento.estado()
    print(f"Aislamiento vigente: {info['nivel']} — {info['descripcion']}")
    if not info["proceso_disponible"]:
        print(f"  (aislamiento de proceso no disponible en este sistema: {info['motivo_no_disponible']})")
    print(f"  interfaces visibles: {', '.join(info['interfaces'] or ['?'])}")
    print("\nLibrerías:")
    print("\n".join(informe_librerias()))
    print("\nModelos locales (GGUF):")
    print("\n".join(informe_modelos(config)) or "  (ninguno configurado)")
    print(f"\nCandidatos en modo {args.modo.upper()}:")
    lineas, hay_disponible = informe_estado(selector, args.modo)
    print("\n".join(lineas))

    codigo = 0 if hay_disponible else 1
    if args.probar:
        print(f"\nPrueba real en modo {args.modo.upper()}" + (" con la red bloqueada" if args.bloquear_red else "") + ":")
        ok, resumen, bloqueo = probar(selector, args.modo, args.pregunta, args.bloquear_red)
        print(resumen)
        if bloqueo is not None:
            if bloqueo.intentos:
                print(f"  ATENCIÓN: se intentó abrir la red hacia: {', '.join(bloqueo.intentos)}")
                codigo = 1
            else:
                print("  Red: ningún intento de conexión externa desde código Python durante la generación"
                      + (" (y el kernel bloquea cualquier otro: aislamiento de proceso)." if info["nivel"] == "proceso"
                         else ". Nota: la guardia Python no ve subprocesos ni código nativo; usa --aislar."))
        if not ok:
            codigo = 1
    return codigo


if __name__ == "__main__":
    sys.exit(main())
