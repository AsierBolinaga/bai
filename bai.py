from core.arranque import preparar_arranque

if __name__ == "__main__":
    preparar_arranque()  # opciones de arranque y aislamiento de red (antes de cargar motores)
    from core.assistant import run_assistant
    run_assistant()
