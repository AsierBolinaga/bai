import yaml
from config.motors_config import motors_config

# Mapear motores disponibles
MOTORES_DISPONIBLES = {
    "gpt4all": "core.motors.gpt4all_engine",
    "llama_cpp": "core.motors.llama_cpp_engine"
}

def responder_offline(prompt, context=None):
    motor = motors_config.get("motor_offline")

    if motor not in MOTORES_DISPONIBLES:
        return False, f"[B.A.I] Motor '{motor}' no reconocido."

    try:
        module_path = MOTORES_DISPONIBLES[motor]
        motor_module = __import__(module_path, fromlist=[''])
        respuesta = motor_module.responder(prompt)

        if respuesta and len(respuesta.strip()) > 0:
            return True, respuesta
        else:
            return False, "[B.A.I] El motor no devolvió respuesta."

    except Exception as e:
        return False, f"[B.A.I] Error ejecutando el motor '{motor}': {e}"