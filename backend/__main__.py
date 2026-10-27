import argparse
from dataclasses import asdict
import sys

from .config import Settings
from .errors import BackendError


def main():
    parser = argparse.ArgumentParser(description="Backend USB · Grupo C. Inicia sin conectar ni capturar automaticamente.")
    parser.add_argument("--config", help="Archivo JSON de configuracion del servidor")
    parser.add_argument("--host", help="127.0.0.1 por defecto; 0.0.0.0 para acceso por red local")
    parser.add_argument("--port", type=int, help="Puerto HTTP, 8001 por defecto")
    parser.add_argument("--database", help="Ruta de la base SQLite")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Se requiere Python 3.11 o posterior.")
    try:
        config = asdict(Settings.load(args.config))
        for key in ("host", "port", "database"):
            if getattr(args, key) is not None:
                config[key] = getattr(args, key)
        settings = Settings.from_mapping(config)
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1, log_level="info")
    except (BackendError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
