from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import Config

engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def init_db():
    """Cria todas as tabelas que ainda não existem. Chamado no boot da app."""
    # Importa os modelos aqui dentro para garantir que estão registrados no Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session():
    """Gera uma sessão de banco. Use com 'with' ou feche manualmente."""
    return SessionLocal()
