from __future__ import annotations

import base64
import hashlib
import secrets


class SecureCallbackTokenFactory:
    def create(self) -> tuple[str, str]:
        nonce = secrets.token_bytes(32)
        token = base64.urlsafe_b64encode(nonce).decode().rstrip("=")
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(nonce).digest())
            .decode()
            .rstrip("=")
        )
        return token, digest
