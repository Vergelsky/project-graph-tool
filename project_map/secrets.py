"""Encrypt repository tokens. The key lives beside the cabinet database."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from pathlib import Path


def load_or_create_key(path: Path) -> bytes:
    """Return the 32-byte cabinet key, creating it on first launch."""
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise RuntimeError(f"Cabinet key must be 32 bytes: {path}")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    return key


def encrypt(key: bytes, text: str) -> str:
    """Encrypt text. The result is not the original token."""
    nonce = secrets.token_bytes(16)
    body = text.encode("utf-8")
    cipher = bytes(left ^ right for left, right in zip(body, _keystream(key, nonce, len(body))))
    mac = hmac.new(key, b"mac" + nonce + cipher, hashlib.sha256).digest()
    return base64.b64encode(nonce + mac + cipher).decode("ascii")


def decrypt(key: bytes, blob: str) -> str:
    """Decrypt a token stored by encrypt."""
    raw = base64.b64decode(blob)
    nonce, mac, cipher = raw[:16], raw[16:48], raw[48:]
    expected = hmac.new(key, b"mac" + nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Сохранённый токен повреждён")
    body = bytes(left ^ right for left, right in zip(cipher, _keystream(key, nonce, len(cipher))))
    return body.decode("utf-8")


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    """HMAC stream long enough for the token."""
    chunks = bytearray()
    counter = 0
    while len(chunks) < size:
        block = hmac.new(key, b"stream" + nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        chunks.extend(block)
        counter += 1
    return bytes(chunks[:size])
