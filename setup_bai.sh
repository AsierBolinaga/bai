#!/bin/bash

echo "[B.A.I] Inicializando entorno..."

# Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo "[B.A.I] Creando entorno virtual..."
    python3 -m venv venv
fi

# Activar entorno virtual
echo "[B.A.I] Activando entorno virtual..."
source venv/bin/activate

# Instalar dependencias
echo "[B.A.I] Instalando dependencias..."
pip install --upgrade pip
pip install -r requirements.txt

# Verificar y descargar modelo si no existe
#MODEL_PATH="models/mistral-7b-instruct-v0.1.Q4_0.gguf"
#MODEL_URL="https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.1-GGUF/resolve/main/mistral-7b-instruct-v0.1.Q4_0.gguf"

#if [ ! -f "$MODEL_PATH" ]; then
#    echo "[B.A.I] Descargando modelo Mistral Q4_0..."
#    mkdir -p models
#    wget -O "$MODEL_PATH" "$MODEL_URL"
#else
#    echo "[B.A.I] Modelo ya presente. No se descarga de nuevo."
#fi

# Lanzar B.A.I.
echo "[B.A.I] Lanzando B.A.I..."
chmod +x bai.sh
./bai.sh
