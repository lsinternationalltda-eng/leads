import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

try:
    from main import app
    logger.info("App carregado com sucesso.")
except Exception as e:
    logger.exception("ERRO FATAL ao iniciar app: %s", e)
    raise
