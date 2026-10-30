import subprocess
import sys
from pathlib import Path

from core.arranque import analizar_argumentos, preparar_arranque


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = analizar_argumentos(argv)
    if not args.sesion:
        from config.motors_config import cargar_motors_config
        from core.motors.base import MotorError
        from core.preparar_modelo import preparar_modelo
        from core.reinicio import ONLINE, OFFLINE
        while True:
            config = cargar_motors_config()
            modo = "online" if "--online" in argv else (
                "offline" if "--offline" in argv else config["modo_por_defecto"])
            try:
                if modo == "offline":
                    preparar_modelo(config)
            except (MotorError, OSError) as error:
                print(f"[B.A.I] No se puede preparar el motor local: {error}", file=sys.stderr)
                return 1
            try:
                resultado = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                            *argv, "--sesion"])
            except KeyboardInterrupt:
                return 130
            if resultado.returncode not in (ONLINE, OFFLINE):
                return resultado.returncode
            argv = [a for a in argv if a not in ("--online", "--offline")]
            argv.append("--online" if resultado.returncode == ONLINE else "--offline")
    ui = args.ui
    raiz = None
    if ui:
        import tkinter
        from core.ui_tk import crear_raiz
        try:
            raiz = crear_raiz()  # antes del aislamiento: ver crear_raiz()
        except tkinter.TclError as e:
            sys.exit(f"[B.A.I] No se puede abrir la ventana ({e}). Usa la consola: python bai.py")
    config = preparar_arranque(argv)
    if config["modo_por_defecto"] == "offline":
        from core.motors import registry
        from core.motors.base import MotorError
        opciones = config["offline"]["motores"][config["offline"]["motor"]]
        if opciones.get("descargar_al_arrancar"):
            try:
                registry.obtener_motor(config["offline"]["motor"]).cargar_modelo(opciones)
            except MotorError as error:
                print(f"[B.A.I] No se pudo cargar el modelo local: {error}", file=sys.stderr)
                if raiz is not None:
                    raiz.destroy()
                return 1
    if ui:
        from core.ui_tk import iniciar_ui
        return iniciar_ui(raiz=raiz)
    else:
        from core.assistant import run_assistant
        return run_assistant()


if __name__ == "__main__":
    sys.exit(main())
