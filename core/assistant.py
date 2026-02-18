from core.config import nombre_ia, master_name
from core.memory_engine import save_chat_history, load_full_history, learn_from_input
from core.ai_engine import ask

chat_history = load_full_history()

def run_assistant():
    print(f"[{nombre_ia}] Hola, {master_name}. Conectado a GPT con memoria de sesión.")

    while True:
        try:
            user_input = input("bai> ").strip()

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
                continue

            if user_input.lower().startswith(("aprende:", "recuerda que", "graba esto:", "ten en cuenta que")):
                learn_from_input(user_input)
                print(f"[{nombre_ia}] He aprendido y actualizado tu perfil, jauna.")
                continue

            response = ask(user_input, chat_history)
            print(f"\n[{nombre_ia}] {response}\n")
            save_chat_history(chat_history)

        except KeyboardInterrupt:
            print(f"\n[{nombre_ia}] Sesión finalizada.")
            save_chat_history(chat_history)
            break
