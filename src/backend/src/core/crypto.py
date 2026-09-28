# pylint: disable=missing-function-docstring
"""
src/core/crypto.py

Symmetric encryption for secrets we must store at rest (e.g. a PSN npsso
token) but never need to search/index — Fernet (AES-128-CBC + HMAC) via
`settings.SECRET_KEY`.

Generate a key for `.env`'s SECRET_KEY with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    try:
        return Fernet(settings.SECRET_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "SECRET_KEY is not a valid Fernet key — generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`'
        ) from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Could not decrypt stored secret: SECRET_KEY may have changed.") from exc
