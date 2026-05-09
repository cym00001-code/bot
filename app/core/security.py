from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet


class Encryptor:
    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    def encrypt_json(self, value: Any) -> str:
        return self.encrypt_text(json.dumps(value, ensure_ascii=False, sort_keys=True)) or ""

    def decrypt_json(self, value: str | None) -> Any:
        raw = self.decrypt_text(value)
        return json.loads(raw) if raw else None


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def mask_secret(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"
