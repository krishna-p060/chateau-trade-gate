"""Signing keys and JWS helpers (Ed25519 / EdDSA, RFC 8037).

The gate signs every quote and order confirmation so an external agent can verify Valio's claims
(price, stock status, delivery date) offline against the published JWKS. Buyers sign their agents'
purchasing mandates with their own key, which the gate verifies before acting.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class KeyPair:
    def __init__(self, kid: str, private: Ed25519PrivateKey):
        self.kid = kid
        self.private = private
        self.public: Ed25519PublicKey = private.public_key()

    @staticmethod
    def load_or_create(path: Path, kid: str) -> "KeyPair":
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        else:
            key = Ed25519PrivateKey.generate()
            path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
            path.chmod(0o600)
        return KeyPair(kid, key)

    def jwk(self) -> dict:
        raw = self.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return {"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw), "kid": self.kid, "use": "sig", "alg": "EdDSA"}

    def sign(self, payload: dict, typ: str = "JWT") -> str:
        return jwt.encode(payload, self.private, algorithm="EdDSA", headers={"kid": self.kid, "typ": typ})


def public_key_from_jwk(jwk: dict) -> Ed25519PublicKey:
    raw = base64.urlsafe_b64decode(jwk["x"] + "=" * (-len(jwk["x"]) % 4))
    return Ed25519PublicKey.from_public_bytes(raw)


def verify(token: str, jwk: dict, **kwargs) -> dict:
    """Verify an EdDSA JWS against a JWK; raises jwt exceptions on failure."""
    return jwt.decode(token, public_key_from_jwk(jwk), algorithms=["EdDSA"],
                      options={"verify_aud": False, **kwargs.pop("options", {})}, **kwargs)


def unverified_header(token: str) -> dict:
    return jwt.get_unverified_header(token)


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
