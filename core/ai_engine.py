import os
import yaml
import json
import socket
from datetime import datetime
import unicodedata
import re
from dotenv import load_dotenv
from core.memory_engine import learn_from_input, get_memory_context
from core.offline_engine import responder_offline
from core.online_engine import responder_online

load_dotenv()

modo_actual = "online" 

def clean_text(text):
    return unicodedata.normalize("NFKD", text).encode("utf-8", "ignore").decode("utf-8")

def get_system_prompt():
    with open("config/data/system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read()



def hay_conexion(host="api.openai.com", port=443, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False

def ask(user_input, chat_history):
    global modo_actual
    learn_from_input(user_input)

    # Comandos de cambio de modo
    if "pasa a modo offline" in user_input.lower():
        modo_actual = "offline"
        return "[B.A.I] Modo cambiado a OFFLINE. Usaré solo motores locales."

    if "pasa a modo online" in user_input.lower():
        modo_actual = "online"
        return "[B.A.I] Modo cambiado a ONLINE. Usaré OpenAI por defecto."
    
    system_prompt = get_system_prompt()
    memory_context = get_memory_context()

    if chat_history is None:
        chat_history = []

    prompted_history = chat_history.copy()
    prompted_history[:] = [m for m in prompted_history if m["role"] != "system"]
    prompted_history.insert(0, {"role": "system", "content": system_prompt})
    prompted_history.insert(1, {"role": "system", "content": memory_context})
    prompted_history.append({"role": "system", "content": "Responde siempre en el idioma del usuario."})
    prompted_history.append({"role": "user", "content": user_input})

    if modo_actual == "online":
        if hay_conexion():
            respuesta = responder_online(prompted_history)
            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": respuesta})
            return respuesta
        else:
            print("[B.A.I] No hay conexión a Internet. Usaré el motor local.")
            ok, respuesta = responder_offline(user_input)
            if ok:
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({"role": "assistant", "content": respuesta})
                return respuesta
            else:
                return "[B.A.I] El motor local tampoco ha podido responder."

    else: # Modo offline forzado
        ok, respuesta = responder_offline(user_input)
        if ok:
            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": respuesta})
            return respuesta
        else:
            return "[B.A.I] El motor local no ha podido generar una respuesta."
