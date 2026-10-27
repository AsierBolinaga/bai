#!/bin/bash
# Lanza B.A.I desde cualquier directorio: el entorno virtual y bai.py se
# resuelven respecto a la ubicación de este script. Los argumentos se reenvían
# a bai.py (p. ej. ./bai.sh --online).

BAI_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

echo "[B.A.I] Iniciando sesión con B.A.I..."

# Activar entorno virtual (creado por setup_bai.sh) si existe
if [ -f "$BAI_DIR/venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$BAI_DIR/venv/bin/activate"
    PYTHON=python
else
    echo "[B.A.I] Aviso: no existe $BAI_DIR/venv (ejecuta setup_bai.sh). Se usa python3 del sistema."
    PYTHON=python3
fi

# Ejecutar sistema
exec "$PYTHON" "$BAI_DIR/bai.py" "$@"
