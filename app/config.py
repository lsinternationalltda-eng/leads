import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuração central da aplicação, lida do .env"""

    _db_url = os.getenv("DATABASE_URL", "sqlite:////tmp/local.db")
    # Converte postgres:// e postgresql:// para pg8000 (driver puro Python, sem libpq)
    if _db_url.startswith("postgres://"):
        _db_url = "postgresql+pg8000://" + _db_url[len("postgres://"):]
    elif _db_url.startswith("postgresql://"):
        _db_url = "postgresql+pg8000://" + _db_url[len("postgresql://"):]
    DATABASE_URL = _db_url

    META_APP_ID = os.getenv("META_APP_ID")
    META_APP_SECRET = os.getenv("META_APP_SECRET")
    WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")

    WHATSAPP_BUSINESS_TOKEN = os.getenv("WHATSAPP_BUSINESS_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH")

    # Usada para criptografar os tokens de System User de cada BM em repouso (via app/crypto.py).
    # Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

    # Janela de tolerância antes de marcar um lead como divergente
    # (Meta reportou, mas ainda não confirmou na planilha/WhatsApp)
    DIVERGENCE_WINDOW_MINUTES = int(os.getenv("DIVERGENCE_WINDOW_MINUTES", "30"))
