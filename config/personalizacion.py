"""Rutas de personalización privada, con plantillas versionadas como alternativa."""
from config.motors_config import PROJECT_ROOT


def ruta_personalizacion(nombre):
    directorio = PROJECT_ROOT / "config" / "data"
    base = directorio / nombre
    local = base.with_name(f"{base.stem}.local{base.suffix}")
    return local if local.exists() else base
