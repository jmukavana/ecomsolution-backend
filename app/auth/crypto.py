"""Hashing + symmetric encryption helpers.

Conventions:
- OTP codes and recovery codes are stored as SHA-256 hashes (one-shot secrets,
  not user passwords, so a fast hash is fine).
- Session tokens are stored as SHA-256 hashes (opaque random tokens).
- TOTP secrets are encrypted at rest with Fernet using a key derived from
  SESSION_SECRET so they round-trip safely.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from app.config import settings


def hash_code(code: str) -> str:
    """SHA-256 hex digest. Suitable for one-shot tokens, not user passwords."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_code(code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code), expected_hash)


def random_token(nbytes: int = 32) -> str:
    """URL-safe random token used as session cookie value."""
    return secrets.token_urlsafe(nbytes)


def random_numeric(length: int) -> str:
    """Zero-padded random numeric string for OTPs."""
    upper = 10**length
    n = secrets.randbelow(upper)
    return str(n).zfill(length)


def _fernet() -> Fernet:
    raw = settings.SESSION_SECRET.encode("utf-8")
    # Derive a stable 32-byte key from SESSION_SECRET so secrets encrypted today
    # can be decrypted after a restart (Fernet keys must be base64-urlsafe 32 bytes).
    digest = hashlib.sha256(raw).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
