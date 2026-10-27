#!/bin/bash

echo "[B.A.I] Iniciando sesión con B.A.I..."

# Activar entorno virtual
source venv/bin/activate

# Ejecutar sistema
python bai.py "$@"