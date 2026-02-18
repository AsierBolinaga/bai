from llama_cpp import Llama
import os
import yaml
from time import time

# Ruta de configuración del motor
CONFIG_PATH = "config/motors_config.yaml"

def cargar_configuracion():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def cargar_modelo_llama():
    config = cargar_configuracion()
    model_path = config.get("model_path", "models/mistral-7b-instruct-v0.1.Q4_0.gguf")

    print(f"[B.A.I] Cargando modelo llama.cpp desde: {model_path}")

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"[B.A.I] No se encontró el modelo en {model_path}")
    
    try:
        modelo = Llama(
            model_path=model_path,
            n_ctx=2048,        
            use_mlock=True,
            verbose=True,
            chat_format="llama-2"
        )
        print("[B.A.I] Modelo cargado correctamente.")
        return modelo
    except Exception as e:
        print(f"[B.A.I] Error al cargar el modelo: {e}")
        return None

modelo = cargar_modelo_llama()

def responder(prompt):
    if not modelo:
        return "[B.A.I] El modelo no está disponible."

    print(f"[DEBUG] Prompt enviado a llama.cpp:{prompt[:300]}...")  # recorte para debug

    inicio = time()

    try:
        resultado = modelo(
            prompt=prompt,
            max_tokens=256,
            temperature=0.7,
            stop=["</s>", "###"]
        )
        duracion = time() - inicio
        print(f"[DEBUG] Tiempo de respuesta: {duracion:.2f} segundos")
        return resultado["choices"][0]["text"].strip()
    except Exception as e:
        return f"[B.A.I] Error al usar llama.cpp: {e}"