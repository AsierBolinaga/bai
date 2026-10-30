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

# El lanzador prepara el modelo ligero antes de aislar la sesión offline.
# Copilot es opcional: pip install -r requirements-copilot.txt y copilot login.

# Lanzar B.A.I.
echo "[B.A.I] Lanzando B.A.I..."
chmod +x bai.sh
./bai.sh
