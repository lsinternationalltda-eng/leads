import logging
import os
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

_db_url = os.getenv("DATABASE_URL", "")
_db_tipo = "postgresql" if ("postgresql" in _db_url or "postgres" in _db_url) else ("sqlite" if "sqlite" in _db_url else "nao_definido")
logger.info("DATABASE_URL tipo detectado: %s", _db_tipo)

try:
    from main import app
    logger.info("App carregado com sucesso.")
except Exception as e:
    logger.exception("ERRO FATAL ao iniciar app: %s", e)
    raise
