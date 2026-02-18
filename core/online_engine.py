import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def responder_online(prompted_history):
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=prompted_history,
            temperature=0.5,
            max_tokens=1024
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[B.A.I] Error al contactar con OpenAI: {str(e)}"
