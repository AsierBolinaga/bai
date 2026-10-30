from core.config import nombre_ia, master_name
from core.memory_engine import save_chat_history, load_full_history
from core.ai_engine import ask, describir_estado
from core.reinicio import aviso_reinicio, codigo_modo, modo_reinicio
from copy import deepcopy

chat_history = load_full_history()

def run_assistant():
    print(f"[{nombre_ia}] Hola, {master_name}. Memoria de sesión cargada.")
    print(f"[{nombre_ia}] {describir_estado()}")
    print(f"[{nombre_ia}] Comandos: 'pasa a modo offline' | 'pasa a modo online' | 'estado' | 'ayuda'")
    print(f"[{nombre_ia}] Memoria: 'recuerda que X es Y' | '¿qué recuerdas?' | 'recuerda que ahora X es Z' | 'olvida X'")

    while True:
        try:
            user_input = input("bai> ").strip()
            modo = modo_reinicio(user_input)
            if modo is not None:
                print(f"[{nombre_ia}] {aviso_reinicio(modo)}")
                if input("¿Continuar? [s/N] ").strip().lower() in ("s", "si", "sí"):
                    if save_chat_history(chat_history):
                        return codigo_modo(modo)
                    print(f"[{nombre_ia}] No se puede reiniciar: ha fallado el guardado del historial.")
                continue

            if user_input.lower() in ["salir", "exit", "irten", "atera", "amaitu", "quit"]:
                print(f"[{nombre_ia}] Agur, {master_name}.")
                save_chat_history(chat_history)
                break

            if user_input.lower() in ["ver memoria", "mostrar memoria"]:
                from pprint import pprint
                pprint(chat_history)
                continue

            if user_input.lower() in ["reset", "limpiar"]:
                chat_history.clear()
                print(f"[{nombre_ia}] Memoria de sesión limpiada.")
                if not save_chat_history(chat_history):
                    print(f"[{nombre_ia}] No he podido guardar el historial vacío en disco.")
                continue

            # Las peticiones de memoria ("recuerda que...", "olvida...", "¿qué
            # recuerdas?") las resuelve ask() localmente y con informe honesto:
            # sólo confirma cuando la escritura en disco ha terminado bien.
            try:
                historial_turno = deepcopy(chat_history)
                response = ask(user_input, historial_turno)
            except KeyboardInterrupt:
                print(f"\n[{nombre_ia}] Generación cancelada; puedes enviar otra pregunta.")
                continue
            chat_history[:] = historial_turno
            print(f"\n[{nombre_ia}] {response}\n")
            save_chat_history(chat_history)

        except KeyboardInterrupt:
            print(f"\n[{nombre_ia}] Sesión finalizada.")
            save_chat_history(chat_history)
            break
