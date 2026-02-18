# gpt4all_engine.py

from gpt4all import GPT4All
import os
import yaml

# Cargar configuración del modelo
def cargar_configuracion_modelo():
    with open("config/motors_config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def responder(prompt):
    config = cargar_configuracion_modelo()
    modelo = config.get("modelo", "mistral-7b-instruct")
    ruta = config.get("ruta_modelo", f"models/{modelo}.gguf")

    if not os.path.exists(ruta):
        return "[B.A.I] No encuentro el modelo GPT4All especificado."

    try:
        model = GPT4All(model_name=modelo, model_path=os.path.dirname(ruta))
        with model.chat_session():
            respuesta = model.generate(prompt)
        return respuesta
    except Exception as e:
        return f"[B.A.I] Error al generar respuesta offline con GPT4All: {str(e)}"
