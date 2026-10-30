import subprocess
import signal
import sys
from pathlib import Path

from core.arranque import analizar_argumentos, preparar_arranque


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = analizar_argumentos(argv)
    if args.preparar_modelo:
        from config.motors_config import cargar_motors_config
        from core.motors.base import MotorError
        from core.preparar_modelo import preparar_modelo
        try:
            preparar_modelo(cargar_motors_config(), permitir_descarga=True)
        except (MotorError, OSError) as error:
            print(f"[B.A.I] No se puede preparar el motor local: {error}", file=sys.stderr)
            return 1
        return 0
    if not args.sesion:
        from core.reinicio import ONLINE, OFFLINE
        while True:
            argumentos_sesion = [*argv, "--sesion"]
            anterior_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                resultado = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                            *argumentos_sesion])
            except KeyboardInterrupt:
                return 130
            finally:
                signal.signal(signal.SIGINT, anterior_sigint)
            if resultado.returncode not in (ONLINE, OFFLINE):
                return resultado.returncode
            argv = [a for a in argv if a not in ("--online", "--offline")]
            argv.append("--online" if resultado.returncode == ONLINE else "--offline")
    # El supervisor deja que la sesion gestione Ctrl+C, sin matarla al cancelar.
    signal.signal(signal.SIGINT, signal.default_int_handler)
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
    from core.ai_engine import get_selector
    selector = get_selector()
    aviso_arranque = None
    if config["modo_por_defecto"] == "offline":
        from core.motors import registry
        from core.motors.base import MotorError
        nombre_motor = config["offline"]["motor"]
        opciones = config["offline"]["motores"][nombre_motor]
        error_local = None
        try:
            motor = registry.obtener_motor(nombre_motor)
            ok, motivo = motor.disponible(opciones)
            if not ok:
                raise MotorError(f"{motivo}. Prepara el modelo con './bai.sh --preparar-modelo' "
                                 "si usas el Qwen predeterminado; para otros modelos revisa su configuración.")
            if opciones.get("descargar_al_arrancar"):
                from core.preparar_modelo import preparar_modelo
                preparar_modelo(config)
                selector.precargar(motor, opciones)
        except (MotorError, OSError, ImportError) as error:
            error_local = f"No se pudo cargar el modelo local: {error}"
        if error_local:
            from core.ai_engine import get_selector
            get_selector().marcar_no_disponible(nombre_motor, error_local)
            aviso_arranque = (
                f"Modo degradado: {nombre_motor} no disponible. {error_local}. "
                "Puedes usar ayuda, memoria y estado, o autorizar el cambio a Online. "
                "Corrige el problema y reinicia B.A.I. para reintentar el motor local.")
            print(f"[B.A.I] {aviso_arranque}", file=sys.stderr)
    try:
        if ui:
            from core.ui_tk import iniciar_ui
            return iniciar_ui(raiz=raiz, aviso_arranque=aviso_arranque)
        else:
            from core.assistant import run_assistant
            return run_assistant()
    finally:
        selector.cerrar()


if __name__ == "__main__":
    sys.exit(main())
