import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        from app.config import Config
        url = Config.DATABASE_URL
        logger.info("Criando engine para: %s", url.split("@")[0] if "@" in url else url[:30])
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def init_db():
    from app import models  # noqa: F401
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Tabelas criadas/verificadas com sucesso.")


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal()
