import os
import json
import yaml
from datetime import datetime
import unicodedata
import re

# Rutas absolutas respecto a la raíz del proyecto (independientes del directorio de trabajo)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(_PROJECT_ROOT, "history")
SESSION_FILE = os.path.join(HISTORY_DIR, "historial.json")
MEMORY_PATH = os.path.join(_PROJECT_ROOT, "config", "data", "user_profile.yaml")
MAX_MESSAGES = 5000
os.makedirs(HISTORY_DIR, exist_ok=True)

def learn_from_input(raw_input):
    try:
        if not raw_input or len(raw_input.split()) < 2:
            return

        if ":" in raw_input:
            text = raw_input.split(":", 1)[1].strip()
        else:
            text = re.sub(
                r"^(tengo|me gusta|sabes que|recuerda que|graba esto:|ten en cuenta que|aprende que|anota que|no olvides que|quiero que recuerdes que|memoriza que|añade que|te digo que)",
                "",
                raw_input,
                flags=re.IGNORECASE
            ).strip()

        if not text or " " not in text:
            return

        match = re.match(r"(.+?)\s+es\s+(.+)", text, re.IGNORECASE)
        if match:
            key, value = match.group(1).strip().lower(), match.group(2).strip()
        else:
            key, value = text.split(" ", 1)[0].lower(), text.split(" ", 1)[1].strip()

        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if any(word in key for word in ["pareja", "novia", "novio"]):
            data.setdefault("vida_personal", {}).setdefault("pareja", {})["nombre"] = value
        elif "furgoneta" in key or "camper" in key or "vehiculo" in key:
            data.setdefault("vida_personal", {})["vehiculo"] = value
        elif "entreno" in key or "entrenamiento" in key:
            data.setdefault("vida_personal", {})["entreno"] = value
        elif "ilustracion" in key or any(x in value.lower() for x in ["pixar", "funko", "disney"]):
            data.setdefault("gustos", {}).setdefault("ilustracion_personalizada", []).append(value)
        elif "estilo" in key or "visual" in key:
            data.setdefault("gustos", {})["estilo_visual"] = value
        elif "freelance" in key or "trabajo" in key:
            data.setdefault("freelance", {})["estado"] = value
        elif any(word in key for word in ["nombre", "alias"]):
            data[key] = value
        elif any(x in key for x in ["sistema operativo", "ubuntu", "windows"]):
            data.setdefault("entorno", {}).setdefault("sistemas_operativos", []).append(value)
        elif "microcontrolador" in key or "i.mx" in value.lower():
            data.setdefault("entorno", {}).setdefault("microcontroladores", []).append(value)
        elif "tecnologia" in key or value.lower() in ["mqtt", "lwip", "freertos", "git", "sdk nxp", "asyncapi"]:
            data.setdefault("entorno", {}).setdefault("tecnologias", []).append(value)
        elif "broker" in key or value.lower() == "mosquitto":
            data.setdefault("entorno", {}).setdefault("brokers", []).append(value)
        elif "interfaz" in key or "android" in value.lower():
            data.setdefault("entorno", {}).setdefault("interfaz_coche", []).append(value)
        elif "docker" in key:
            data.setdefault("entorno", {}).setdefault("configuracion", {})["dockerizado"] = value.lower() in ["true", "sí", "si"]
        elif "cli" in key:
            data.setdefault("entorno", {}).setdefault("configuracion", {})["usa_CLI"] = value.lower() in ["true", "sí", "si"]
        elif "dualboot" in key:
            data.setdefault("entorno", {}).setdefault("configuracion", {})["dualboot"] = value.lower() in ["true", "sí", "si"]
        else:
            data.setdefault("aprendido_durante_sesion", {})[key] = value

        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

    except Exception as e:
        print(f"[B.A.I] Error al aprender: {e}")

def save_chat_history(history):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except UnicodeEncodeError:
        with open(SESSION_FILE, "w", encoding="utf-8", errors="replace") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

def load_full_history():
    messages = []
    archivos_a_borrar = []

    os.makedirs(HISTORY_DIR, exist_ok=True)

    # Cargar historial activo si existe
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                session = json.load(f)
                messages.extend([m for m in session if m["role"] in ["user", "assistant"]])
        except Exception as e:
            print(f"[B.A.I] Error leyendo historial.json: {e}")

    # Cargar sesiones anteriores
    for file in os.listdir(HISTORY_DIR):
        if file.endswith(".json") and file != os.path.basename(SESSION_FILE):
            path = os.path.join(HISTORY_DIR, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    session = json.load(f)
                    messages.extend([m for m in session if m["role"] in ["user", "assistant"]])
                    archivos_a_borrar.append(path)
            except Exception as e:
                print(f"[B.A.I] Error cargando {file}: {e}")

    messages = messages[-MAX_MESSAGES:]

    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
    except UnicodeEncodeError:
        with open(SESSION_FILE, "w", encoding="utf-8", errors="replace") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)

    for path in archivos_a_borrar:
        try:
            os.remove(path)
        except Exception as e:
            print(f"[B.A.I] Error borrando {path}: {e}")

    return messages

def get_memory_context():
    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        memory = yaml.safe_load(f)

    aprendido = memory.get("aprendido_durante_sesion", {})
    texto = []

    for k, v in memory.items():
        if isinstance(v, dict):
            for subk, subv in v.items():
                if isinstance(subv, dict):
                    for ssubk, ssubv in subv.items():
                        texto.append(f"{ssubk.capitalize()} es {ssubv}.")
                elif isinstance(subv, list):
                    texto.append(f"{subk.capitalize()} incluye: {', '.join(map(str, subv))}.")
                else:
                    texto.append(f"{subk.capitalize()} es {subv}.")
        elif isinstance(v, list):
            texto.append(f"{k.capitalize()} incluye: {', '.join(map(str, v))}.")
        else:
            texto.append(f"{k.capitalize()} es {v}.")

    for k, v in aprendido.items():
        texto.append(f"{k.capitalize()} es {v}.")

    return "\n".join(texto)