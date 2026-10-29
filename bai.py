import sys

from core.arranque import analizar_argumentos, preparar_arranque

if __name__ == "__main__":
    ui = analizar_argumentos().ui
    raiz = None
    if ui:
        import tkinter
        from core.ui_tk import crear_raiz
        try:
            raiz = crear_raiz()  # antes del aislamiento: ver crear_raiz()
        except tkinter.TclError as e:
            sys.exit(f"[B.A.I] No se puede abrir la ventana ({e}). Usa la consola: python bai.py")
    preparar_arranque()  # opciones de arranque y aislamiento de red (antes de cargar motores)
    if ui:
        from core.ui_tk import iniciar_ui
        iniciar_ui(raiz=raiz)
    else:
        from core.assistant import run_assistant
        run_assistant()
