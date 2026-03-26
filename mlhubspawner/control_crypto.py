from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


_PROTOCOL_LABEL = b"mlhub-ssh-gateway-control-v1"
_PROTOCOL_VERSION = 1
_KEY_LENGTH = 32
_NONCE_LENGTH = 12


class ControlCryptoError(ValueError):
    """Raised when an encrypted control payload cannot be processed."""


class EncryptedControlCodec:
    def __init__(self, shared_secret: str):
        if not isinstance(shared_secret, str) or not shared_secret:
            raise ControlCryptoError("shared secret must be a non-empty string")
        self._cipher = AESGCM(self._derive_key(shared_secret))

    def encode(self, payload: Mapping[str, object]) -> bytes:
        plaintext = self._encode_json_object(payload, "control payload")
        nonce = os.urandom(_NONCE_LENGTH)
        ciphertext = self._cipher.encrypt(nonce, plaintext, _PROTOCOL_LABEL)
        envelope = {
            "version": _PROTOCOL_VERSION,
            "nonce": self._encode_b64(nonce),
            "ciphertext": self._encode_b64(ciphertext),
        }
        return self.encode_plaintext(envelope)

    def decode(self, line: bytes) -> dict[str, object]:
        if not line:
            raise ControlCryptoError("missing encrypted control payload")

        envelope = self.decode_plaintext(line, description="control envelope")
        if "nonce" not in envelope or "ciphertext" not in envelope:
            if "action" in envelope or "secret" in envelope:
                raise ControlCryptoError("plaintext control payloads are not supported")
            raise ControlCryptoError("invalid control envelope")

        version = envelope.get("version")
        if version != _PROTOCOL_VERSION:
            raise ControlCryptoError(f"unsupported control envelope version: {version!r}")

        nonce = self._decode_b64(envelope.get("nonce"), "nonce")
        if len(nonce) != _NONCE_LENGTH:
            raise ControlCryptoError(f"invalid nonce length: expected {_NONCE_LENGTH}, got {len(nonce)}")

        ciphertext = self._decode_b64(envelope.get("ciphertext"), "ciphertext")
        try:
            plaintext = self._cipher.decrypt(nonce, ciphertext, _PROTOCOL_LABEL)
        except InvalidTag as exc:
            raise ControlCryptoError("invalid shared secret or encrypted payload") from exc

        return self.decode_plaintext(plaintext, description="decrypted control payload")

    @staticmethod
    def encode_plaintext(payload: Mapping[str, object]) -> bytes:
        return EncryptedControlCodec._encode_json_object(payload, "control payload") + b"\n"

    @staticmethod
    def decode_plaintext(line: bytes, *, description: str = "control payload") -> dict[str, object]:
        return EncryptedControlCodec._decode_json_object(line, description)

    @staticmethod
    def _derive_key(shared_secret: str) -> bytes:
        kdf = Scrypt(
            salt=_PROTOCOL_LABEL,
            length=_KEY_LENGTH,
            n=2**14,
            r=8,
            p=1,
        )
        return kdf.derive(shared_secret.encode("utf-8"))

    @staticmethod
    def _encode_json_object(payload: Mapping[str, object], description: str) -> bytes:
        if not isinstance(payload, Mapping):
            raise ControlCryptoError(f"{description} must be a JSON object")
        try:
            encoded = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ControlCryptoError(f"{description} is not JSON serializable: {exc}") from exc
        return encoded

    @staticmethod
    def _decode_json_object(raw: bytes, description: str) -> dict[str, object]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlCryptoError(f"invalid {description}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ControlCryptoError(f"{description} must be a JSON object")
        return payload

    @staticmethod
    def _encode_b64(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    @staticmethod
    def _decode_b64(value: object, field_name: str) -> bytes:
        if not isinstance(value, str) or not value:
            raise ControlCryptoError(f"{field_name} must be a non-empty base64 string")
        try:
            return base64.b64decode(value.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise ControlCryptoError(f"invalid {field_name}: {exc}") from exc
