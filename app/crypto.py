"""
Utilitários de criptografia para tokens de System User em repouso (Fernet/AES-128).

Para gerar uma chave nova:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Guarde o resultado no .env como ENCRYPTION_KEY. Perder essa chave significa perder
acesso a todos os tokens cadastrados — trate como segredo de nível de produção.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import Config


def _fernet() -> Fernet:
    key = Config.ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY não configurada. Gere com:\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plain: str) -> str:
    """Criptografa um token de System User para armazenamento em banco."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Descriptografa um token previamente cifrado com encrypt_token."""
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Token inválido ou ENCRYPTION_KEY incorreta.") from exc
